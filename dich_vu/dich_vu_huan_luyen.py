import json
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from dich_vu.co_so_du_lieu import lay_ket_noi_csdl
from cau_hinh import (
    PROMPT_LEVEL_DEFAULT,
    MEMORY_SUCCESS_TO_FADE,
    MEMORY_LEVEL1_FAILURE_TO_RAISE,
    MEMORY_LEVEL0_FAILURE_TO_RAISE,
    MEMORY_LEVEL0_CHECK_DELAY_MINUTES,
)


def thoi_quen_khoa_tu_tieu_de(title):
    s = (title or "nhiệm vụ").strip().lower()
    s = re.sub(r"[^0-9a-zA-ZÀ-ỹ\s_-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:80] or "nhiem_vu"


def _thuong(text):
    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _chua_bat_ky(text, phrases):
    s = _thuong(text)
    return any(_thuong(x) in s for x in phrases)


DONE_PHRASES = ["đã làm", "làm rồi", "xong rồi", "xong", "hoàn thành rồi", "làm xong"]
FORGOT_PHRASES = ["không nhớ", "quên", "quên mất", "việc gì", "là việc gì", "không biết"]
REMEMBER_NOT_DONE_PHRASES = ["nhớ nhưng chưa làm", "nhớ mà chưa làm", "nhớ nhưng chưa", "chưa làm"]
REMEMBER_PHRASES = ["nhớ", "có nhớ", "mình nhớ", "tôi nhớ", "ừ nhớ", "nhớ rồi"]
SNOOZE_PHRASES = ["nhắc lại sau", "phút nữa", "để sau", "chút nữa"]
CANCEL_PHRASES = ["hủy task", "hủy nhiệm vụ", "bỏ lịch", "không cần nhắc nữa"]


class DichVuHuanLuyen:
    """Điều phối huấn luyện nhận thức và ghi nhớ với ba mức hỗ trợ 2, 1, 0."""

    def __init__(self, dich_vu_nhiem_vu, dich_vu_ai):
        self.dich_vu_nhiem_vu = dich_vu_nhiem_vu
        self.dich_vu_ai = dich_vu_ai

    def lap_cac_buoc(self, title):
        return self.dich_vu_ai.lap_ke_hoach_nhiem_vu(title)

    def ghi_nhat_ky(self, event_type, task_id=None, occurrence_id=None, habit_key=None, payload=None):
        with lay_ket_noi_csdl() as c:
            c.execute("""
                INSERT INTO coaching_events(task_id,occurrence_id,habit_key,event_type,payload,created_at)
                VALUES(?,?,?,?,?,?)
            """, (
                task_id, occurrence_id, habit_key, event_type,
                json.dumps(payload or {}, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds")
            ))

    def lay_hoac_tao_thoi_quen(self, habit_key, label=None):
        habit_key = habit_key or thoi_quen_khoa_tu_tieu_de(label)
        now = datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            r = c.execute("SELECT * FROM habit_profiles WHERE habit_key=?", (habit_key,)).fetchone()
            if not r:
                c.execute("""
                    INSERT INTO habit_profiles(habit_key,label,prompt_level,updated_at)
                    VALUES(?,?,?,?)
                """, (habit_key, label or habit_key, PROMPT_LEVEL_DEFAULT, now))
                r = c.execute("SELECT * FROM habit_profiles WHERE habit_key=?", (habit_key,)).fetchone()
        d = dict(r)
        # v9 chỉ sử dụng ba mức 2, 1, 0.
        if int(d.get("prompt_level") or 0) > 2:
            with lay_ket_noi_csdl() as c:
                c.execute("UPDATE habit_profiles SET prompt_level=2 WHERE habit_key=?", (habit_key,))
            d["prompt_level"] = 2
        return d

    def lay_muc_nhac(self, current_task):
        key = current_task.get("habit_key") or thoi_quen_khoa_tu_tieu_de(current_task.get("task_name"))
        return int(self.lay_hoac_tao_thoi_quen(key, current_task.get("task_name"))["prompt_level"])

    # ---------- Huấn luyện thời gian kế thừa từ v8 ----------
    def de_xuat_phut(self, habit_key, user_estimate=None):
        h = self.lay_hoac_tao_thoi_quen(habit_key, habit_key)
        hist = h.get("avg_actual_minutes")
        if hist and hist > 0:
            if user_estimate and user_estimate > 0:
                return int(round(max(float(user_estimate), float(hist))))
            return int(round(hist))
        return int(user_estimate or 10)

    def lich_tu_han(self, deadline_at, habit_key, user_estimate=None):
        deadline = datetime.fromisoformat(deadline_at)
        mins = self.de_xuat_phut(habit_key, user_estimate)
        start = deadline - timedelta(minutes=mins)
        return start.replace(second=0, microsecond=0).isoformat(timespec="minutes"), mins

    # ---------- Vòng đời kiểm tra ghi nhớ ----------
    def _cap_nhat_hoac_them_kiem_tra(self, cur, level, status, check_due_at=None, prompt_sent=False):
        now = datetime.now().isoformat(timespec="seconds")
        key = cur.get("habit_key") or thoi_quen_khoa_tu_tieu_de(cur.get("task_name"))
        with lay_ket_noi_csdl() as c:
            c.execute("""
                INSERT INTO memory_checks(
                    occurrence_id,task_id,task_title,habit_key,prompt_level,scheduled_at,
                    check_due_at,status,prompt_sent_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(occurrence_id) DO UPDATE SET
                    prompt_level=excluded.prompt_level,
                    check_due_at=excluded.check_due_at,
                    status=excluded.status,
                    prompt_sent_at=excluded.prompt_sent_at,
                    updated_at=excluded.updated_at
            """, (
                cur.get("occurrence_id"), cur.get("task_id"), cur.get("task_name") or "Nhiệm vụ",
                key, int(level), cur.get("scheduled_at"), check_due_at, status,
                now if prompt_sent else None, now, now
            ))
            row = c.execute("SELECT * FROM memory_checks WHERE occurrence_id=?", (cur.get("occurrence_id"),)).fetchone()
        return dict(row)

    def bat_dau_nhac_khi_den_han(self, cur, level):
        if int(level) == 2:
            check = self._cap_nhat_hoac_them_kiem_tra(cur, 2, "awaiting_level2", datetime.now().isoformat(timespec="seconds"), True)
            self.ghi_nhat_ky("MEMORY_PROMPT_LEVEL2", cur.get("task_id"), cur.get("occurrence_id"), check.get("habit_key"), {})
            return {
                "level": 2,
                "text": f"Đến giờ {cur['task_name']} rồi. Bạn có nhớ việc này không? Hãy trả lời nhớ, không nhớ, hoặc đã làm rồi."
            }
        check = self._cap_nhat_hoac_them_kiem_tra(cur, 1, "awaiting_level1_decision", datetime.now().isoformat(timespec="seconds"), True)
        self.ghi_nhat_ky("MEMORY_PROMPT_LEVEL1", cur.get("task_id"), cur.get("occurrence_id"), check.get("habit_key"), {})
        return {
            "level": 1,
            "text": "Bạn có một việc cần làm. Bạn có nhớ đó là việc gì không?"
        }

    def lap_lich_kiem_tra_muc0(self, cur):
        due = datetime.fromisoformat(cur["scheduled_at"]) + timedelta(minutes=MEMORY_LEVEL0_CHECK_DELAY_MINUTES)
        check = self._cap_nhat_hoac_them_kiem_tra(cur, 0, "scheduled", due.isoformat(timespec="seconds"), False)
        self.ghi_nhat_ky("MEMORY_LEVEL0_SCHEDULED", cur.get("task_id"), cur.get("occurrence_id"), check.get("habit_key"),
                 {"check_due_at": check.get("check_due_at")})
        return check

    def lay_kiem_tra_muc0_den_han(self):
        now = datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            row = c.execute("""
                SELECT * FROM memory_checks
                WHERE status='scheduled' AND prompt_level=0 AND check_due_at<=?
                ORDER BY check_due_at ASC LIMIT 1
            """, (now,)).fetchone()
            if not row:
                return None
            d = dict(row)
            # Bảo đảm lần thực hiện vẫn tồn tại và đang chờ xử lý.
            occ = c.execute("SELECT status FROM task_occurrences WHERE id=?", (d["occurrence_id"],)).fetchone()
            if not occ or occ["status"] != "pending":
                c.execute("UPDATE memory_checks SET status='closed_stale',updated_at=? WHERE id=?", (now, d["id"]))
                return None
            c.execute("""
                UPDATE memory_checks SET status='awaiting_level0',prompt_sent_at=?,updated_at=? WHERE id=?
            """, (now, now, d["id"]))
            d["status"] = "awaiting_level0"
            d["prompt_sent_at"] = now
        self.ghi_nhat_ky("MEMORY_CHECK_LEVEL0", d.get("task_id"), d.get("occurrence_id"), d.get("habit_key"), {})
        return d

    def cho_xu_ly_kiem_tra(self):
        with lay_ket_noi_csdl() as c:
            r = c.execute("""
                SELECT * FROM memory_checks
                WHERE status IN ('awaiting_level2','awaiting_level1_decision','awaiting_level1_recall','awaiting_level0')
                ORDER BY updated_at DESC LIMIT 1
            """).fetchone()
        return dict(r) if r else None

    def _tu_nho_khop(self, response, title):
        a = _thuong(response)
        b = _thuong(title)
        if not a or not b:
            return False
        if b in a or a in b:
            return True
        stop = {"toi", "minh", "phai", "can", "lam", "viec", "la", "di", "nho", "se"}
        ta = {x for x in a.split() if x not in stop}
        tb = {x for x in b.split() if x not in stop}
        overlap = len(ta & tb) / max(1, len(tb))
        ratio = SequenceMatcher(None, a, b).ratio()
        return overlap >= 0.6 or ratio >= 0.58

    def _cap_nhat_kiem_tra(self, check_id, **fields):
        if not fields:
            return
        fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
        keys = list(fields)
        sql = "UPDATE memory_checks SET " + ",".join(f"{k}=?" for k in keys) + " WHERE id=?"
        with lay_ket_noi_csdl() as c:
            c.execute(sql, tuple(fields[k] for k in keys) + (check_id,))

    def _ghi_ghi_nho_ket_qua(self, check, memory_result, execution_result, response_text=None, recall_text=None):
        key = check.get("habit_key") or thoi_quen_khoa_tu_tieu_de(check.get("task_title"))
        h = self.lay_hoac_tao_thoi_quen(key, check.get("task_title"))
        old_level = max(0, min(2, int(h.get("prompt_level") or 0)))
        success = memory_result in {"remembered", "recalled_correctly"}
        success_streak = int(h.get("memory_success_streak") or 0)
        failure_streak = int(h.get("memory_failure_streak") or 0)
        new_level = old_level

        if success:
            success_streak += 1
            failure_streak = 0
            if old_level in (2, 1) and success_streak >= MEMORY_SUCCESS_TO_FADE:
                new_level = old_level - 1
                success_streak = 0
        else:
            success_streak = 0
            failure_streak += 1
            # KHÔNG tăng mức hỗ trợ chỉ sau một lần người dùng quên.
            if old_level == 0 and failure_streak >= MEMORY_LEVEL0_FAILURE_TO_RAISE:
                new_level = 1
                failure_streak = 0
            elif old_level == 1 and failure_streak >= MEMORY_LEVEL1_FAILURE_TO_RAISE:
                new_level = 2
                failure_streak = 0
            # Mức 2 vẫn giữ ở mức 2: người dùng cần bài tập nhắc rõ ràng hơn.

        now = datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            c.execute("""
                UPDATE habit_profiles
                SET prompt_level=?,memory_success_streak=?,memory_failure_streak=?,
                    last_memory_result=?,last_execution_result=?,last_response_at=?,updated_at=?
                WHERE habit_key=?
            """, (
                new_level, success_streak, failure_streak, memory_result,
                execution_result, now, now, key
            ))

        self._cap_nhat_kiem_tra(
            check["id"], status="closed", response_text=response_text,
            recall_text=recall_text, memory_result=memory_result,
        )
        payload = {
            "old_level": old_level, "new_level": new_level,
            "memory_result": memory_result, "execution_result": execution_result,
            "memory_success_streak": success_streak,
            "memory_failure_streak": failure_streak,
        }
        self.ghi_nhat_ky("MEMORY_RESPONSE", check.get("task_id"), check.get("occurrence_id"), key, payload)

        # Các sự kiện nhãn PCBM v9.9: không phản hồi KHÔNG được xem là thất bại.
        try:
            event_type = "RECALL_SUCCESS" if success else "RECALL_FAILURE"
            with lay_ket_noi_csdl() as c:
                c.execute(
                    """INSERT INTO pcbm_events(user_id,task_id,occurrence_id,event_type,data_json,created_at)
                       VALUES('local_user',?,?,?,?,?)""",
                    (
                        str(check.get("task_id") or ""),
                        str(check.get("occurrence_id") or ""),
                        event_type,
                        json.dumps({
                            "memory_result": memory_result,
                            "execution_result": execution_result,
                            "prompt_level": check.get("prompt_level"),
                        }, ensure_ascii=False),
                        now,
                    )
                )
                if memory_result == "forgot":
                    c.execute(
                        """INSERT INTO pcbm_events(user_id,task_id,occurrence_id,event_type,data_json,created_at)
                           VALUES('local_user',?,?, 'USER_FORGOT', ?,?)""",
                        (
                            str(check.get("task_id") or ""),
                            str(check.get("occurrence_id") or ""),
                            json.dumps({"source": "memory_coaching"}, ensure_ascii=False),
                            now,
                        )
                    )
        except Exception as e:
            print("[PCBM MEMORY LOG WARN]", e)

        return payload

    def _hoan_thanh_cho_kiem_tra(self, check):
        result = self.dich_vu_nhiem_vu.hoan_thanh_lan_thuc_hien_buoc(check.get("occurrence_id"))
        if result.get("done"):
            self.khi_da_hoan_thanh(result, allow_autonomous_memory=False)
        return result

    def xu_ly_phan_hoi_giong_noi(self, text):
        """Xử lý phản hồi giọng nói khi hệ thống đang chờ câu trả lời của vòng huấn luyện ghi nhớ."""
        check = self.cho_xu_ly_kiem_tra()
        if not check:
            return None

        raw = (text or "").strip()
        status = check["status"]
        title = check["task_title"]

        # Giữ các lệnh điều khiển cốt lõi v6/v8 ngay cả khi Buddy đang chờ câu trả lời ghi nhớ.
        if _chua_bat_ky(raw, CANCEL_PHRASES):
            self._cap_nhat_kiem_tra(check["id"], status="closed_cancelled", response_text=raw)
            result = self.dich_vu_nhiem_vu.huy_nhiem_vu(check.get("task_id"))
            return {"reply": result.get("message") or f"Đã hủy {title}.", "state": "success", "refresh": True}
        if _chua_bat_ky(raw, SNOOZE_PHRASES):
            m = re.search(r"(\d+)\s*ph", _thuong(raw))
            minutes = max(1, min(int(m.group(1)) if m else 5, 120))
            self._cap_nhat_kiem_tra(check["id"], status="closed_snoozed", response_text=raw)
            cur = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            self.dich_vu_nhiem_vu.hoan_lan_thuc_hien(check.get("occurrence_id"), minutes)
            self.khi_hoan(cur)
            return {"reply": f"Được, mình sẽ kiểm tra lại sau {minutes} phút.", "state": "idle", "refresh": True}

        is_done = _chua_bat_ky(raw, DONE_PHRASES)
        is_forgot = _chua_bat_ky(raw, FORGOT_PHRASES)
        is_remember_not_done = _chua_bat_ky(raw, REMEMBER_NOT_DONE_PHRASES)
        is_remember = _chua_bat_ky(raw, REMEMBER_PHRASES)

        if status == "awaiting_level2":
            if is_done:
                outcome = self._ghi_ghi_nho_ket_qua(check, "remembered", "completed_after_prompt", raw)
                self._hoan_thanh_cho_kiem_tra(check)
                msg = "Tốt, bạn đã nhớ và làm xong việc này."
                if outcome["new_level"] < outcome["old_level"]:
                    msg += " Lần sau mình sẽ nhắc ngắn hơn một chút."
                return {"reply": msg, "state": "success", "refresh": True}
            if is_forgot:
                self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", raw)
                return {"reply": f"Việc này là {title}. Mình sẽ tiếp tục nhắc rõ để bạn luyện dần nhé.", "state": "idle"}
            if is_remember or self._tu_nho_khop(raw, title):
                outcome = self._ghi_ghi_nho_ket_qua(check, "remembered", "not_completed", raw, raw if self._tu_nho_khop(raw, title) else None)
                msg = "Tốt, bạn nhớ rồi. Khi làm xong hãy nói xong rồi nhé."
                if outcome["new_level"] < outcome["old_level"]:
                    msg += " Những lần tới mình sẽ gợi ý ít hơn."
                return {"reply": msg, "state": "success"}
            return {"reply": "Bạn chỉ cần trả lời ngắn: nhớ, không nhớ, hoặc đã làm rồi.", "state": "idle"}

        if status == "awaiting_level1_decision":
            if is_done:
                outcome = self._ghi_ghi_nho_ket_qua(check, "remembered", "completed_after_generic_cue", raw)
                self._hoan_thanh_cho_kiem_tra(check)
                msg = "Tốt, bạn đã tự nhớ được việc đó và làm xong."
                if outcome["new_level"] == 0 and outcome["old_level"] == 1:
                    msg += " Lần sau mình sẽ để bạn tự nhớ trước."
                return {"reply": msg, "state": "success", "refresh": True}
            if is_forgot:
                outcome = self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", raw)
                msg = f"Việc đó là {title}. Không sao, mình sẽ cho bạn thêm thời gian luyện nhớ ở mức này."
                if outcome["new_level"] > outcome["old_level"]:
                    msg += " Những lần tới mình sẽ nhắc rõ hơn một chút."
                return {"reply": msg, "state": "idle"}
            if self._tu_nho_khop(raw, title):
                outcome = self._ghi_ghi_nho_ket_qua(check, "recalled_correctly", "not_completed", raw, raw)
                msg = "Đúng rồi, bạn đã tự nhớ được việc cần làm."
                if outcome["new_level"] == 0 and outcome["old_level"] == 1:
                    msg += " Lần sau mình sẽ không nhắc lúc đến giờ nữa."
                else:
                    msg += " Khi làm xong hãy nói xong rồi nhé."
                return {"reply": msg, "state": "success"}
            if is_remember:
                self._cap_nhat_kiem_tra(check["id"], status="awaiting_level1_recall", response_text=raw)
                return {"reply": "Bạn nói thử xem đó là việc gì.", "state": "idle"}
            return {"reply": "Nếu nhớ, bạn có thể nói luôn tên việc. Nếu không nhớ, chỉ cần nói không nhớ.", "state": "idle"}

        if status == "awaiting_level1_recall":
            if is_forgot:
                outcome = self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", raw)
                msg = f"Việc đó là {title}. Mình sẽ tiếp tục cho bạn luyện ở mức gợi nhớ."
                if outcome["new_level"] > outcome["old_level"]:
                    msg += " Vì bạn quên nhiều lần liên tiếp, lần tới mình sẽ nhắc rõ hơn."
                return {"reply": msg, "state": "idle"}
            if self._tu_nho_khop(raw, title):
                outcome = self._ghi_ghi_nho_ket_qua(check, "recalled_correctly", "not_completed", raw, raw)
                msg = "Đúng rồi, bạn nhớ chính xác."
                if outcome["new_level"] == 0 and outcome["old_level"] == 1:
                    msg += " Lần sau mình sẽ để bạn tự nhớ trước."
                else:
                    msg += " Khi làm xong hãy nói xong rồi nhé."
                return {"reply": msg, "state": "success"}
            attempts = int(check.get("attempts") or 0) + 1
            if attempts < 2:
                self._cap_nhat_kiem_tra(check["id"], attempts=attempts, recall_text=raw)
                return {"reply": "Mình chưa chắc. Bạn thử nói ngắn gọn tên việc một lần nữa nhé.", "state": "idle"}
            outcome = self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", raw, raw)
            msg = f"Việc đó là {title}. Mình sẽ cho bạn tiếp tục luyện nhớ ở mức này."
            if outcome["new_level"] > outcome["old_level"]:
                msg += " Những lần tới mình sẽ nhắc rõ hơn."
            return {"reply": msg, "state": "idle"}

        if status == "awaiting_level0":
            if is_done:
                self._ghi_ghi_nho_ket_qua(check, "remembered", "completed_without_due_prompt", raw)
                self._hoan_thanh_cho_kiem_tra(check)
                return {"reply": "Tốt, bạn đã tự nhớ và làm xong mà không cần mình nhắc tên việc.", "state": "success", "refresh": True}
            if is_forgot:
                outcome = self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", raw)
                msg = f"Việc đó là {title}. Mình đã ghi nhận là lần này bạn chưa nhớ."
                if outcome["new_level"] == 1:
                    msg += " Lần tới mình sẽ gợi nhẹ rằng bạn có một việc cần làm."
                return {"reply": msg, "state": "idle"}
            if is_remember_not_done or is_remember or self._tu_nho_khop(raw, title):
                self._ghi_ghi_nho_ket_qua(check, "remembered", "not_completed", raw, raw if self._tu_nho_khop(raw, title) else None)
                return {"reply": "Tốt, bạn vẫn tự nhớ được. Khi làm xong hãy nói xong rồi nhé.", "state": "success"}
            return {"reply": "Bạn có thể trả lời: đã làm rồi, nhớ nhưng chưa làm, hoặc không nhớ.", "state": "idle"}

        return None

    def xu_ly_phan_hoi_ghi_nho_tu_band(self, occurrence_id, action):
        with lay_ket_noi_csdl() as c:
            r = c.execute("""
                SELECT * FROM memory_checks WHERE occurrence_id=?
                AND status IN ('awaiting_level2','awaiting_level1_decision','awaiting_level1_recall','awaiting_level0')
            """, (occurrence_id,)).fetchone()
        if not r:
            return None
        check = dict(r)
        a = (action or "").upper().strip()
        if a == "DONE":
            outcome = self._ghi_ghi_nho_ket_qua(check, "remembered", "completed_after_prompt", "BAND:DONE")
            result = self._hoan_thanh_cho_kiem_tra(check)
            return {"success": True, "message": result.get("message", "Đã ghi nhận hoàn thành."), "level": outcome["new_level"]}
        if a == "REMEMBER_NOT_DONE":
            # Chủ yếu dùng cho lần kiểm tra trễ mức 0 trên Band:
            # người dùng đã nhớ nhiệm vụ nhưng chưa hoàn thành.
            outcome = self._ghi_ghi_nho_ket_qua(
                check, "remembered", "not_completed", "BAND:REMEMBER_NOT_DONE"
            )
            return {
                "success": True,
                "message": "Đã ghi nhận: bạn nhớ việc nhưng chưa làm.",
                "level": outcome["new_level"]
            }

        if a in {"REMEMBER", "REMEMBERED"}:
            if check["prompt_level"] == 1:
                # Trên Band, thao tác bấm NHỚ chỉ là tự báo cáo của người dùng.
                # Không được giảm từ mức 1 vì người dùng chưa gọi lại được tên nhiệm vụ.
                self._cap_nhat_kiem_tra(
                    check["id"],
                    status="awaiting_level1_recall",
                    response_text="BAND:REMEMBER"
                )
                return {
                    "success": True,
                    "message": "Đã ghi nhận bạn nhớ. Khi gặp Buddy, hãy nói tên việc để kiểm tra recall.",
                    "level": 1
                }
            outcome = self._ghi_ghi_nho_ket_qua(check, "remembered", "not_completed", "BAND:REMEMBER")
            return {"success": True, "message": "Đã ghi nhận bạn nhớ việc.", "level": outcome["new_level"]}
        if a in {"FORGOT", "NOT_REMEMBER", "NO_REMEMBER"}:
            outcome = self._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", "BAND:FORGOT")
            return {"success": True, "message": f"Việc đó là {check['task_title']}.", "level": outcome["new_level"]}
        return None

    def khi_hoan(self, cur):
        if not cur or cur.get("done"):
            return
        key = cur.get("habit_key") or thoi_quen_khoa_tu_tieu_de(cur.get("task_name"))
        h = self.lay_hoac_tao_thoi_quen(key, cur.get("task_name"))
        now = datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            c.execute("""
                UPDATE habit_profiles SET total_snoozes=total_snoozes+1,updated_at=? WHERE habit_key=?
            """, (now, key))
        self.ghi_nhat_ky("SNOOZE", cur.get("task_id"), cur.get("occurrence_id"), key,
                 {"prompt_level": int(h.get("prompt_level") or PROMPT_LEVEL_DEFAULT)})

    def khi_da_hoan_thanh(self, result, allow_autonomous_memory=True):
        """Cập nhật thống kê hoàn thành và thời gian; giảm mức nhắc dựa trên kết quả ghi nhớ rõ ràng."""
        if not result or not result.get("done"):
            return
        key = result.get("habit_key") or thoi_quen_khoa_tu_tieu_de(result.get("title"))
        h = self.lay_hoac_tao_thoi_quen(key, result.get("title"))
        actual = result.get("actual_minutes")
        total = int(h.get("total_completed") or 0) + 1
        old_avg = h.get("avg_actual_minutes")
        if actual is not None:
            avg = float(actual) if old_avg is None else ((float(old_avg) * (total - 1) + float(actual)) / total)
        else:
            avg = old_avg
        now = datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            c.execute("""
                UPDATE habit_profiles SET total_completed=?,avg_actual_minutes=?,last_completed_at=?,updated_at=?
                WHERE habit_key=?
            """, (total, avg, now, now, key))
            check_row = c.execute("SELECT * FROM memory_checks WHERE occurrence_id=?", (result.get("occurrence_id"),)).fetchone()
        if allow_autonomous_memory and check_row:
            check = dict(check_row)
            if int(check.get("prompt_level") or -1) == 0 and check.get("status") == "scheduled":
                self._ghi_ghi_nho_ket_qua(check, "remembered", "completed_before_check", "AUTO:COMPLETED")
        self.ghi_nhat_ky("COMPLETED", result.get("task_id"), result.get("occurrence_id"), key,
                 {"actual_minutes": actual, "start_delay_minutes": result.get("start_delay_minutes")})

    def _ho_so_pcbm_tu_su_kien(self, habit_key=None):
        """
        Tạo hồ sơ thói quen chỉ-đọc từ bảng pcbm_events.

        Bộ dữ liệu PCBM v4.1 large được import vào pcbm_events để huấn luyện mô hình,
        trong khi màn hình "Huấn luyện ghi nhớ" trước đây chỉ đọc habit_profiles.
        Vì vậy dữ liệu huấn luyện lớn có thể đã tồn tại nhưng giao diện vẫn trống.

        Hàm này KHÔNG ghi ngược vào habit_profiles và KHÔNG tác động vòng lặp huấn luyện
        2→1→0 đang chạy thực tế. Mỗi user/task của dữ liệu PCBM được trình bày như một
        hồ sơ tổng hợp với khóa dạng <user_id>:<task_id>.
        """
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                """
                SELECT user_id, task_id, event_type, data_json, created_at
                FROM pcbm_events
                ORDER BY user_id, task_id, created_at, id
                """
            ).fetchall()

        by_key = {}
        for row in rows:
            r = dict(row)
            uid = str(r.get("user_id") or "local_user")
            task_id = str(r.get("task_id") or "")
            key = f"{uid}:{task_id}"
            if habit_key and habit_key not in {key, task_id}:
                continue
            try:
                data = json.loads(r.get("data_json") or "{}")
            except Exception:
                data = {}

            h = by_key.setdefault(key, {
                "habit_key": key,
                "user_id": uid,
                "task_code": task_id,
                "label": task_id or "Nhiệm vụ",
                "prompt_level": None,
                "memory_success_streak": 0,
                "memory_failure_streak": 0,
                "total_completed": 0,
                "total_snoozes": 0,
                "recall_successes": 0,
                "recall_failures": 0,
                "avg_actual_minutes": None,
                "last_memory_result": None,
                "last_execution_result": None,
                "last_response_at": None,
                "last_completed_at": None,
                "updated_at": r.get("created_at"),
                "source": "pcbm_events",
                "_actual_minutes": [],
                "_recall_seq": [],
            })
            h["updated_at"] = r.get("created_at") or h["updated_at"]
            et = str(r.get("event_type") or "").upper()

            if et == "TASK_CREATED":
                if data.get("title"):
                    h["label"] = data.get("title")
            elif et == "REMINDER_SENT":
                if data.get("prompt_level") is not None:
                    try:
                        h["prompt_level"] = int(data.get("prompt_level"))
                    except Exception:
                        pass
            elif et == "RECALL_SUCCESS":
                h["recall_successes"] += 1
                h["last_memory_result"] = "remembered"
                h["last_response_at"] = r.get("created_at")
                h["_recall_seq"].append(True)
            elif et == "RECALL_FAILURE":
                h["recall_failures"] += 1
                h["last_memory_result"] = "forgot"
                h["last_response_at"] = r.get("created_at")
                h["_recall_seq"].append(False)
            elif et == "USER_REMEMBERED":
                h["last_memory_result"] = "remembered_delayed"
                h["last_response_at"] = r.get("created_at")
            elif et == "USER_FORGOT":
                h["last_memory_result"] = "forgot_delayed"
                h["last_response_at"] = r.get("created_at")
            elif et == "SNOOZE":
                h["total_snoozes"] += 1
            elif et == "TASK_COMPLETED":
                h["total_completed"] += 1
                h["last_completed_at"] = r.get("created_at")
                h["last_execution_result"] = "completed"
                try:
                    actual = float(data.get("actual_minutes"))
                    h["_actual_minutes"].append(actual)
                except Exception:
                    pass

        result = []
        for h in by_key.values():
            seq = h.pop("_recall_seq", [])
            actuals = h.pop("_actual_minutes", [])
            if actuals:
                h["avg_actual_minutes"] = round(sum(actuals) / len(actuals), 2)
            if seq:
                last = seq[-1]
                streak = 0
                for v in reversed(seq):
                    if v != last:
                        break
                    streak += 1
                if last:
                    h["memory_success_streak"] = streak
                    h["memory_failure_streak"] = 0
                else:
                    h["memory_success_streak"] = 0
                    h["memory_failure_streak"] = streak
            result.append(h)

        result.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return result

    def lay_tien_do(self, habit_key=None):
        with lay_ket_noi_csdl() as c:
            if habit_key:
                rows = c.execute("SELECT * FROM habit_profiles WHERE habit_key=?", (habit_key,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM habit_profiles ORDER BY updated_at DESC").fetchall()
        native = [dict(x) for x in rows]
        for x in native:
            x.setdefault("source", "habit_profiles")
        # Hiển thị đồng thời dữ liệu thật và dữ liệu PCBM import; không ghi dữ liệu sample
        # vào habit_profiles để tránh can thiệp vào vòng huấn luyện 2→1→0 của người dùng thật.
        return native + self._ho_so_pcbm_tu_su_kien(habit_key)

    def _kiem_tra_pcbm_tu_su_kien(self, limit=100):
        """Dựng các lần kiểm tra ghi nhớ từ generic cue của PCBM v4."""
        with lay_ket_noi_csdl() as c:
            rows = c.execute(
                """
                SELECT id,user_id,task_id,occurrence_id,event_type,data_json,created_at
                FROM pcbm_events
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()

        created = {}
        reminders = {}
        outcomes = {}
        for row in rows:
            r = dict(row)
            occ = str(r.get("occurrence_id") or "")
            if not occ:
                continue
            try:
                data = json.loads(r.get("data_json") or "{}")
            except Exception:
                data = {}
            et = str(r.get("event_type") or "").upper()
            if et == "TASK_CREATED":
                created[occ] = data
            elif et == "REMINDER_SENT" and str(data.get("reminder_type") or "").lower() == "generic":
                reminders[occ] = (r, data)
            elif et in {"RECALL_SUCCESS", "RECALL_FAILURE"}:
                # Chỉ giữ phản hồi recall đầu tiên sau generic cue cho occurrence này.
                outcomes.setdefault(occ, r)

        result = []
        for occ, (rem, rdata) in reminders.items():
            out = outcomes.get(occ)
            task_meta = created.get(occ, {})
            uid = str(rem.get("user_id") or "local_user")
            task_id = str(rem.get("task_id") or "")
            success = bool(out and str(out.get("event_type")).upper() == "RECALL_SUCCESS")
            result.append({
                "id": f"pcbm:{rem.get('id')}",
                "user_id": uid,
                "occurrence_id": occ,
                "task_id": task_id,
                "task_title": task_meta.get("title") or task_id,
                "habit_key": f"{uid}:{task_id}",
                "prompt_level": rdata.get("prompt_level"),
                "scheduled_at": rem.get("created_at"),
                "check_due_at": rem.get("created_at"),
                "status": "closed_sample" if out else "sample_no_recall_label",
                "prompt_sent_at": rem.get("created_at"),
                "memory_result": ("remembered" if success else "forgot") if out else None,
                "response_text": str(out.get("event_type")) if out else None,
                "created_at": rem.get("created_at"),
                "updated_at": out.get("created_at") if out else rem.get("created_at"),
                "source": "pcbm_events",
            })

        result.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return result[:max(1, int(limit))]

    def lay_kiem_tra_ghi_nho(self, limit=100):
        limit = max(1, int(limit))
        with lay_ket_noi_csdl() as c:
            rows = c.execute("SELECT * FROM memory_checks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        native = [dict(x) for x in rows]
        for x in native:
            x.setdefault("source", "memory_checks")
        if len(native) >= limit:
            return native[:limit]
        return native + self._kiem_tra_pcbm_tu_su_kien(limit - len(native))

    def lay_su_kien_huan_luyen(self, limit=100):
        """Kết hợp coaching_events thật với nhật ký PCBM import để màn hình không bị trống."""
        limit = max(1, int(limit))
        with lay_ket_noi_csdl() as c:
            native = [dict(x) for x in c.execute(
                "SELECT * FROM coaching_events ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
            pcbm_rows = c.execute(
                """
                SELECT id,user_id,task_id,occurrence_id,event_type,data_json,created_at
                FROM pcbm_events
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

        merged = []
        for x in native:
            x["source"] = "coaching_events"
            merged.append(x)
        for row in pcbm_rows:
            r = dict(row)
            uid = str(r.get("user_id") or "local_user")
            task_id = str(r.get("task_id") or "")
            merged.append({
                "id": f"pcbm:{r.get('id')}",
                "user_id": uid,
                "task_id": task_id,
                "occurrence_id": r.get("occurrence_id"),
                "habit_key": f"{uid}:{task_id}",
                "event_type": r.get("event_type"),
                "payload": r.get("data_json") or "{}",
                "created_at": r.get("created_at"),
                "source": "pcbm_events",
            })
        merged.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return merged[:limit]
