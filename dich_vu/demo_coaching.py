from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
import pandas as pd

from cau_hinh import BASE_DIR


class DemoCoachingManager:
    """Luồng demo riêng, không ghi vào dữ liệu thật của OneStep."""

    def __init__(self, dich_vu_pcbm):
        self.pcbm = dich_vu_pcbm
        self.data_dir = Path(BASE_DIR) / "demo_coaching"
        self.profiles = json.loads((self.data_dir / "profiles.json").read_text(encoding="utf-8"))
        self._seed = self._load_events()
        self.active = False
        self.profile_id = None
        self.state = "idle"
        self.events = []
        self.task_title = "Làm bài Toán"
        self.base_level = 1
        self._seq = 0
        self._decision_time = None
        self.last_result = None

    def _load_events(self):
        out = {}
        with (self.data_dir / "demo_profiles.jsonl").open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                d["timestamp"] = pd.Timestamp(d["timestamp"]).to_pydatetime()
                out.setdefault(d["user_id"], []).append(d)
        for uid in out:
            out[uid].sort(key=lambda e: e["timestamp"])
        return out

    def danh_sach_profile(self):
        return list(self.profiles)

    def lay_profile_hien_tai(self):
        return next((x for x in self.profiles if x.get("user_id") == self.profile_id), {})

    def lich_goi_y_trong_ngay(self, profile_id=None):
        uid = profile_id or self.profile_id or self.profiles[0]["user_id"]
        prof = next((x for x in self.profiles if x.get("user_id") == uid), {})
        return [dict(item) for item in (prof.get("daily_plan") or [])]

    def tom_tat_thoi_quen(self, profile_id=None):
        uid = profile_id or self.profile_id or self.profiles[0]["user_id"]
        prof = next((x for x in self.profiles if x.get("user_id") == uid), {})
        return prof.get("habit_summary", "")

    def goi_y_trong_ngay_text(self, profile_id=None, max_items=4):
        items = self.lich_goi_y_trong_ngay(profile_id)[:max_items]
        if not items:
            return ""
        return "🗓 Gợi ý hôm nay: " + "  •  ".join(
            f"{x.get('time','--:--')} {x.get('title','')}" for x in items
        )

    def _append(self, event_type, data=None, minutes=0):
        self._seq += 1
        ts = self._decision_time + timedelta(minutes=minutes, seconds=self._seq)
        self.events.append({
            "event_id": f"DEMO_LIVE_{self._seq}",
            "user_id": self.profile_id,
            "task_id": "DEMO::study",
            "occurrence_id": "DEMO_SESSION",
            "timestamp": ts,
            "event_type": event_type,
            "data": data or {},
        })

    def _evaluate(self):
        result = self.pcbm.thu_nghiem_kich_ban_tu_su_kien(
            self.events, self.profile_id, self.task_title,
            base_prompt_level=self.base_level, estimated_minutes=30,
            priority=1, channel="buddy", decision_time=self._decision_time + timedelta(minutes=20, seconds=self._seq),
        )
        self.last_result = result
        return result

    def reset(self, profile_id=None):
        uid = profile_id or self.profile_id or self.profiles[0]["user_id"]
        if uid not in self._seed:
            uid = self.profiles[0]["user_id"]
        self.profile_id = uid
        self.events = [dict(e, data=dict(e.get("data") or {})) for e in self._seed[uid]]
        self._decision_time = max(e["timestamp"] for e in self.events) + timedelta(minutes=1)
        self._seq = 0
        self.state = "idle"
        self.active = False
        self.last_result = None
        return self._evaluate()

    def start(self, profile_id):
        self.reset(profile_id)
        self.active = True
        self.state = "wait_recall"
        r = self.last_result or self._evaluate()
        p = r.get("prediction") or {}
        cur = self.base_level
        rec = int(p.get("recommended_prompt_level", cur))
        rp = p.get("recall_percent")
        return {
            "reply": "Có một việc em cần làm. Em nhớ là việc gì không?",
            "state": "idle", "refresh": False, "demo": True,
            "demo_status": self.status_text(r),
            "demo_note": f"PCBM trước phiên: Recall {rp}% • Level {cur} → {rec}",
            "daily_suggestions": self.goi_y_trong_ngay_text(profile_id),
            "habit_summary": self.tom_tat_thoi_quen(profile_id),
        }

    def stop(self):
        self.active = False
        self.state = "idle"
        return {"reply": "Đã kết thúc Demo Coaching. Dữ liệu người dùng thật không bị thay đổi.", "state": "idle", "demo": True}

    def status_text(self, result=None):
        r = result or self.last_result or self._evaluate()
        p = r.get("prediction") or {}
        prof = next((x for x in self.profiles if x["user_id"] == self.profile_id), {})
        return (f"🎬 DEMO • {prof.get('label', self.profile_id)} • "
                f"Recall {p.get('recall_percent')}% • "
                f"PCBM Level {self.base_level} → {p.get('recommended_prompt_level', self.base_level)}")

    def handle(self, text):
        if not self.active:
            return None
        t = (text or "").strip().lower()
        if any(x in t for x in ("dừng demo", "thoát demo", "kết thúc demo")):
            return self.stop()

        if self.state == "wait_recall":
            if any(x in t for x in ("toán", "bài toán", "làm bài")):
                self._append("RECALL_SUCCESS", {"prompt_level": 1, "source": "demo_generic_cue"})
                self.state = "wait_start"
                return {"reply": "Đúng rồi. Em chưa cần làm hết ngay. Hãy mở vở Toán và làm câu đầu tiên trước.",
                        "state": "success", "demo": True, "demo_status": self.status_text(self._evaluate())}
            self._append("RECALL_FAILURE", {"prompt_level": 1, "source": "demo_generic_cue"})
            self.state = "wait_start"
            return {"reply": "Không sao. Việc cần làm là bài Toán. Mình bắt đầu thật nhỏ nhé: chỉ mở vở trước thôi.",
                    "state": "idle", "demo": True, "demo_status": self.status_text(self._evaluate())}

        if self.state == "wait_start":
            if any(x in t for x in ("chưa muốn", "không muốn", "lười", "để lát", "chưa sẵn sàng")):
                self._append("SNOOZE", {"minutes": 5, "source": "demo_hesitation"})
                return {"reply": "Mình chỉ bắt đầu 5 phút thôi. Em mở vở trước nhé; chưa cần hoàn thành cả bài.",
                        "state": "idle", "demo": True, "demo_status": self.status_text(self._evaluate())}
            if any(x in t for x in ("bắt đầu", "được", "ok", "mở vở")):
                self._append("REMINDER_SENT", {"prompt_level": 1, "reminder_type": "generic", "channel": "buddy"})
                self._append("TASK_STARTED", {"source": "demo_user_started"}, minutes=4)
                self.state = "in_progress"
                return {"reply": "Tốt. Buddy đã ghi nhận em bắt đầu. Bây giờ chỉ tập trung vào câu đầu tiên.",
                        "state": "success", "demo": True, "demo_status": self.status_text(self._evaluate())}
            return {"reply": "Khi sẵn sàng, em chỉ cần nói ‘bắt đầu’. Mình sẽ đi từng bước một.", "state": "idle", "demo": True}

        if self.state in {"in_progress", "recovery"}:
            if any(x in t for x in ("mất tập trung", "quên đang làm", "bị phân tâm", "không tập trung")):
                self._append("REMINDER_FEEDBACK", {"feedback": "needs_recovery", "source": "demo_distraction"}, minutes=8)
                self.state = "recovery"
                return {"reply": "Em đang làm bài Toán. Quay lại câu đầu tiên nhé. Chỉ cần hoàn thành câu này trước.",
                        "state": "idle", "demo": True, "demo_status": self.status_text(self._evaluate())}
            if any(x in t for x in ("xong", "hoàn thành", "làm xong")):
                self._append("TASK_COMPLETED", {"actual_minutes": 24, "source": "demo_completed"}, minutes=24)
                r = self._evaluate()
                self.state = "completed"
                p = r.get("prediction") or {}
                return {
                    "reply": ("Hoàn thành rồi. PCBM đã dùng lịch sử demo và kết quả phiên này để đánh giá lại. "
                              f"Khả năng tự nhớ hiện khoảng {p.get('recall_percent')}%. "
                              f"Hệ thống đề xuất Level {self.base_level} → {p.get('recommended_prompt_level', self.base_level)}. "
                              "Đây là khuyến nghị coaching, không tự động đổi mức hỗ trợ."),
                    "state": "success", "demo": True, "demo_status": self.status_text(r),
                }
            return {"reply": "Em cứ tiếp tục. Nếu bị mất tập trung, nói với Buddy; khi xong hãy nói ‘xong rồi’.", "state": "idle", "demo": True}

        if self.state == "completed":
            return {"reply": "Phiên demo đã hoàn tất. Bạn có thể Reset Demo hoặc chọn hồ sơ khác để thấy PCBM coaching khác nhau.",
                    "state": "success", "demo": True, "demo_status": self.status_text()}
        return {"reply": "Demo đang sẵn sàng.", "state": "idle", "demo": True}
