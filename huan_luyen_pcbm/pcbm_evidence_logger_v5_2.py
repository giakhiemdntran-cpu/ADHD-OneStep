"""Append-only, explicit evidence recorder for future real-world PCBM observation.

Integration points: call record_user_initiated_start() from the actual user action,
and record_verified_observation() only from a verified human observation workflow.
Neither API may be invoked merely because an event is absent.
"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _iso(ts):
    if ts is None: ts=datetime.now(timezone.utc)
    if isinstance(ts,str): ts=datetime.fromisoformat(ts)
    if ts.tzinfo is None:raise ValueError('Phải cung cấp thời gian có múi giờ (ISO8601)')
    return ts.isoformat()


def _add(db_path,user_id,task_id,occurrence_id,event_type,data,ts):
    if not all(str(v or '').strip() for v in (user_id,task_id,occurrence_id)):
        raise ValueError('Thiếu user_id, task_id hoặc occurrence_id')
    db=Path(db_path)
    if not db.exists():raise FileNotFoundError(db)
    with sqlite3.connect(str(db)) as c:
        c.execute('''INSERT INTO pcbm_events (user_id,task_id,occurrence_id,event_type,data_json,created_at)
                     VALUES (?,?,?,?,?,?)''',(str(user_id),str(task_id),str(occurrence_id),event_type,json.dumps(data,ensure_ascii=False),_iso(ts)))
        return c.execute('SELECT last_insert_rowid()').fetchone()[0]


def record_user_initiated_start(db_path, user_id, task_id, occurrence_id, *, action_channel, timestamp=None):
    """Only call when user actually presses Start/acts of their own initiative.

    A generic response after a reminder must NEVER call this function.
    The labeler determines pre-first-reminder eligibility after event ordering.
    """
    if action_channel not in ('buddy_ui','oneband_ui','web_ui','verified_observer'):
        raise ValueError('action_channel không hợp lệ')
    return _add(db_path,user_id,task_id,occurrence_id,'TASK_STARTED',
                {'evidence_source':'user_initiated_action','action_channel':action_channel,
                 'protocol':'v5.2','human_confirmed':action_channel=='verified_observer'},timestamp)


def record_verified_observation(db_path,user_id,task_id,occurrence_id,*,coverage_start,coverage_end,reviewer_id,evidence_reference,verified_continuous_coverage,timestamp=None):
    """Human attestation; must be backed by reviewed evidence, never guessed from missing events.
    False coverage flag is allowed and will NOT create a negative label.
    """
    if not str(reviewer_id or '').strip() or not str(evidence_reference or '').strip():
        raise ValueError('Bắt buộc người xác nhận và tham chiếu bằng chứng quan sát')
    start=_iso(coverage_start);end=_iso(coverage_end)
    if datetime.fromisoformat(start)>=datetime.fromisoformat(end):
        raise ValueError('coverage_end phải sau coverage_start')
    if verified_continuous_coverage is not True:
        raise ValueError('Chỉ ghi sự kiện VERIFIED khi đã xác minh quan sát liên tục')
    recorded_at=_iso(timestamp)
    if datetime.fromisoformat(recorded_at)<datetime.fromisoformat(end):
        raise ValueError('Thời điểm xác nhận không thể trước khi phiên quan sát kết thúc')
    return _add(db_path,user_id,task_id,occurrence_id,'OBSERVATION_VERIFIED',
                {'verified_continuous_coverage':True,'coverage_start':start,'coverage_end':end,
                 'reviewer_id':str(reviewer_id),'evidence_reference':str(evidence_reference),
                 'protocol':'v5.2'},recorded_at)
