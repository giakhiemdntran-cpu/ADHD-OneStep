from datetime import datetime
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl


class DichVuVongDeo:
    def __init__(self, dich_vu_nhiem_vu, dich_vu_huan_luyen=None):
        self.dich_vu_nhiem_vu = dich_vu_nhiem_vu
        self.dich_vu_huan_luyen = dich_vu_huan_luyen

    def dam_bao_luoc_do(self):
        with lay_ket_noi_csdl() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS band_notifications(
              id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER,occurrence_id INTEGER,type TEXT NOT NULL,
              message TEXT NOT NULL,dedupe_key TEXT UNIQUE,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,
              action TEXT,action_at TEXT)''')

    def gui(self, type, message, task_id=None, occurrence_id=None, dedupe_key=None):
        self.dam_bao_luoc_do()
        with lay_ket_noi_csdl() as c:
            if dedupe_key:
                old = c.execute("SELECT * FROM band_notifications WHERE dedupe_key=?", (dedupe_key,)).fetchone()
                if old:
                    return dict(old)
            cur = c.execute('''INSERT INTO band_notifications(task_id,occurrence_id,type,message,dedupe_key,status,created_at)
                             VALUES(?,?,?,?,?,'pending',?)''',
                            (task_id, occurrence_id, type, message, dedupe_key, datetime.now().isoformat(timespec="seconds")))
            row = c.execute("SELECT * FROM band_notifications WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def gui_nhac_nhiem_vu_den_vong_deo(self, current_task):
        oid = current_task.get("occurrence_id")
        title = current_task.get("task_name") or "Nhiệm vụ"
        step = current_task.get("current_step") or title
        return self.gui("TASK", f"{title}|{step}", current_task.get("task_id"), oid,
                         f"TASK:{oid}:{current_task.get('scheduled_at')}")

    def gui_nhac_ghi_nho_den_vong_deo(self, current_task, level):
        oid = current_task.get("occurrence_id")
        if int(level) == 2:
            typ = "MEMORY2"
            msg = f"{current_task.get('task_name') or 'Nhiệm vụ'}|NHỚ / KHÔNG NHỚ / XONG"
        else:
            typ = "MEMORY1"
            msg = "Bạn có một việc cần làm|NHỚ / KHÔNG NHỚ"
        return self.gui(typ, msg, current_task.get("task_id"), oid,
                         f"{typ}:{oid}:{current_task.get('scheduled_at')}")

    def gui_kiem_tra_ghi_nho_muc0_den_vong_deo(self, check):
        """Gửi yêu cầu tự kiểm tra trễ đến OneBand khi chạy ở chế độ vòng đeo hoặc cả hai thiết bị."""
        oid = check.get("occurrence_id")
        task_id = check.get("task_id")
        due = check.get("check_due_at") or ""
        return self.gui(
            "MEMORY0",
            "Bạn có một việc lúc nãy|XONG / NHỚ CHƯA LÀM / KHÔNG NHỚ",
            task_id,
            oid,
            f"MEMORY0:{oid}:{due}"
        )

    def lay_tiep_theo(self):
        with lay_ket_noi_csdl() as c:
            r = c.execute("SELECT * FROM band_notifications WHERE status='pending' ORDER BY id ASC LIMIT 1").fetchone()
        if not r:
            return {"has_message": False}
        d = dict(r)
        return {"has_message": True, "id": d["id"], "type": d["type"], "message": d["message"],
                "task_id": d["task_id"], "occurrence_id": d["occurrence_id"]}

    def dong(self, nid, action):
        with lay_ket_noi_csdl() as c:
            c.execute("UPDATE band_notifications SET status='closed',action=?,action_at=? WHERE id=?",
                      (action, datetime.now().isoformat(timespec="seconds"), nid))

    def xu_ly_hanh_dong(self, notification_id, action):
        with lay_ket_noi_csdl() as c:
            r = c.execute("SELECT * FROM band_notifications WHERE id=?", (notification_id,)).fetchone()
        if not r:
            return {"success": False, "message": "Không tìm thấy thông báo."}
        d = dict(r)
        action = (action or "").upper().strip()
        oid = d.get("occurrence_id")

        if action in {"REMEMBER", "REMEMBERED", "REMEMBER_NOT_DONE", "FORGOT", "NOT_REMEMBER", "NO_REMEMBER"} and self.dich_vu_huan_luyen:
            result = self.dich_vu_huan_luyen.xu_ly_phan_hoi_ghi_nho_tu_band(oid, action)
            if result:
                self.dong(notification_id, action)
                return result

        if action == "DONE":
            # Thông báo ghi nhớ: xử lý đúng occurrence_id, không dựa vào hội thoại chờ toàn cục.
            if self.dich_vu_huan_luyen and d.get("type", "").startswith("MEMORY"):
                check_result = self.dich_vu_huan_luyen.xu_ly_phan_hoi_ghi_nho_tu_band(oid, "DONE")
                if check_result:
                    self.dong(notification_id, action)
                    return {"success": True, "action": action, "message": check_result.get("message", "Đã ghi nhận."),
                            "level": check_result.get("level")}
            result = self.dich_vu_nhiem_vu.hoan_thanh_lan_thuc_hien_buoc(oid) if oid else self.dich_vu_nhiem_vu.hoan_thanh_hien_tai_buoc()
            self.dong(notification_id, action)
            if self.dich_vu_huan_luyen and result.get("done"):
                self.dich_vu_huan_luyen.khi_da_hoan_thanh(result)
            return {"success": True, "action": action, "message": result.get("message", "Đã ghi nhận hoàn thành.")}

        if action in ("SNOOZE_5", "SNOOZE"):
            cur = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            result = self.dich_vu_nhiem_vu.hoan_lan_thuc_hien(oid, 5) if oid else self.dich_vu_nhiem_vu.hoan_nhiem_vu_hien_tai(5)
            self.dong(notification_id, "SNOOZE_5")
            if self.dich_vu_huan_luyen:
                self.dich_vu_huan_luyen.khi_hoan(cur)
            return {"success": True, "action": "SNOOZE_5", "message": "Mình sẽ nhắc lại sau 5 phút.", "until": result.get("until")}

        if action == "HELP":
            return {"success": True, "action": "HELP", "message": "Bạn có thể hỏi Buddy: việc gì vậy?"}

        if action == "CANCEL":
            result = self.dich_vu_nhiem_vu.huy_nhiem_vu(d["task_id"]) if d.get("task_id") else self.dich_vu_nhiem_vu.huy_hien_tai_nhiem_vu()
            self.dong(notification_id, action)
            return {"success": result.get("success", False), "action": action,
                    "message": result.get("message") or f"Đã hủy {result.get('title','nhiệm vụ')}."}

        return {"success": False, "message": "Action không hợp lệ."}

    def lay_trang_thai_vong_deo(self):
        cur = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        if cur.get("done"):
            return {"has_task": False, "task": None,
                    "message": "Chưa có task. Bạn vẫn có thể dùng Focus, Nước và Trạng thái."}
        level = self.dich_vu_huan_luyen.lay_muc_nhac(cur) if self.dich_vu_huan_luyen else None
        return {"has_task": True, "prompt_level": level,
                "task": {"task_id": cur.get("task_id"), "title": cur.get("task_name"),
                         "step": cur.get("current_step"), "step_index": cur.get("step_index"),
                         "total_steps": cur.get("total_steps"), "scheduled_at": cur.get("scheduled_at")}}
