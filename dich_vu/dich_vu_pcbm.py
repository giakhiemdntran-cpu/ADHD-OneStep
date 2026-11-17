import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from cau_hinh import (
    PCBM_ENABLED,
    PCBM_APPLY_PROMPT_LEVEL,
    PCBM_RECALL_MODEL,
    PCBM_COMPLETION_MODEL,
    PCBM_SAMPLE_DATA,
)
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl
from dich_vu.cai_dat_nguoi_dung import tai_cai_dat
from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung


class DichVuPCBM:
    """Tích hợp mô hình hành vi nhận thức cá nhân PCBM với dữ liệu sự kiện và mô hình dự đoán."""

    def __init__(self, user_id=None):
        self.duoc_bat = bool(PCBM_ENABLED)
        self.ap_dung_muc_nhac = bool(PCBM_APPLY_PROMPT_LEVEL)
        self._mo_hinh_tu_nho = None
        self._mo_hinh_hoan_thanh = None
        self.active_user_id = str(user_id or tai_cai_dat().get("active_user_id") or "test_U036").strip() or "test_U036"
        self.tai_lai_mo_hinh()


    def dat_nguoi_dung_hien_tai(self, user_id):
        user_id = str(user_id or "test_U036").strip() or "test_U036"
        self.active_user_id = user_id
        return self.active_user_id

    def lay_nguoi_dung_hien_tai(self):
        return self.active_user_id

    def _user(self, user_id=None):
        return str(user_id or self.active_user_id or "test_U036").strip() or "test_U036"

    def tai_lai_mo_hinh(self):
        self._mo_hinh_tu_nho = self._tai_mo_hinh(PCBM_RECALL_MODEL)
        self._mo_hinh_hoan_thanh = self._tai_mo_hinh(PCBM_COMPLETION_MODEL)

    def _tai_mo_hinh(self, path):
        try:
            p = Path(path)
            if not p.exists():
                return None
            import joblib
            return joblib.load(p)
        except Exception as e:
            print("[PCBM MODEL LOAD ERROR]", path, e)
            return None

    def lay_trang_thai_dich_vu(self):
        with lay_ket_noi_csdl() as c:
            n_events = c.execute("SELECT COUNT(*) FROM pcbm_events").fetchone()[0]
            n_preds = c.execute("SELECT COUNT(*) FROM pcbm_predictions").fetchone()[0]
        meta = None
        meta_path = Path(PCBM_RECALL_MODEL).parent / "pcbm_model_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = None
        with lay_ket_noi_csdl() as c:
            last_run = c.execute(
                "SELECT * FROM pcbm_training_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "enabled": self.duoc_bat,
            "apply_prompt_level": self.ap_dung_muc_nhac,
            "recall_model_loaded": self._mo_hinh_tu_nho is not None,
            "completion_model_loaded": self._mo_hinh_hoan_thanh is not None,
            "recall_model_path": str(PCBM_RECALL_MODEL),
            "completion_model_path": str(PCBM_COMPLETION_MODEL),
            "sample_data": str(PCBM_SAMPLE_DATA),
            "live_event_count": n_events,
            "prediction_count": n_preds,
            "mode": "sqlite_personal_training + live_event_collection",
            "model_meta": meta,
            "last_training_run": dict(last_run) if last_run else None,
        }

    def ghi_su_kien(self, event_type, task_id=None, occurrence_id=None, data=None,
                  user_id=None, timestamp=None):
        if not self.duoc_bat:
            return None
        user_id = self._user(user_id)
        now = timestamp or datetime.now().isoformat(timespec="seconds")
        data = data or {}
        with lay_ket_noi_csdl() as c:
            cur = c.execute(
                """INSERT INTO pcbm_events(
                    user_id, task_id, occurrence_id, event_type, data_json, created_at
                ) VALUES(?,?,?,?,?,?)""",
                (
                    user_id,
                    str(task_id) if task_id is not None else None,
                    str(occurrence_id) if occurrence_id is not None else None,
                    str(event_type).upper(),
                    json.dumps(data, ensure_ascii=False),
                    now,
                )
            )
            return cur.lastrowid

    def lay_su_kien_gan_day(self, limit=200):
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                "SELECT * FROM pcbm_events ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d.pop("data_json") or "{}")
            except Exception:
                d["data"] = {}
            out.append(d)
        return out

    def lay_du_doan_gan_day(self, limit=100):
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                "SELECT * FROM pcbm_predictions ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("features_json", "output_json"):
                try:
                    d[key.replace("_json", "")] = json.loads(d.pop(key) or "{}")
                except Exception:
                    d[key.replace("_json", "")] = {}
            out.append(d)
        return out

    def _db_su_kien(self, user_id=None):
        user_id = self._user(user_id)
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                "SELECT * FROM pcbm_events WHERE user_id=? ORDER BY created_at,id",
                (user_id,)
            ).fetchall()
        events = []
        for r in rows:
            try:
                data = json.loads(r["data_json"] or "{}")
            except Exception:
                data = {}
            try:
                ts = pd.Timestamp(r["created_at"]).to_pydatetime()
            except Exception:
                continue
            events.append({
                "event_id": f"DB{r['id']}",
                "user_id": r["user_id"],
                "task_id": str(r["task_id"] or ""),
                "occurrence_id": str(r["occurrence_id"] or ""),
                "timestamp": ts,
                "event_type": r["event_type"],
                "data": data,
            })
        return events

    def _nhiem_vu_da_tao_mo_phong(self, current_task, task_row, decision_time, user_id):
        created_at = task_row.get("created_at") or (
            decision_time - timedelta(minutes=1)
        ).isoformat()
        try:
            ts = pd.Timestamp(created_at).to_pydatetime()
        except Exception:
            ts = decision_time - timedelta(minutes=1)
        if ts >= decision_time:
            ts = decision_time - timedelta(seconds=1)
        return {
            "event_id": "SYNTH_TASK_CREATED",
            "user_id": user_id,
            "task_id": str(current_task.get("task_id") or ""),
            "occurrence_id": str(current_task.get("occurrence_id") or ""),
            "timestamp": ts,
            "event_type": "TASK_CREATED",
            "data": {
                "task_type": task_row.get("task_type") or self._suy_ra_nhiem_vu_loai(task_row.get("title")),
                "priority": task_row.get("priority") or 1,
                "estimated_minutes": task_row.get("estimated_minutes"),
                "title": task_row.get("title"),
            }
        }

    @staticmethod
    def _suy_ra_nhiem_vu_loai(title):
        t = (title or "").lower()
        if any(x in t for x in ("toán", "bài", "học", "homework", "đọc")):
            return "study"
        if any(x in t for x in ("cặp", "chuẩn bị", "đồ", "mang")):
            return "preparation"
        if any(x in t for x in ("uống", "thuốc", "nước", "ăn")):
            return "self_care"
        return "general"

    def _du_doan_xac_suat(self, bundle, features):
        if not bundle:
            return None
        pipe = bundle.get("pipeline")
        cols = bundle.get("feature_columns") or []
        row = {c: features.get(c) for c in cols}
        X = pd.DataFrame([row], columns=cols)
        try:
            p = pipe.predict_proba(X)
            classes = list(pipe.named_steps["model"].classes_)
            if 1 in classes:
                return float(p[0][classes.index(1)])
            return float(p[0][-1])
        except Exception as e:
            print("[PCBM PREDICT ERROR]", e)
            return None

    def de_xuat_muc_ho_tro(self, current_task, base_prompt_level=1, user_id=None):
        user_id = self._user(user_id)
        if not self.duoc_bat or not current_task or current_task.get("done"):
            return {
                "enabled": self.duoc_bat,
                "recommended_prompt_level": base_prompt_level,
                "applied": False,
            }

        decision_time = datetime.now()
        with lay_ket_noi_csdl() as c:
            task_row = c.execute(
                "SELECT * FROM tasks WHERE id=?", (current_task["task_id"],)
            ).fetchone()
        task_row = dict(task_row) if task_row else {
            "id": current_task.get("task_id"),
            "title": current_task.get("task_name"),
            "estimated_minutes": current_task.get("estimated_minutes"),
            "created_at": (decision_time - timedelta(minutes=1)).isoformat(),
        }

        events = self._db_su_kien(user_id)
        # Chỉ thêm TASK_CREATED mô phỏng khi lần thực hiện này chưa có sự kiện lịch sử tương ứng.
        occ = str(current_task.get("occurrence_id") or "")
        if not any(
            e["occurrence_id"] == occ and e["event_type"] == "TASK_CREATED"
            for e in events
        ):
            events.append(
                self._nhiem_vu_da_tao_mo_phong(
                    current_task, task_row, decision_time, user_id
                )
            )

        decision = {
            "event_id": "LIVE_DECISION",
            "user_id": user_id,
            "task_id": str(current_task.get("task_id") or ""),
            "occurrence_id": occ,
            "timestamp": decision_time,
            "event_type": "REMINDER_SENT",
            "data": {
                "prompt_level": int(base_prompt_level),
                "reminder_type": "generic" if int(base_prompt_level) <= 1 else "explicit",
                "channel": "buddy",
            }
        }

        # PCBM v4: mô hình recall dự đoán khả năng nhớ sau một generic cue.
        # Vì vậy feature inference của recall luôn mô phỏng generic cue mức 1;
        # mô hình completion vẫn dùng reminder hiện tại.
        recall_decision = dict(decision)
        recall_decision["data"] = dict(decision["data"])
        recall_decision["data"]["reminder_type"] = "generic"
        recall_decision["data"]["prompt_level"] = 1

        recall_features = xay_dung_dac_trung(events, recall_decision)
        completion_features = xay_dung_dac_trung(events, decision)
        recall_p = self._du_doan_xac_suat(self._mo_hinh_tu_nho, recall_features)
        completion_p = self._du_doan_xac_suat(self._mo_hinh_hoan_thanh, completion_features)

        recommended = int(base_prompt_level)
        reason = "KEEP_BASE_LEVEL_ADVISORY_ONLY"
        if recall_p is not None:
            if recall_p >= 0.80 and recommended > 0:
                recommended -= 1
                reason = "HIGH_RECALL_PROBABILITY_SUGGEST_FADE_ONE_LEVEL"
            elif recall_p < 0.45 and recommended < 2:
                recommended += 1
                reason = "LOW_RECALL_PROBABILITY_SUGGEST_MORE_SUPPORT"

        output = {
            "recall_probability": recall_p,
            "completion_30m_probability": completion_p,
            "base_prompt_level": int(base_prompt_level),
            "recommended_prompt_level": int(recommended),
            # v4 giữ advisory-only: không tự động giảm/tăng mức hỗ trợ.
            "applied": False,
            "reason_code": reason,
            "training_version": "PCBM",
            "model_note": "PCBM advisory-only; recall = response after generic cue.",
        }

        with lay_ket_noi_csdl() as c:
            c.execute(
                """INSERT INTO pcbm_predictions(
                    user_id, task_id, occurrence_id, decision_type,
                    features_json, output_json, created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    user_id,
                    str(current_task.get("task_id") or ""),
                    occ,
                    "REMINDER_SENT",
                    json.dumps({"recall": recall_features, "completion": completion_features}, ensure_ascii=False, default=str),
                    json.dumps(output, ensure_ascii=False),
                    decision_time.isoformat(timespec="seconds"),
                )
            )

        return output


    # ------------------------------------------------------------------
    # PCBM Playground / Admin demo helpers
    # ------------------------------------------------------------------
    def liet_ke_nguoi_dung(self, limit=200):
        """Liệt kê user có dữ liệu PCBM để dùng trong màn hình Admin Playground."""
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                """SELECT user_id, COUNT(*) AS event_count,
                          MIN(created_at) AS first_event,
                          MAX(created_at) AS last_event
                   FROM pcbm_events
                   GROUP BY user_id
                   ORDER BY event_count DESC, user_id
                   LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _pct(v):
        return None if v is None else round(float(v) * 100.0, 1)

    @staticmethod
    def _ly_do_tieng_viet(code):
        return {
            "HIGH_RECALL_PROBABILITY_SUGGEST_FADE_ONE_LEVEL":
                "Khả năng tự nhớ cao; có thể giảm một mức hỗ trợ và ưu tiên quan sát.",
            "LOW_RECALL_PROBABILITY_SUGGEST_MORE_SUPPORT":
                "Khả năng tự nhớ thấp; nên tăng một mức hỗ trợ để nhắc rõ hơn.",
            "KEEP_BASE_LEVEL_ADVISORY_ONLY":
                "Khả năng tự nhớ ở vùng trung gian; giữ mức hỗ trợ hiện tại.",
        }.get(code, "Giữ mức hỗ trợ hiện tại và tiếp tục quan sát.")

    def thoi_diem_demo_theo_lich_su(self, user_ids):
        """Neo thời điểm demo ngay sau sự kiện mới nhất của các user đã chọn.

        Hữu ích với bộ dữ liệu mô phỏng lịch sử: các feature 1/3/7 ngày vẫn có ý nghĩa
        thay vì bị rỗng chỉ vì ngày hiện tại cách xa ngày cuối của dataset.
        """
        ids = [str(x).strip() for x in (user_ids or []) if str(x).strip()]
        if not ids:
            return None
        marks = ",".join("?" for _ in ids)
        with lay_ket_noi_csdl() as c:
            row = c.execute(
                f"SELECT MAX(created_at) AS last_time FROM pcbm_events WHERE user_id IN ({marks})",
                ids,
            ).fetchone()
        if not row or not row["last_time"]:
            return None
        try:
            return pd.Timestamp(row["last_time"]).to_pydatetime() + timedelta(minutes=1)
        except Exception:
            return None

    def thu_nghiem_kich_ban_tu_su_kien(self, events, user_id, title, base_prompt_level=1,
                                        estimated_minutes=30, priority=1, channel="buddy",
                                        decision_time=None):
        """Chạy PCBM bằng một lịch sử sự kiện được cung cấp từ bên ngoài.

        Dùng cho Demo Coaching Mode: dữ liệu demo nằm riêng, chạy hoàn toàn trong RAM,
        không đọc/ghi pcbm_events hoặc pcbm_predictions của người dùng thật.
        """
        if not user_id:
            raise ValueError("Thiếu user_id")
        title = (title or "Nhiệm vụ thử nghiệm").strip()
        base_prompt_level = max(0, min(int(base_prompt_level), 2))
        try:
            estimated_minutes = int(estimated_minutes or 30)
        except Exception:
            estimated_minutes = 30
        estimated_minutes = max(1, min(estimated_minutes, 480))
        try:
            priority = int(priority or 1)
        except Exception:
            priority = 1
        priority = max(1, min(priority, 3))
        events = list(events or [])
        if decision_time is None:
            if events:
                decision_time = max(e["timestamp"] for e in events) + timedelta(minutes=1)
            else:
                decision_time = datetime.now()
        task_id = f"DEMO::{self._suy_ra_nhiem_vu_loai(title)}"
        occurrence_id = f"DEMO::{decision_time.strftime('%Y%m%d%H%M%S')}"
        synthetic_created = {
            "event_id": "DEMO_TASK_CREATED", "user_id": user_id,
            "task_id": task_id, "occurrence_id": occurrence_id,
            "timestamp": decision_time - timedelta(seconds=2),
            "event_type": "TASK_CREATED",
            "data": {"title": title, "task_type": self._suy_ra_nhiem_vu_loai(title),
                     "priority": priority, "estimated_minutes": estimated_minutes},
        }
        work_events = events + [synthetic_created]
        decision = {
            "event_id": "DEMO_DECISION", "user_id": user_id,
            "task_id": task_id, "occurrence_id": occurrence_id,
            "timestamp": decision_time, "event_type": "REMINDER_SENT",
            "data": {"prompt_level": base_prompt_level,
                     "reminder_type": "generic" if base_prompt_level <= 1 else "explicit",
                     "channel": channel or "buddy"},
        }
        recall_decision = dict(decision)
        recall_decision["data"] = dict(decision["data"])
        recall_decision["data"]["prompt_level"] = 1
        recall_decision["data"]["reminder_type"] = "generic"
        recall_features = xay_dung_dac_trung(work_events, recall_decision)
        completion_features = xay_dung_dac_trung(work_events, decision)
        recall_p = self._du_doan_xac_suat(self._mo_hinh_tu_nho, recall_features)
        completion_p = self._du_doan_xac_suat(self._mo_hinh_hoan_thanh, completion_features)
        recommended = base_prompt_level
        reason = "KEEP_BASE_LEVEL_ADVISORY_ONLY"
        if recall_p is not None:
            if recall_p >= 0.80 and recommended > 0:
                recommended -= 1
                reason = "HIGH_RECALL_PROBABILITY_SUGGEST_FADE_ONE_LEVEL"
            elif recall_p < 0.45 and recommended < 2:
                recommended += 1
                reason = "LOW_RECALL_PROBABILITY_SUGGEST_MORE_SUPPORT"
        profile = {
            "event_count": recall_features.get("event_count_before"),
            "history_days": round(float(recall_features.get("history_days") or 0), 1),
            "cold_start": bool(recall_features.get("is_cold_start")),
            "recall_rate_7d": self._pct(recall_features.get("recall_rate_7d")),
            "completion_rate_7d": self._pct(recall_features.get("completion_rate_7d")),
            "snooze_rate_7d": self._pct(recall_features.get("snooze_rate_7d")),
            "forget_rate_7d": self._pct(recall_features.get("forget_rate_7d")),
            "avg_start_delay_7d": None if recall_features.get("avg_start_delay_7d") is None else round(float(recall_features["avg_start_delay_7d"]), 1),
            "recall_success_streak": recall_features.get("recall_success_streak", 0),
            "recall_failure_streak": recall_features.get("recall_failure_streak", 0),
        }
        return {
            "user_id": user_id, "profile": profile,
            "scenario": {"title": title, "base_prompt_level": base_prompt_level,
                         "decision_time": decision_time.isoformat(timespec="seconds")},
            "prediction": {
                "recall_probability": recall_p,
                "completion_30m_probability": completion_p,
                "recall_percent": self._pct(recall_p),
                "completion_30m_percent": self._pct(completion_p),
                "base_prompt_level": base_prompt_level,
                "recommended_prompt_level": recommended,
                "reason_code": reason,
                "reason_vi": self._ly_do_tieng_viet(reason),
                "applied": False,
            },
            "features": {"recall": recall_features, "completion": completion_features},
        }

    def thu_nghiem_kich_ban(self, user_id, title, base_prompt_level=1,
                            estimated_minutes=30, priority=1, channel="buddy",
                            decision_time=None):
        """Chạy thử PCBM cho một user mà KHÔNG ghi event/prediction vào DB.

        Mục đích: Admin Playground / demo trước giám khảo. Toàn bộ feature vẫn dùng
        xay_dung_dac_trung() và model thật, nhưng task/decision chỉ tồn tại trong RAM.
        """
        if not user_id:
            raise ValueError("Thiếu user_id")
        title = (title or "Nhiệm vụ thử nghiệm").strip()
        base_prompt_level = max(0, min(int(base_prompt_level), 2))
        try:
            estimated_minutes = int(estimated_minutes or 30)
        except Exception:
            estimated_minutes = 30
        estimated_minutes = max(1, min(estimated_minutes, 480))
        try:
            priority = int(priority or 1)
        except Exception:
            priority = 1
        priority = max(1, min(priority, 3))
        events = self._db_su_kien(user_id)
        # Dữ liệu import có thể chứa timestamp kèm timezone. Playground phải dùng
        # cùng kiểu datetime để tránh so sánh aware/naive trong feature builder.
        if decision_time is None:
            tz = next((e["timestamp"].tzinfo for e in events if getattr(e["timestamp"], "tzinfo", None) is not None), None)
            decision_time = datetime.now(tz=tz) if tz is not None else datetime.now()
        elif events:
            sample_tz = next((e["timestamp"].tzinfo for e in events if getattr(e["timestamp"], "tzinfo", None) is not None), None)
            if sample_tz is not None and decision_time.tzinfo is None:
                decision_time = decision_time.replace(tzinfo=sample_tz)
            elif sample_tz is None and decision_time.tzinfo is not None:
                decision_time = decision_time.replace(tzinfo=None)

        task_id = f"PLAYGROUND::{self._suy_ra_nhiem_vu_loai(title)}"
        occurrence_id = f"PLAY::{decision_time.strftime('%Y%m%d%H%M%S')}"

        synthetic_created = {
            "event_id": "PLAY_TASK_CREATED",
            "user_id": user_id,
            "task_id": task_id,
            "occurrence_id": occurrence_id,
            "timestamp": decision_time - timedelta(seconds=2),
            "event_type": "TASK_CREATED",
            "data": {
                "title": title,
                "task_type": self._suy_ra_nhiem_vu_loai(title),
                "priority": priority,
                "estimated_minutes": estimated_minutes,
            },
        }
        events = list(events) + [synthetic_created]

        decision = {
            "event_id": "PLAY_DECISION",
            "user_id": user_id,
            "task_id": task_id,
            "occurrence_id": occurrence_id,
            "timestamp": decision_time,
            "event_type": "REMINDER_SENT",
            "data": {
                "prompt_level": base_prompt_level,
                "reminder_type": "generic" if base_prompt_level <= 1 else "explicit",
                "channel": channel or "buddy",
            },
        }
        recall_decision = dict(decision)
        recall_decision["data"] = dict(decision["data"])
        recall_decision["data"]["prompt_level"] = 1
        recall_decision["data"]["reminder_type"] = "generic"

        recall_features = xay_dung_dac_trung(events, recall_decision)
        completion_features = xay_dung_dac_trung(events, decision)
        recall_p = self._du_doan_xac_suat(self._mo_hinh_tu_nho, recall_features)
        completion_p = self._du_doan_xac_suat(self._mo_hinh_hoan_thanh, completion_features)

        recommended = base_prompt_level
        reason = "KEEP_BASE_LEVEL_ADVISORY_ONLY"
        if recall_p is not None:
            if recall_p >= 0.80 and recommended > 0:
                recommended -= 1
                reason = "HIGH_RECALL_PROBABILITY_SUGGEST_FADE_ONE_LEVEL"
            elif recall_p < 0.45 and recommended < 2:
                recommended += 1
                reason = "LOW_RECALL_PROBABILITY_SUGGEST_MORE_SUPPORT"

        profile = {
            "event_count": recall_features.get("event_count_before"),
            "history_days": round(float(recall_features.get("history_days") or 0), 1),
            "cold_start": bool(recall_features.get("is_cold_start")),
            "recall_rate_1d": self._pct(recall_features.get("recall_rate_1d")),
            "recall_rate_3d": self._pct(recall_features.get("recall_rate_3d")),
            "recall_rate_7d": self._pct(recall_features.get("recall_rate_7d")),
            "completion_rate_7d": self._pct(recall_features.get("completion_rate_7d")),
            "completion_rate_30d": self._pct(recall_features.get("completion_rate_30d")),
            "snooze_rate_7d": self._pct(recall_features.get("snooze_rate_7d")),
            "forget_rate_7d": self._pct(recall_features.get("forget_rate_7d")),
            "avg_start_delay_7d": None if recall_features.get("avg_start_delay_7d") is None else round(float(recall_features["avg_start_delay_7d"]), 1),
            "recall_success_streak": recall_features.get("recall_success_streak", 0),
            "recall_failure_streak": recall_features.get("recall_failure_streak", 0),
            "last_recall_feedback": recall_features.get("last_recall_feedback"),
        }

        return {
            "user_id": user_id,
            "scenario": {
                "title": title,
                "task_type": recall_features.get("task_type"),
                "estimated_minutes": estimated_minutes,
                "priority": priority,
                "channel": channel,
                "base_prompt_level": base_prompt_level,
                "decision_time": decision_time.isoformat(timespec="seconds"),
            },
            "profile": profile,
            "prediction": {
                "recall_probability": recall_p,
                "completion_30m_probability": completion_p,
                "recall_percent": self._pct(recall_p),
                "completion_30m_percent": self._pct(completion_p),
                "base_prompt_level": base_prompt_level,
                "recommended_prompt_level": recommended,
                "reason_code": reason,
                "reason_vi": self._ly_do_tieng_viet(reason),
                "applied": False,
            },
            "features": {
                "recall": recall_features,
                "completion": completion_features,
            },
        }

    def so_sanh_nguoi_dung(self, user_ids, title, base_prompt_level=1,
                           estimated_minutes=30, priority=1, channel="buddy",
                           decision_time=None):
        ids = [str(x).strip() for x in (user_ids or []) if str(x).strip()]
        if len(ids) != 3:
            raise ValueError("Cần chọn đúng 3 user để so sánh.")
        results = []
        for uid in ids:
            # Với dữ liệu mô phỏng lịch sử, neo từng user ngay sau sự kiện mới nhất
            # giúp so sánh đúng "trạng thái gần nhất" của mỗi hồ sơ.
            t = decision_time or self.thoi_diem_demo_theo_lich_su([uid])
            results.append(
                self.thu_nghiem_kich_ban(
                    uid, title, base_prompt_level, estimated_minutes,
                    priority, channel, t
                )
            )
        return results

    def huan_luyen_mau_mo_hinh(self):
        from huan_luyen_pcbm.huan_luyen_mo_hinh import chay_chuong_trinh as _unused  # kiểm tra lại kết quả nhập dữ liệu
        import subprocess, sys
        cmd = [
            sys.executable, "-m", "huan_luyen_pcbm.huan_luyen_mo_hinh",
            "--input", str(PCBM_SAMPLE_DATA),
            "--model-dir", str(Path(PCBM_RECALL_MODEL).parent),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        self.tai_lai_mo_hinh()
        return {"success": True, "stdout": r.stdout.strip(), "status": self.lay_trang_thai_dich_vu()}

    def huan_luyen_tu_sqlite(self):
        from huan_luyen_pcbm.huan_luyen_tu_csdl import huan_luyen_tu_sqlite_dong

        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                "SELECT * FROM pcbm_events ORDER BY user_id, created_at, id"
            ).fetchall()
        if not rows:
            raise RuntimeError("Bảng pcbm_events đang rỗng. Hãy import dữ liệu hoặc sử dụng OneStep để tạo lịch sử trước.")

        meta = huan_luyen_tu_sqlite_dong(rows, Path(PCBM_RECALL_MODEL).parent)
        self.tai_lai_mo_hinh()

        metrics = {
            "recall": meta["recall_model"],
            "completion_30m": meta["completion_model"],
        }
        with lay_ket_noi_csdl() as c:
            cur = c.execute(
                """INSERT INTO pcbm_training_runs(
                    source, event_count, record_count, user_count,
                    recall_rows, completion_rows, metrics_json,
                    recall_model_path, completion_model_path, created_at,
                    training_version, dataset_name
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    meta["source"], meta["events"], meta["records"], meta["users"],
                    meta["recall_model"]["training_rows"],
                    meta["completion_model"]["training_rows"],
                    json.dumps(metrics, ensure_ascii=False),
                    meta["recall_model"]["path"],
                    meta["completion_model"]["path"],
                    meta["trained_at"],
                    meta.get("training_version", "PCBM"),
                    "sample_events_4133.jsonl" if meta.get("events") == 4133 else "sqlite:pcbm_events",
                )
            )
            run_id = cur.lastrowid

        return {
            "success": True,
            "training_run_id": run_id,
            "events_used": meta["events"],
            "training_records": meta["records"],
            "users": meta["users"],
            "recall_model": meta["recall_model"],
            "completion_model": meta["completion_model"],
            "saved_models": {
                "recall": meta["recall_model"]["path"],
                "completion_30m": meta["completion_model"]["path"],
                "meta": str(Path(PCBM_RECALL_MODEL).parent / "pcbm_model_meta.json"),
            },
            "status": self.lay_trang_thai_dich_vu(),
        }
