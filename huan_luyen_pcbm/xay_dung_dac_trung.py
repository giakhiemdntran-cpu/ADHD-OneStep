from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math


# Timestamp in older OneStep SQLite records may omit a timezone while imported
# records may use Z/+00:00. Historical naive values were written in local VN time.
# Normalize only the copies passed to the feature builder: never rewrite SQLite.
_VN_TZ = timezone(timedelta(hours=7))


def _vn_aware_timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"PCBM timestamp is not datetime: {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_VN_TZ)
    return value.astimezone(_VN_TZ)


def _normalise_feature_times(events, decision):
    safe_decision = dict(decision)
    safe_decision["timestamp"] = _vn_aware_timestamp(decision["timestamp"])
    safe_events = []
    for e in events:
        if e.get("user_id") != decision.get("user_id"):
            continue
        item = dict(e)
        item["timestamp"] = _vn_aware_timestamp(e["timestamp"])
        safe_events.append(item)
    return safe_events, safe_decision


def thoi_gian_cua_ngay(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def dau_tien_nhiem_vu_da_tao_truoc(events, user_id, occurrence_id, decision_time):
    xs = [
        e for e in events
        if e["user_id"] == user_id
        and e["occurrence_id"] == occurrence_id
        and e["event_type"] == "TASK_CREATED"
        and e["timestamp"] < decision_time
    ]
    return xs[-1] if xs else None


def _cac_lan(history, event_types):
    return {e["occurrence_id"] for e in history if e["event_type"] in event_types}


def _an_toan_ty_le(num: int, den: int):
    return (num / den) if den else None


def _thong_ke_recall(history, t, days):
    start = t - timedelta(days=days)
    xs = [e for e in history if e["timestamp"] >= start and e["event_type"] in {"RECALL_SUCCESS", "RECALL_FAILURE"}]
    if not xs:
        return None, 0
    success = sum(e["event_type"] == "RECALL_SUCCESS" for e in xs)
    return success / len(xs), len(xs)


def _streak_recall(history):
    xs = [e for e in history if e["event_type"] in {"RECALL_SUCCESS", "RECALL_FAILURE"}]
    if not xs:
        return 0, 0, "none", None
    xs.sort(key=lambda e: e["timestamp"])
    last = xs[-1]
    success_streak = 0
    failure_streak = 0
    for e in reversed(xs):
        if e["event_type"] == "RECALL_SUCCESS" and failure_streak == 0:
            success_streak += 1
        elif e["event_type"] == "RECALL_FAILURE" and success_streak == 0:
            failure_streak += 1
        else:
            break
    return success_streak, failure_streak, (
        "success" if last["event_type"] == "RECALL_SUCCESS" else "failure"
    ), last["timestamp"]


def xay_dung_dac_trung(events, decision):
    """Xây đặc trưng PCBM v4 với ranh giới thời gian nghiêm ngặt.

    Tất cả đặc trưng lịch sử chỉ dùng sự kiện xảy ra trước decision_time để tránh leakage.
    v4 bổ sung tín hiệu recall 1/3/7 ngày, streak, cùng nhiệm vụ và feedback gần nhất.
    """
    # Keep legacy naive (+07 local clock) and timezone-aware imported events
    # comparable before the FIRST time comparison; does not modify input data.
    events, decision = _normalise_feature_times(events, decision)
    t = decision["timestamp"]
    user_id = decision["user_id"]
    task_id = decision["task_id"]
    occ = decision["occurrence_id"]

    history = [e for e in events if e["user_id"] == user_id and e["timestamp"] < t]
    hist_7d = [e for e in history if e["timestamp"] >= t - timedelta(days=7)]
    hist_30d = [e for e in history if e["timestamp"] >= t - timedelta(days=30)]

    created = dau_tien_nhiem_vu_da_tao_truoc(events, user_id, occ, t)
    task_data = (created or {}).get("data", {})
    reminder_data = decision.get("data", {})

    reminded_7d = _cac_lan(hist_7d, {"REMINDER_SENT"})
    completed_7d = _cac_lan(hist_7d, {"TASK_COMPLETED"})
    snoozed_7d = _cac_lan(hist_7d, {"SNOOZE"})
    forgot_7d = _cac_lan(hist_7d, {"USER_FORGOT", "RECALL_FAILURE"})

    reminded_30d = _cac_lan(hist_30d, {"REMINDER_SENT"})
    completed_30d = _cac_lan(hist_30d, {"TASK_COMPLETED"})

    same_task_hist = [e for e in history if e["task_id"] == task_id]
    same_task_reminded = _cac_lan(same_task_hist, {"REMINDER_SENT"})
    same_task_completed = _cac_lan(same_task_hist, {"TASK_COMPLETED"})
    same_task_recall = [e for e in same_task_hist if e["event_type"] in {"RECALL_SUCCESS", "RECALL_FAILURE"}]
    same_task_recall_success = sum(e["event_type"] == "RECALL_SUCCESS" for e in same_task_recall)

    # Lịch sử độ trễ bắt đầu, mỗi occurrence chỉ lấy một giá trị.
    starts = {}
    reminds = {}
    for e in hist_7d:
        if e["event_type"] == "REMINDER_SENT":
            reminds[e["occurrence_id"]] = e["timestamp"]
        elif e["event_type"] == "TASK_STARTED":
            starts[e["occurrence_id"]] = e["timestamp"]
    delays = []
    for oid, rt in reminds.items():
        st = starts.get(oid)
        if st and st >= rt:
            delays.append((st - rt).total_seconds() / 60.0)

    recall_rate_1d, recall_count_1d = _thong_ke_recall(history, t, 1)
    recall_rate_3d, recall_count_3d = _thong_ke_recall(history, t, 3)
    recall_rate_7d, recall_count_7d = _thong_ke_recall(history, t, 7)
    recall_success_streak, recall_failure_streak, last_recall_feedback, last_recall_time = _streak_recall(history)

    first_hist_time = min((e["timestamp"] for e in history), default=t)
    history_days = max(0.0, (t - first_hist_time).total_seconds() / 86400.0)
    minutes_since_last_recall = None
    if last_recall_time is not None:
        minutes_since_last_recall = max(0.0, (t - last_recall_time).total_seconds() / 60.0)

    # Human-in-the-loop history BEFORE decision_time only; never used as a target label.
    feedback_events = [e for e in hist_30d if e['event_type'] in
                       {'SUPPORT_REVIEW_KEPT','SUPPORT_REVIEW_ACCEPTED','SUPPORT_REVIEW_DEFERRED',
                        'REMINDER_FEEDBACK','SUPPORT_ACCEPTED'}]
    choices = [e for e in feedback_events if e['event_type'] in
               {'SUPPORT_REVIEW_KEPT','SUPPORT_REVIEW_ACCEPTED','SUPPORT_REVIEW_DEFERRED'}]
    n_choices = len(choices)
    keep_count = sum(e['event_type']=='SUPPORT_REVIEW_KEPT' for e in choices)
    accept_count = sum(e['event_type']=='SUPPORT_REVIEW_ACCEPTED' for e in choices)
    more_count = sum((e.get('data') or {}).get('feedback')=='too_little' for e in feedback_events)
    less_count = sum((e.get('data') or {}).get('feedback')=='too_much' for e in feedback_events)

    hour = t.hour
    weekday = t.weekday()

    return {
        "user_id": user_id,
        "task_id": task_id,
        "occurrence_id": occ,
        "decision_time": t.isoformat(),
        "decision_type": decision["event_type"],

        "hour": hour,
        "weekday": weekday,
        "is_weekend": int(weekday >= 5),
        "time_of_day": thoi_gian_cua_ngay(hour),
        "hour_sin": math.sin(2 * math.pi * hour / 24.0),
        "hour_cos": math.cos(2 * math.pi * hour / 24.0),

        "task_type": task_data.get("task_type", "UNKNOWN"),
        "priority": task_data.get("priority"),
        "estimated_minutes": task_data.get("estimated_minutes"),

        "prompt_level": reminder_data.get("prompt_level"),
        "reminder_type": reminder_data.get("reminder_type", "UNKNOWN"),
        "channel": reminder_data.get("channel", "UNKNOWN"),

        "completion_rate_7d": _an_toan_ty_le(len(completed_7d & reminded_7d), len(reminded_7d)),
        "completion_rate_30d": _an_toan_ty_le(len(completed_30d & reminded_30d), len(reminded_30d)),
        "snooze_rate_7d": _an_toan_ty_le(len(snoozed_7d & reminded_7d), len(reminded_7d)),
        "forget_rate_7d": _an_toan_ty_le(len(forgot_7d & reminded_7d), len(reminded_7d)),
        "avg_start_delay_7d": (sum(delays) / len(delays)) if delays else None,

        # PCBM v4: tín hiệu recall trực tiếp.
        "recall_rate_1d": recall_rate_1d,
        "recall_rate_3d": recall_rate_3d,
        "recall_rate_7d": recall_rate_7d,
        "recall_count_1d": recall_count_1d,
        "recall_count_3d": recall_count_3d,
        "recall_count_7d": recall_count_7d,
        "recall_success_streak": recall_success_streak,
        "recall_failure_streak": recall_failure_streak,
        "last_recall_feedback": last_recall_feedback,
        "minutes_since_last_recall": minutes_since_last_recall,
        "same_task_recall_rate": _an_toan_ty_le(same_task_recall_success, len(same_task_recall)),
        "same_task_recall_count": len(same_task_recall),
        "same_task_completion_rate": _an_toan_ty_le(len(same_task_completed & same_task_reminded), len(same_task_reminded)),

        "user_feedback_review_count_30d": n_choices,
        "user_feedback_keep_rate_30d": (keep_count / n_choices) if n_choices else None,
        "user_feedback_accept_rate_30d": (accept_count / n_choices) if n_choices else None,
        "user_feedback_more_count_30d": more_count,
        "user_feedback_less_count_30d": less_count,
        "event_count_before": len(history),
        "history_days": history_days,
        "is_cold_start": int(len(history) < 10),
    }
