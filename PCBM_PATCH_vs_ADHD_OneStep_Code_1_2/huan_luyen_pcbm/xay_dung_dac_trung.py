from __future__ import annotations
from datetime import timedelta
import math


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

        "event_count_before": len(history),
        "history_days": history_days,
        "is_cold_start": int(len(history) < 10),
    }
