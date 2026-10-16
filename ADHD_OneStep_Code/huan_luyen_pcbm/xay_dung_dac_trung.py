from __future__ import annotations
from datetime import timedelta
from typing import List, Dict, Any
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

def _da_hoan_thanh_lan_thuc_hien(history):
    return {e["occurrence_id"] for e in history if e["event_type"] == "TASK_COMPLETED"}

def _da_nhac_lan_thuc_hien(history):
    return {e["occurrence_id"] for e in history if e["event_type"] == "REMINDER_SENT"}

def _da_hoan_lan_thuc_hien(history):
    return {e["occurrence_id"] for e in history if e["event_type"] == "SNOOZE"}

def _da_quen_lan_thuc_hien(history):
    return {e["occurrence_id"] for e in history if e["event_type"] in {"USER_FORGOT", "RECALL_FAILURE"}}

def _an_toan_ty_le(num: int, den: int):
    return (num / den) if den else None

def xay_dung_dac_trung(events, decision):
    t = decision["timestamp"]
    user_id = decision["user_id"]
    task_id = decision["task_id"]
    occ = decision["occurrence_id"]

    # Ranh giới chống rò rỉ dữ liệu nghiêm ngặt.
    history = [e for e in events if e["user_id"] == user_id and e["timestamp"] < t]

    hist_7d = [e for e in history if e["timestamp"] >= t - timedelta(days=7)]
    hist_30d = [e for e in history if e["timestamp"] >= t - timedelta(days=30)]

    created = dau_tien_nhiem_vu_da_tao_truoc(events, user_id, occ, t)
    task_data = (created or {}).get("data", {})
    reminder_data = decision.get("data", {})

    reminded_7d = _da_nhac_lan_thuc_hien(hist_7d)
    completed_7d = _da_hoan_thanh_lan_thuc_hien(hist_7d)
    snoozed_7d = _da_hoan_lan_thuc_hien(hist_7d)
    forgot_7d = _da_quen_lan_thuc_hien(hist_7d)

    same_task_hist = [e for e in history if e["task_id"] == task_id]
    same_task_reminded = _da_nhac_lan_thuc_hien(same_task_hist)
    same_task_completed = _da_hoan_thanh_lan_thuc_hien(same_task_hist)

    # Lịch sử độ trễ bắt đầu, mỗi lần thực hiện chỉ lấy một giá trị.
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

    first_hist_time = min((e["timestamp"] for e in history), default=t)
    history_days = max(0.0, (t - first_hist_time).total_seconds() / 86400.0)

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

        "completion_rate_7d": _an_toan_ty_le(
            len(completed_7d & reminded_7d), len(reminded_7d)
        ),
        "snooze_rate_7d": _an_toan_ty_le(
            len(snoozed_7d & reminded_7d), len(reminded_7d)
        ),
        "forget_rate_7d": _an_toan_ty_le(
            len(forgot_7d & reminded_7d), len(reminded_7d)
        ),
        "avg_start_delay_7d": (sum(delays) / len(delays)) if delays else None,

        "same_task_completion_rate": _an_toan_ty_le(
            len(same_task_completed & same_task_reminded), len(same_task_reminded)
        ),

        "event_count_before": len(history),
        "history_days": history_days,
        "is_cold_start": int(len(history) < 10),
    }
