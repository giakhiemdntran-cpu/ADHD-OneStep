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
from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung


class DichVuPCBM:
    """Tích hợp mô hình hành vi nhận thức cá nhân PCBM với dữ liệu sự kiện và mô hình dự đoán."""

    def __init__(self):
        self.duoc_bat = bool(PCBM_ENABLED)
        self.ap_dung_muc_nhac = bool(PCBM_APPLY_PROMPT_LEVEL)
        self._mo_hinh_tu_nho = None
        self._mo_hinh_hoan_thanh = None
        self.tai_lai_mo_hinh()

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
                  user_id="local_user", timestamp=None):
        if not self.duoc_bat:
            return None
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

    def _db_su_kien(self, user_id="local_user"):
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

    def de_xuat_muc_ho_tro(self, current_task, base_prompt_level=1, user_id="local_user"):
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
