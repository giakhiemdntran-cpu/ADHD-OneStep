from __future__ import annotations
from datetime import timedelta


def _dau_tien(events, types, start, end, user_id, occurrence_id):
    xs = [
        e for e in events
        if e["user_id"] == user_id
        and e["occurrence_id"] == occurrence_id
        and e["event_type"] in types
        and start < e["timestamp"] <= end
    ]
    xs.sort(key=lambda e: e["timestamp"])
    return xs[0] if xs else None


def xay_dung_nhan(events, decision):
    """Nhãn PCBM v4.

    Thay đổi quan trọng: y_recall_success chỉ được gán sau một generic cue.
    Reminder explicit không còn được dùng làm mẫu 'tự nhớ', vì explicit reminder đã chứa
    nội dung nhiệm vụ và có thể làm nhãn recall trở nên quá dễ / sai ý nghĩa.
    """
    t = decision["timestamp"]
    occ = decision["occurrence_id"]
    user_id = decision["user_id"]
    reminder_type = str((decision.get("data") or {}).get("reminder_type", "")).lower().strip()

    out = {
        "y_recall_success": None,
        "y_started_within_10m": 0,
        "y_start_delay_minutes": None,
        "y_complete_within_30m": 0,
        "y_complete_within_60m": 0,
        "y_completion_delay_minutes": None,
        "y_snooze": 0,
        "y_forgot": None,
    }

    # v4: tự nhớ = phản hồi recall rõ ràng sau generic cue, cửa sổ tối đa 2 phút.
    if reminder_type == "generic":
        recall = _dau_tien(
            events,
            {"RECALL_SUCCESS", "RECALL_FAILURE"},
            t, t + timedelta(minutes=2), user_id, occ
        )
        if recall:
            out["y_recall_success"] = int(recall["event_type"] == "RECALL_SUCCESS")

    started = _dau_tien(events, {"TASK_STARTED"}, t, t + timedelta(minutes=60), user_id, occ)
    if started:
        delay = (started["timestamp"] - t).total_seconds() / 60.0
        out["y_start_delay_minutes"] = round(delay, 3)
        out["y_started_within_10m"] = int(delay <= 10)

    completed = _dau_tien(events, {"TASK_COMPLETED"}, t, t + timedelta(minutes=180), user_id, occ)
    if completed:
        delay = (completed["timestamp"] - t).total_seconds() / 60.0
        out["y_completion_delay_minutes"] = round(delay, 3)
        out["y_complete_within_30m"] = int(delay <= 30)
        out["y_complete_within_60m"] = int(delay <= 60)

    snooze = _dau_tien(events, {"SNOOZE"}, t, t + timedelta(minutes=10), user_id, occ)
    out["y_snooze"] = int(snooze is not None)

    forgot = _dau_tien(
        events, {"USER_FORGOT", "USER_REMEMBERED", "RECALL_FAILURE", "RECALL_SUCCESS"},
        t, t + timedelta(minutes=10), user_id, occ
    )
    if forgot:
        if forgot["event_type"] in {"USER_FORGOT", "RECALL_FAILURE"}:
            out["y_forgot"] = 1
        elif forgot["event_type"] in {"USER_REMEMBERED", "RECALL_SUCCESS"}:
            out["y_forgot"] = 0

    return out
