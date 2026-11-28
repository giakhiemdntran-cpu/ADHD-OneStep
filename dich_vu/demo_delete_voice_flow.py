"""Stateful demo-only deletion dialogue, no real task DB writes or auto-delete."""
from pathlib import Path
from datetime import datetime
import re
from cau_hinh import BASE_DIR
from dich_vu.demo_task_store import DemoTaskStore, tomorrow_at, normalize

class DemoDeleteVoiceFlow:
    def __init__(self, path=None):
        self.store = DemoTaskStore(path or Path(BASE_DIR)/'demo_coaching'/'task_confirmation_demo.sqlite3')
        self.stage = 'off'
        self.candidate = None

    def start(self):
        self.store.seed_delete_scenario()
        self.stage = 'waiting_command'
        self.candidate = None

    def stop(self):
        self.stage = 'off'
        self.candidate = None

    def reset(self):
        self.start()

    @staticmethod
    def _is_yes(s):
        return s in {'dung','dung roi','phai','phai roi','chinh xac','yes','co phai','dung la no'}

    @staticmethod
    def _is_no(s):
        return s in {'khong','khong phai','khong dung','sai roi','huy','thoi','bo qua'}

    @staticmethod
    def _delete_intent(s):
        return any(w in s.split() for w in ['xoa','huy']) or 'bo lich' in s

    def handle(self, text):
        if self.stage=='off':
            return None
        s=normalize(text)
        if not s:
            return {'reply':'Mình chưa nghe rõ. Bạn thử nói lại yêu cầu xóa nhé.','demo':True,'state':'idle'}
        if self.stage=='waiting_command':
            if not self._delete_intent(s):
                return None  # do not automatically start any deletion conversation
            if not ('toan' in s or 'bai tap' in s):
                return {'reply':'Bạn muốn xóa lịch nào? Hãy nói tên nhiệm vụ và thời gian giúp mình nhé.','demo':True,'state':'idle'}
            if 'hom nay' in s or 'ngay kia' in s:
                return {'reply':'Mình đang có nhiệm vụ Toán vào ngày mai. Bạn muốn tìm lịch ngày nào?','demo':True,'state':'idle'}
            if not ('ngay mai' in s or 'mai' in s):
                return {'reply':'Bạn muốn xóa lịch Toán của ngày nào?','demo':True,'state':'idle'}
            if not any(x in s for x in ['7 gio','7h','19 gio','19h','bay gio']):
                return {'reply':'Bạn nhớ lịch Toán vào khoảng mấy giờ?','demo':True,'state':'idle'}
            matches=self.store.find('Làm bài tập Toán', tomorrow_at(19,0), 60)
            if len(matches)!=1:
                return {'reply':'Mình chưa xác định được duy nhất lịch Toán cần xóa. Mình chưa xóa gì cả.','demo':True,'state':'idle'}
            self.candidate=matches[0]
            self.stage='confirm_identity'
            return {'reply':'Mình tìm thấy nhiệm vụ Làm bài tập Toán lúc 7 giờ tối ngày mai. Có phải bạn muốn xóa nhiệm vụ này không?', 'demo':True,'state':'idle'}
        if self.stage=='confirm_identity':
            if self._is_no(s):
                self.stage='waiting_command';self.candidate=None
                return {'reply':'Được, mình không xóa. Bạn có thể nói lại tên và giờ của lịch cần tìm.', 'demo':True,'state':'idle'}
            if self._is_yes(s):
                self.stage='confirm_deletion'
                return {'reply':'Bạn xác nhận xóa nhiệm vụ Làm bài tập Toán lúc 7 giờ tối ngày mai nhé? Hãy nói xác nhận xóa hoặc hủy.', 'demo':True,'state':'idle'}
            return {'reply':'Bạn hãy nói đúng rồi hoặc không phải để mình xác định chính xác nhiệm vụ.', 'demo':True,'state':'idle'}
        if self.stage=='confirm_deletion':
            if self._is_no(s):
                self.stage='waiting_command';self.candidate=None
                return {'reply':'Đã hủy yêu cầu. Nhiệm vụ vẫn còn trong cơ sở dữ liệu demo.', 'demo':True,'state':'idle'}
            if s in {'xac nhan xoa','dong y xoa','xoa di','toi xac nhan xoa'}:
                r=self.candidate
                ok=bool(r and self.store.delete_exact(r['id'], r['title'],r['scheduled_at']))
                self.candidate=None
                self.stage='waiting_command'
                if ok:
                    return {'reply':'Đã xóa nhiệm vụ Làm bài tập Toán lúc 7 giờ tối ngày mai khỏi dữ liệu demo.', 'demo':True,'state':'idle'}
                return {'reply':'Nhiệm vụ đã thay đổi hoặc không còn. Mình không xóa gì cả.','demo':True,'state':'idle'}
            return {'reply':'Để an toàn, bạn hãy nói xác nhận xóa hoặc hủy. Mình chưa xóa nhiệm vụ.', 'demo':True,'state':'idle'}
