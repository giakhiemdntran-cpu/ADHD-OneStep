from __future__ import annotations

from datetime import datetime
from typing import Optional

from dich_vu.cai_dat_nguoi_dung import tai_cai_dat, luu_cai_dat
from dich_vu.pcbm_review_policy import evaluate as kiem_tra_de_xuat, cooldown_ok


class DieuPhoiPCBM:
    """Điều phối hội thoại PCBM trên Robot Buddy.

    - Lưu Current Level theo từng user.
    - Dùng model thật để lấy Recall/Completion + reason.
    - Không để LLM tự bịa số liệu/giải thích.
    - Chỉ đổi level sau khi người dùng chấp nhận.
    - Theo dõi một phiên demo gần nhất để trả lời "lần này thế nào?".
    """

    def __init__(self, dich_vu_pcbm, dich_vu_nhiem_vu):
        self.pcbm = dich_vu_pcbm
        self.nhiem_vu = dich_vu_nhiem_vu
        self._session = {}

    def _user(self):
        return self.pcbm.lay_nguoi_dung_hien_tai()

    @staticmethod
    def _clamp_level(level):
        try:
            return max(0, min(2, int(level)))
        except Exception:
            return 1

    def lay_muc_ho_tro(self, user_id=None):
        uid = str(user_id or self._user()).strip()
        settings = tai_cai_dat()
        levels = settings.get("pcbm_support_levels") or {}
        if not isinstance(levels, dict):
            levels = {}
        return self._clamp_level(levels.get(uid, 1))

    def dat_muc_ho_tro(self, level, user_id=None):
        uid = str(user_id or self._user()).strip()
        level = self._clamp_level(level)
        settings = tai_cai_dat()
        levels = settings.get("pcbm_support_levels") or {}
        if not isinstance(levels, dict):
            levels = {}
        levels[str(uid)] = level
        settings["pcbm_support_levels"] = levels
        luu_cai_dat(settings)
        return level

    def _decision_time(self, uid):
        # Với user mô phỏng, neo vào lịch sử gần nhất để feature 1/3/7 ngày có ý nghĩa.
        if str(uid).startswith("test_") or str(uid).startswith("U"):
            return self.pcbm.thoi_diem_demo_theo_lich_su([uid])
        return None

    def danh_gia(self, title=None, estimated_minutes=None):
        uid = self._user()
        level = self.lay_muc_ho_tro(uid)
        cur = self.nhiem_vu.lay_nhiem_vu_hien_tai()
        if title is None:
            title = (cur.get("task_name") if not cur.get("done") else None) or "Nhiệm vụ học tập"
        if estimated_minutes is None:
            estimated_minutes = (cur.get("estimated_minutes") if not cur.get("done") else None) or 30
        result = self.pcbm.thu_nghiem_kich_ban(
            uid,
            title,
            base_prompt_level=level,
            estimated_minutes=estimated_minutes,
            priority=1,
            channel="buddy",
            decision_time=self._decision_time(uid),
        )
        self._session.setdefault(uid, {})["last_assessment"] = result
        return result

    @staticmethod
    def _pct(v):
        if v is None:
            return "chưa đủ dữ liệu"
        try:
            return f"{float(v):.1f}%".replace('.', ',')
        except Exception:
            return "chưa đủ dữ liệu"

    def _explanation(self, result):
        p = result.get("prediction") or {}
        profile = result.get("profile") or {}
        recall = self._pct(p.get("recall_percent"))
        r7 = profile.get("recall_rate_7d")
        forget = profile.get("forget_rate_7d")
        snooze = profile.get("snooze_rate_7d")
        succ = int(profile.get("recall_success_streak") or 0)
        fail = int(profile.get("recall_failure_streak") or 0)
        parts = []
        if r7 is not None:
            parts.append(f"tỷ lệ nhớ 7 ngày là {self._pct(r7)}")
        if forget is not None:
            parts.append(f"tỷ lệ quên là {self._pct(forget)}")
        if snooze is not None and float(snooze) >= 20:
            parts.append(f"tỷ lệ hoãn là {self._pct(snooze)}")
        if succ > 0:
            parts.append(f"có {succ} lần nhớ thành công liên tiếp")
        elif fail > 0:
            parts.append(f"có {fail} lần nhớ chưa thành công liên tiếp")
        history = ", ".join(parts[:3])
        if history:
            history = "Lịch sử gần đây cho thấy " + history + ". "
        return f"{history}PCBM dự đoán khả năng nhớ sau gợi ý khoảng {recall}. {p.get('reason_vi') or ''}".strip()

    def thong_tin_muc_ho_tro(self):
        result = self.danh_gia()
        p = result.get("prediction") or {}
        cur = self.lay_muc_ho_tro()
        rec = self._clamp_level(p.get("recommended_prompt_level", cur))
        recall = self._pct(p.get("recall_percent"))
        completion = self._pct(p.get("completion_30m_percent"))
        return {
            "reply": (
                f"Mức hỗ trợ hiện tại của em là Level {cur}. "
                f"PCBM đang đề xuất Level {rec}. "
                f"Khả năng tự nhớ khoảng {recall}, khả năng hoàn thành trong 30 phút khoảng {completion}."
            ),
            "state": "idle",
            "refresh": True,
        }

    def giai_thich(self):
        result = self.danh_gia()
        p = result.get("prediction") or {}
        cur = self.lay_muc_ho_tro()
        rec = self._clamp_level(p.get("recommended_prompt_level", cur))
        return {
            "reply": self._explanation(result) + f" Vì vậy hệ thống đề xuất Level {cur} → Level {rec}.",
            "state": "idle",
            "refresh": True,
        }

    def chap_nhan_de_xuat(self):
        uid = self._user()
        result = self.danh_gia()
        p = result.get("prediction") or {}
        old = self.lay_muc_ho_tro(uid)
        new = self._clamp_level(p.get("recommended_prompt_level", old))
        if new == old:
            return {"reply": f"PCBM đang đề xuất giữ Level {old}, nên Buddy sẽ tiếp tục mức hỗ trợ hiện tại.", "state": "idle", "refresh": True}
        if new < old:
            state = kiem_tra_de_xuat(uid, old, new, self.pcbm._mo_hinh_tu_nho is not None and self.pcbm._mo_hinh_hoan_thanh is not None)
            if not state['eligible']:
                return {'reply': 'Buddy giữ nguyên Level ' + str(old) + '. ' + state['reason'], 'state': 'idle', 'refresh': True}
        self.dat_muc_ho_tro(new, uid)
        cur_task = self.nhiem_vu.lay_nhiem_vu_hien_tai()
        self.pcbm.ghi_su_kien(
            "SUPPORT_ACCEPTED",
            None if cur_task.get("done") else cur_task.get("task_id"),
            None if cur_task.get("done") else cur_task.get("occurrence_id"),
            {"from_level": old, "to_level": new, "reason_code": p.get("reason_code")},
            user_id=uid,
        )
        s = self._session.setdefault(uid, {})
        s["support_before"] = old
        s["support_after"] = new
        s["support_accepted_at"] = datetime.now().isoformat(timespec="seconds")
        if new < old:
            action = "Buddy sẽ nhắc ít hơn và ưu tiên quan sát trước khi hỗ trợ thêm."
        else:
            action = "Buddy sẽ nhắc rõ hơn để em dễ bắt đầu nhiệm vụ."
        return {"reply": f"Được. Buddy đã chuyển mức hỗ trợ từ Level {old} sang Level {new}. {action}", "state": "success", "refresh": True}

    def xem_xet_thay_doi_muc(self, auto=False):
        uid=self._user()
        current=self.lay_muc_ho_tro(uid)
        result=self.danh_gia()
        pred=result.get('prediction') or {}
        proposed=self._clamp_level(pred.get('recommended_prompt_level',current))
        ready=(self.pcbm._mo_hinh_tu_nho is not None and self.pcbm._mo_hinh_hoan_thanh is not None)
        gate=kiem_tra_de_xuat(uid,current,proposed,ready,auto=auto)
        return dict(gate,current=current,proposed=proposed,reason_code=pred.get('reason_code'),
                    recall_percent=pred.get('recall_percent'),completion_percent=pred.get('completion_30m_percent'))

    def luu_quyet_dinh_muc(self,action,review):
        # fresh eligibility on acceptance, never trust old window/model recommendation
        uid=self._user()
        old=self.lay_muc_ho_tro(uid)
        choice=str(action)
        if choice not in ('keep','accept','later'):
            raise ValueError('Hành động không hợp lệ')
        if choice=='accept':
            fresh=self.xem_xet_thay_doi_muc(auto=False)
            if not fresh['eligible'] or int(fresh['proposed'])!=int(review['proposed']) or old!=int(review['current']):
                return {'applied':False,'message':'Không thể đổi mức: bằng chứng hoặc đề xuất đã thay đổi. Vui lòng đánh giá lại.'}
            new=int(fresh['proposed'])
            self.dat_muc_ho_tro(new,uid)
        else:
            new=old
        cur=self.nhiem_vu.lay_nhiem_vu_hien_tai()
        event={'keep':'SUPPORT_REVIEW_KEPT','accept':'SUPPORT_REVIEW_ACCEPTED','later':'SUPPORT_REVIEW_DEFERRED'}[choice]
        self.pcbm.ghi_su_kien(event,None if cur.get('done') else cur.get('task_id'),
                             None if cur.get('done') else cur.get('occurrence_id'),
                             {'action':choice,'from_level':old,'to_level':new,
                              'proposed_level':review.get('proposed'),'reason_code':review.get('reason_code'),
                              'source':'buddy_user_choice','feedback_not_label':True},user_id=uid)
        return {'applied':choice=='accept','message':f'Buddy sẽ {"giữ Level " + str(old) if choice!="accept" else "chuyển sang Level " + str(new)} theo lựa chọn của em.'}

    def ghi_da_hoi(self,review):
        uid=self._user()
        self.pcbm.ghi_su_kien('SUPPORT_REVIEW_OFFERED',None,None,
            {'from_level':review.get('current'),'proposed_level':review.get('proposed'),
             'source':'buddy_review'},user_id=uid)

    def ghi_feedback(self, kind):
        uid = self._user()
        mapping = {
            "just_right": ("Vừa đủ", "Buddy đã ghi nhận mức nhắc này là vừa đủ."),
            "too_much": ("Quá nhiều", "Buddy đã ghi nhận mức hỗ trợ hiện tại hơi nhiều."),
            "too_little": ("Chưa đủ", "Buddy đã ghi nhận rằng em cần hỗ trợ rõ hơn."),
        }
        label, reply = mapping[kind]
        cur = self.nhiem_vu.lay_nhiem_vu_hien_tai()
        self.pcbm.ghi_su_kien(
            "REMINDER_FEEDBACK",
            None if cur.get("done") else cur.get("task_id"),
            None if cur.get("done") else cur.get("occurrence_id"),
            {"feedback": kind, "feedback_label": label, "prompt_level": self.lay_muc_ho_tro(uid)},
            user_id=uid,
        )
        return {"reply": reply + " Phản hồi này sẽ được lưu vào lịch sử để PCBM sử dụng cho những lần sau.", "state": "success", "refresh": True}

    def khi_tao_nhiem_vu(self, task):
        uid = self._user()
        try:
            result = self.danh_gia(task.get("title"), task.get("estimated_minutes") or 30)
        except Exception:
            return
        p = result.get("prediction") or {}
        cur_level = self.lay_muc_ho_tro(uid)
        rec = self._clamp_level(p.get("recommended_prompt_level", cur_level))
        self.pcbm.ghi_su_kien(
            "SUPPORT_RECOMMENDED", task.get("id"), None,
            {"current_level": cur_level, "recommended_level": rec,
             "recall_probability": p.get("recall_probability"),
             "completion_30m_probability": p.get("completion_30m_probability"),
             "reason_code": p.get("reason_code")},
            user_id=uid,
        )
        self._session[uid] = {
            "task_id": task.get("id"), "title": task.get("title"),
            "support_before": cur_level, "recommended_level": rec,
            "prediction": p, "started": False, "completed": False,
        }

    def khi_bat_dau(self, cur, result):
        uid = self._user()
        level = self.lay_muc_ho_tro(uid)
        s = self._session.setdefault(uid, {})
        s.update({"task_id": cur.get("task_id"), "title": cur.get("task_name"), "started": True,
                  "start_delay_minutes": result.get("start_delay_minutes"), "support_used": level})
        # Nếu đang Level 0 và user chủ động báo bắt đầu, đây là tín hiệu spontaneous recall.
        if level == 0:
            self.pcbm.ghi_su_kien(
                "USER_REMEMBERED", cur.get("task_id"), cur.get("occurrence_id"),
                {"source": "buddy_user_started", "prompt_level": 0}, user_id=uid,
            )
            s["recall_outcome"] = "SUCCESS"

    def khi_hoan_thanh(self, result):
        uid = self._user()
        s = self._session.setdefault(uid, {})
        s.update({"task_id": result.get("task_id"), "title": result.get("title"), "completed": True,
                  "actual_minutes": result.get("actual_minutes"), "completion_outcome": "SUCCESS"})

    def tong_ket_phien(self):
        uid = self._user()
        s = self._session.get(uid) or {}
        if not s:
            return {"reply": "Buddy chưa có đủ thông tin của một phiên hỗ trợ gần đây để tổng kết.", "state": "idle"}
        level = self.lay_muc_ho_tro(uid)
        pred = s.get("prediction") or (s.get("last_assessment") or {}).get("prediction") or {}
        recall = self._pct(pred.get("recall_percent"))
        completion = self._pct(pred.get("completion_30m_percent"))
        started = "đã bắt đầu" if s.get("started") else "chưa ghi nhận bắt đầu"
        completed = "đã hoàn thành" if s.get("completed") else "chưa ghi nhận hoàn thành"
        recall_outcome = s.get("recall_outcome")
        extra = ""
        if recall_outcome == "SUCCESS":
            extra = " Em đã chủ động bắt đầu ở Level 0, đây là tín hiệu tích cực về khả năng tự nhớ."
        return {
            "reply": (
                f"Tổng kết phiên của {uid}: nhiệm vụ {s.get('title') or 'gần nhất'}, {started} và {completed}. "
                f"PCBM trước phiên ước lượng khả năng nhớ sau gợi ý khoảng {recall}, hoàn thành trong 30 phút khoảng {completion}. "
                f"Mức hỗ trợ hiện tại là Level {level}.{extra} Buddy sẽ tiếp tục quan sát nhiều lần trước khi thay đổi thêm."
            ),
            "state": "idle",
            "refresh": True,
        }

    def xu_ly_lenh(self, text) -> Optional[dict]:
        low = " ".join((text or "").strip().lower().split())
        if not low:
            return None

        if any(x in low for x in ["mức hỗ trợ hiện tại", "mức nhắc hiện tại", "đang ở level mấy", "level hiện tại"]):
            return self.thong_tin_muc_ho_tro()
        if any(x in low for x in ["tại sao buddy", "vì sao buddy", "tại sao lại đề xuất", "vì sao lại đề xuất", "tại sao chọn mức", "giải thích mức hỗ trợ"]):
            return self.giai_thich()
        if any(x in low for x in ["nhắc ít hơn", "giảm mức hỗ trợ", "đồng ý giảm", "chấp nhận đề xuất", "đồng ý với đề xuất"]):
            return self.chap_nhan_de_xuat()
        if any(x in low for x in ["mức nhắc này vừa đủ", "mức hỗ trợ này vừa đủ", "vừa đủ"]):
            return self.ghi_feedback("just_right")
        if any(x in low for x in ["nhắc nhiều quá", "hỗ trợ nhiều quá", "quá nhiều lời nhắc"]):
            return self.ghi_feedback("too_much")
        if any(x in low for x in ["cần nhắc rõ hơn", "nhắc rõ hơn", "chưa đủ hỗ trợ", "cần hỗ trợ nhiều hơn"]):
            return self.ghi_feedback("too_little")
        if any(x in low for x in ["lần này buddy đánh giá", "lần này đánh giá", "tổng kết phiên", "kết quả phiên", "đánh giá lần này"]):
            return self.tong_ket_phien()
        return None
