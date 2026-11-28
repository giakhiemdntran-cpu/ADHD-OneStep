from datetime import datetime
import time
from pathlib import Path

from dich_vu.dich_vu_huan_luyen import thoi_quen_khoa_tu_tieu_de
from dich_vu.dieu_phoi_pcbm import DieuPhoiPCBM
from cau_hinh import VISION_SNAPSHOT_SECONDS, VISION_SNAPSHOT_LONG_SECONDS

DEFAULT_SCHOOL_ITEMS = ["backpack", "book", "bottle"]


class BoDinhTuyenYDinh:
    def __init__(self, dich_vu_nhiem_vu, dich_vu_ai, dich_vu_huan_luyen=None, dich_vu_thi_giac=None, dich_vu_pcbm=None):
        self.dich_vu_nhiem_vu = dich_vu_nhiem_vu
        self.dich_vu_ai = dich_vu_ai
        self.dich_vu_huan_luyen = dich_vu_huan_luyen
        self.dich_vu_thi_giac = dich_vu_thi_giac
        self.dich_vu_pcbm = dich_vu_pcbm
        self.dieu_phoi_pcbm = DieuPhoiPCBM(dich_vu_pcbm, dich_vu_nhiem_vu) if dich_vu_pcbm else None
        self._task_confirmation = None  # Not persisted until user explicitly confirms

    def _ngu_canh(self):
        t = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        if t.get("done"):
            return "Không có task hiện tại."
        return (f"Task hiện tại: {t['task_name']}. "
                f"Bước {t['step_index']}/{t['total_steps']}: {t['current_step']}. "
                f"Lịch: {t['scheduled_at']}.")

    def _thi_giac_tim_phan_hoi(self, item):
        if not self.dich_vu_thi_giac:
            return {"reply": "Camera AI chưa được bật.", "state": "error"}

        r = self.dich_vu_thi_giac.tim_vat_dung(item, try_live=True)
        if not r.get("success"):
            return {"reply": r.get("message", "Mình chưa tìm thấy thông tin về đồ vật đó."), "state": "idle"}

        sight = r["sighting"]
        label = r.get("object_label") or item
        zone = self.dich_vu_thi_giac.bo_nho_vat_dung.vung_van_ban(sight.get("position_zone"))
        seen_at = (sight.get("seen_at") or "").replace("T", " ")
        path = sight.get("snapshot_path")

        if r.get("source") == "live":
            pre = f"Mình thấy {label}. Mình sẽ hiển thị hình ảnh vừa chụp nhé."
            after = f"Mình thấy {label} {zone} lúc {seen_at}."
        else:
            pre = f"Mình sẽ hiển thị hình ảnh lần gần nhất mình thấy {label} nhé."
            after = f"Lần cuối mình thấy {label} {zone} lúc {seen_at}."

        if path and Path(path).exists():
            print(f"[VISION SNAPSHOT] id={sight['id']} path={path} link=/vision/snapshot/{sight['id']}")
            return {
                "reply": pre,
                "after_snapshot_reply": after,
                "state": "success",
                "snapshot_path": path,
                "snapshot_seconds": VISION_SNAPSHOT_SECONDS,
                "snapshot_id": sight["id"],
                "snapshot_caption": f"{label} • {zone} • {seen_at}",
            }

        return {"reply": after, "state": "success"}

    def _task_preview(self, cmd):
        title = str(cmd.get("title") or "").strip()
        when = str(cmd.get("scheduled_at") or cmd.get("scheduled_time") or "").replace("T", " ")
        schedule = str(cmd.get("schedule_type") or "once")
        if not when and schedule != "once":
            when = f"lịch {schedule}"
        return (f"Mình nghe được nhiệm vụ: {title}. "
                + (f"Thời gian: {when}. " if when else "Chưa có giờ cụ thể. ")
                + "Bạn xác nhận lưu nhé? Nói 'đồng ý' để lưu, 'sửa' để nói lại toàn bộ yêu cầu, hoặc 'hủy'.")

    def _handle_task_confirmation(self, raw):
        pending = self._task_confirmation
        if not pending:
            return None
        # Pending belongs to one user only; never commit after user change.
        if (time.monotonic() - pending['created'] > 120
                or pending['user_id'] != self.dich_vu_nhiem_vu.active_user_id):
            self._task_confirmation = None
            return {"reply": "Yêu cầu xác nhận đã hết hạn hoặc bạn đã đổi người dùng. Vui lòng nói lại nhiệm vụ.", "state": "idle"}
        answer = raw.strip().lower().strip(' .!?')
        if answer in {'đồng ý', 'đúng', 'đúng rồi', 'xác nhận', 'lưu', 'lưu đi', 'ok', 'okay', 'có', 'vâng'}:
            self._task_confirmation = None
            return pending['cmd']
        if answer in {'hủy', 'huỷ', 'không', 'không lưu', 'bỏ qua', 'thôi', 'cancel'}:
            self._task_confirmation = None
            return {"reply": "Mình đã hủy yêu cầu. Chưa có nhiệm vụ nào được lưu.", "state": "idle"}
        if answer in {'sửa', 'sửa lại', 'không phải', 'sai rồi', 'nhận sai', 'đổi lại'}:
            self._task_confirmation = None
            return {"reply": "Mình chưa lưu gì cả. Bạn hãy nói lại đầy đủ tên nhiệm vụ và thời gian muốn nhắc nhé.", "state": "idle"}
        # A full corrected request is processed anew, never use old pending data.
        if any(p in answer for p in ('nhắc ', 'tạo nhiệm vụ', 'thêm nhiệm vụ', 'ghi việc', 'đặt lịch')):
            self._task_confirmation = None
            return None
        return {"reply": "Mình chưa rõ bạn muốn lưu hay sửa. Hãy nói 'đồng ý', 'sửa', hoặc 'hủy'.", "state": "idle"}

    def xu_ly(self, text):
        raw = (text or "").strip()
        if not raw:
            return {"reply": "Mình chưa nghe rõ. Bạn nói lại nhé.", "state": "error"}

        low = raw.lower()
        confirmation = self._handle_task_confirmation(raw)
        if isinstance(confirmation, dict):
            if 'intent' in confirmation:
                confirmed_cmd = confirmation
            else:
                return confirmation
        else:
            confirmed_cmd = None

        # PCBM Coach commands are handled deterministically before the general LLM.
        # This keeps model numbers/reasons grounded in the actual PCBM pipeline.
        if self.dieu_phoi_pcbm and confirmed_cmd is None:
            pcbm_reply = self.dieu_phoi_pcbm.xu_ly_lenh(raw)
            if pcbm_reply is not None:
                return pcbm_reply

        # Các lệnh thị giác rõ ràng được xử lý nhanh, không phụ thuộc bộ phân tích 1.5B.
        if self.dich_vu_thi_giac and confirmed_cmd is None:
            if any(x in low for x in ["xem lại hình", "xem lại ảnh", "hiện lại hình", "hiện lại ảnh"]):
                sight = self.dich_vu_thi_giac.lay_cuoi_da_trinh_bay_anh_chup()
                if sight and sight.get("snapshot_path") and Path(sight["snapshot_path"]).exists():
                    return {
                        "reply": "Mình sẽ hiển thị lại hình ảnh nhé.",
                        "after_snapshot_reply": "Mình đã hiển thị lại hình gần nhất.",
                        "state": "success",
                        "snapshot_path": sight["snapshot_path"],
                        "snapshot_seconds": VISION_SNAPSHOT_SECONDS,
                        "snapshot_id": sight["id"],
                        "snapshot_caption": self.dich_vu_thi_giac.bo_nho_vat_dung.mo_ta(sight),
                    }
                return {"reply": "Mình chưa có hình nào để hiển thị lại.", "state": "idle"}

            if any(x in low for x in ["xem lâu hơn", "giữ hình lâu hơn", "giữ ảnh lâu hơn"]):
                sight = self.dich_vu_thi_giac.lay_cuoi_da_trinh_bay_anh_chup()
                if sight and sight.get("snapshot_path") and Path(sight["snapshot_path"]).exists():
                    return {
                        "reply": "Được, mình sẽ hiển thị hình lâu hơn nhé.",
                        "after_snapshot_reply": "Mình đã giữ hình lâu hơn để bạn xem.",
                        "state": "success",
                        "snapshot_path": sight["snapshot_path"],
                        "snapshot_seconds": VISION_SNAPSHOT_LONG_SECONDS,
                        "snapshot_id": sight["id"],
                        "snapshot_caption": self.dich_vu_thi_giac.bo_nho_vat_dung.mo_ta(sight),
                    }
                return {"reply": "Mình chưa có hình nào để hiển thị.", "state": "idle"}

            obj = self.dich_vu_thi_giac.trich_xuat_doi_tuong_tu_van_ban(raw)
            if obj and any(x in low for x in ["ở đâu", "o dau", "đâu rồi", "dau roi", "tìm", "tim"]):
                return self._thi_giac_tim_phan_hoi(obj)

        # Hội thoại huấn luyện ghi nhớ v9 được ưu tiên hơn bộ phân tích LLM tổng quát.
        if self.dich_vu_huan_luyen and confirmed_cmd is None:
            memory_reply = self.dich_vu_huan_luyen.xu_ly_phan_hoi_giong_noi(raw)
            if memory_reply is not None:
                return memory_reply

        cmd = confirmed_cmd if confirmed_cmd is not None else self.dich_vu_ai.phan_tich_lenh(raw)
        intent = cmd.get("intent", "chat")
        conf = float(cmd.get("confidence") or 0)
        print("[COMMAND]", cmd)

        # v9.6: cho Qwen2.5:3B phân loại các câu hỏi tự nhiên về danh tính / khả năng.
        # Không mã hóa cứng câu chữ để hệ thống vẫn hiểu được các cách diễn đạt tương đương.
        if intent == "identity" and conf >= 0.55:
            reply, provider = self.dich_vu_ai.hoi_thoai(raw, self._ngu_canh())
            return {"reply": reply, "state": "idle", "provider": provider}

        if intent == "capability" and conf >= 0.55:
            reply, provider = self.dich_vu_ai.hoi_thoai(raw, self._ngu_canh())
            return {"reply": reply, "state": "idle", "provider": provider}

        if intent in ("create_task", "coach_task") and conf >= 0.55:
            title = (cmd.get("title") or "").strip()
            if not title:
                return {"reply": "Bạn muốn mình giúp việc gì?", "state": "idle"}
            if confirmed_cmd is None:
                # A voice-created reminder without a concrete time must not be guessed.
                schedule_type = str(cmd.get("schedule_type") or "once").lower()
                if (('nhắc' in low or 'hẹn' in low)
                        and not (cmd.get('scheduled_at') or cmd.get('scheduled_time'))
                        and schedule_type == 'once'):
                    return {"reply": "Mình đã nghe tên nhiệm vụ nhưng chưa rõ giờ. Bạn hãy nói lại đầy đủ nhiệm vụ và thời gian cụ thể nhé.", "state": "idle"}
                self._task_confirmation = {
                    'cmd': dict(cmd), 'created': time.monotonic(),
                    'user_id': self.dich_vu_nhiem_vu.active_user_id,
                }
                return {"reply": self._task_preview(cmd), "state": "idle"}
            steps = self.dich_vu_huan_luyen.lap_cac_buoc(title) if (intent == "coach_task" and self.dich_vu_huan_luyen) else [title]
            habit = thoi_quen_khoa_tu_tieu_de(title)
            scheduled_at = cmd.get("scheduled_at")
            est = cmd.get("estimated_minutes")
            deadline = cmd.get("deadline_at")
            recommended = None
            if deadline and self.dich_vu_huan_luyen:
                scheduled_at, recommended = self.dich_vu_huan_luyen.lich_tu_han(deadline, habit, est)
            task = self.dich_vu_nhiem_vu.them_nhiem_vu(
                title, steps, cmd.get("schedule_type") or "once", scheduled_at,
                cmd.get("scheduled_time"), cmd.get("repeat_days") or [], "voice",
                est or recommended, deadline, habit
            )
            if self.dich_vu_huan_luyen:
                self.dich_vu_huan_luyen.lay_hoac_tao_thoi_quen(habit, title)
                self.dich_vu_huan_luyen.ghi_nhat_ky("TASK_CREATED", task["id"], None, habit,
                                  {"steps": steps, "deadline_at": deadline, "estimated_minutes": est})
            if self.dich_vu_pcbm:
                self.dich_vu_pcbm.ghi_su_kien(
                    "TASK_CREATED", task["id"], None,
                    {
                        "title": title,
                        "task_type": self.dich_vu_pcbm._suy_ra_nhiem_vu_loai(title),
                        "priority": 1,
                        "estimated_minutes": est or recommended,
                        "deadline_at": deadline,
                        "schedule_type": task.get("schedule_type"),
                    }
                )
            if self.dieu_phoi_pcbm:
                self.dieu_phoi_pcbm.khi_tao_nhiem_vu(task)
            if deadline and recommended:
                reply = f"Mình đã ghi việc {title}. Để kịp giờ, mình đề xuất bắt đầu lúc {scheduled_at.replace('T',' ')}."
            elif len(steps) > 1:
                reply = f"Mình đã chia việc này thành {len(steps)} bước. Bước đầu tiên là {steps[0]}."
            else:
                when = (task.get("scheduled_at") or task.get("scheduled_time") or "").replace("T", " ")
                reply = f"Đã ghi việc {task['title']}. Mình sẽ theo dõi từ {when}."
            if self.dieu_phoi_pcbm:
                try:
                    a = self.dieu_phoi_pcbm.danh_gia(title, est or recommended or 30)
                    pp = a.get("prediction") or {}
                    cur_level = self.dieu_phoi_pcbm.lay_muc_ho_tro()
                    rec_level = int(pp.get("recommended_prompt_level", cur_level))
                    recall_txt = self.dieu_phoi_pcbm._pct(pp.get("recall_percent"))
                    reply += f" PCBM dự đoán khả năng tự nhớ khoảng {recall_txt} và đề xuất Level {cur_level} → Level {rec_level}."
                except Exception as e:
                    print("[PCBM CREATE REPLY WARN]", e)
            return {"reply": reply, "state": "success", "refresh": True}

        if intent == "start_task" and conf >= 0.45:
            r = self.dich_vu_nhiem_vu.bat_dau_hien_tai_nhiem_vu()
            if r.get("done"):
                return {"reply": r.get("message", "Hiện chưa có nhiệm vụ."), "state": "idle"}
            cur = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            if self.dich_vu_huan_luyen:
                self.dich_vu_huan_luyen.ghi_nhat_ky("START", cur.get("task_id"), cur.get("occurrence_id"), cur.get("habit_key"), r)
            if self.dich_vu_pcbm:
                self.dich_vu_pcbm.ghi_su_kien("TASK_STARTED", cur.get("task_id"), cur.get("occurrence_id"), r)
            if self.dieu_phoi_pcbm:
                self.dieu_phoi_pcbm.khi_bat_dau(cur, r)
            return {"reply": f"Bắt đầu nhé. Việc hiện tại là {cur['current_step']}. Buddy đã ghi nhận thời điểm em chủ động bắt đầu.", "state": "success", "refresh": True}

        if intent == "complete_task" and conf >= 0.55:
            result = self.dich_vu_nhiem_vu.hoan_thanh_hien_tai_buoc()
            if result.get("done"):
                if self.dich_vu_huan_luyen:
                    self.dich_vu_huan_luyen.khi_da_hoan_thanh(result)
                if self.dich_vu_pcbm:
                    self.dich_vu_pcbm.ghi_su_kien("TASK_COMPLETED", result.get("task_id"), result.get("occurrence_id"), result)
                if self.dieu_phoi_pcbm:
                    self.dieu_phoi_pcbm.khi_hoan_thanh(result)
                return {"reply": result.get("message", "Đã hoàn thành.") + " Kết quả này đã được ghi vào lịch sử hành vi cho PCBM.", "state": "success", "refresh": True}
            return {"reply": f"Tốt. Tiếp theo là {result['current_step']}.", "state": "success", "refresh": True}

        if intent == "snooze_task" and conf >= 0.55:
            mins = max(1, min(int(cmd.get("snooze_minutes") or 5), 120))
            cur = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            self.dich_vu_nhiem_vu.hoan_nhiem_vu_hien_tai(mins)
            if self.dich_vu_huan_luyen:
                self.dich_vu_huan_luyen.khi_hoan(cur)
            if self.dich_vu_pcbm:
                self.dich_vu_pcbm.ghi_su_kien("SNOOZE", cur.get("task_id"), cur.get("occurrence_id"), {"minutes": mins})
            return {"reply": f"Được, mình sẽ kiểm tra lại sau {mins} phút.", "state": "idle", "refresh": True}

        if intent == "cancel_task" and conf >= 0.55:
            r = self.dich_vu_nhiem_vu.huy_hien_tai_nhiem_vu()
            if not r.get("success"):
                return {"reply": r.get("message", "Hiện không có nhiệm vụ nào để hủy."), "state": "idle"}
            if self.dich_vu_pcbm:
                self.dich_vu_pcbm.ghi_su_kien("TASK_CANCELLED", r.get("task_id"), None, r)
            return {"reply": f"Được, mình đã hủy {r['title']}.", "state": "success", "refresh": True}

        if intent == "query_current_task" and conf >= 0.45:
            t = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            if t.get("done"):
                return {"reply": t["message"], "state": "idle"}
            return {"reply": f"Việc tiếp theo là {t['task_name']}.", "state": "idle"}

        if intent == "coaching_progress" and conf >= 0.4 and self.dich_vu_huan_luyen:
            rows = self.dich_vu_huan_luyen.lay_tien_do()
            if not rows:
                return {"reply": "Mình chưa có đủ lịch sử để đánh giá tiến trình.", "state": "idle"}
            h = rows[0]
            avg = h.get("avg_actual_minutes")
            msg = (f"Routine {h['label']} đã hoàn thành {h['total_completed']} lần. "
                   f"Mức hỗ trợ hiện tại là {h['prompt_level']} trên 2.")
            if avg is not None:
                msg += f" Thời gian trung bình khoảng {float(avg):.1f} phút."
            return {"reply": msg, "state": "idle"}

        if intent == "check_items" and conf >= 0.4:
            if not self.dich_vu_thi_giac:
                return {"reply": "Camera AI chưa được bật.", "state": "error"}
            items = cmd.get("required_items") or DEFAULT_SCHOOL_ITEMS
            r = self.dich_vu_thi_giac.kiem_tra_vat_dung(items)
            if not r.get("success"):
                return {"reply": r.get("message", "Mình chưa kiểm tra được camera."), "state": "error"}
            if not r.get("missing"):
                return {"reply": "Mình nhìn thấy đủ các đồ cần kiểm tra rồi.", "state": "success"}
            missing = r.get("missing_vi") or r.get("missing") or []
            return {"reply": "Mình chưa thấy: " + ", ".join(missing) + ". Bạn kiểm tra lại nhé.", "state": "idle"}

        if intent == "find_object" and conf >= 0.35:
            obj = cmd.get("object_name") or (self.dich_vu_thi_giac.trich_xuat_doi_tuong_tu_van_ban(raw) if self.dich_vu_thi_giac else None)
            if not obj:
                return {"reply": "Bạn muốn mình tìm đồ vật nào?", "state": "idle"}
            return self._thi_giac_tim_phan_hoi(obj)

        if intent in {"show_last_image", "show_image_longer"} and conf >= 0.35 and self.dich_vu_thi_giac:
            sight = self.dich_vu_thi_giac.lay_cuoi_da_trinh_bay_anh_chup()
            if not sight or not sight.get("snapshot_path") or not Path(sight["snapshot_path"]).exists():
                return {"reply": "Mình chưa có hình nào để hiển thị.", "state": "idle"}
            seconds = VISION_SNAPSHOT_LONG_SECONDS if intent == "show_image_longer" else VISION_SNAPSHOT_SECONDS
            return {
                "reply": "Mình sẽ hiển thị hình ảnh nhé.",
                "after_snapshot_reply": "Xong rồi.",
                "state": "success",
                "snapshot_path": sight["snapshot_path"],
                "snapshot_seconds": seconds,
                "snapshot_id": sight["id"],
                "snapshot_caption": self.dich_vu_thi_giac.bo_nho_vat_dung.mo_ta(sight),
            }

        reply, provider = self.dich_vu_ai.hoi_thoai(raw, self._ngu_canh())
        return {"reply": reply, "state": "idle", "provider": provider}
