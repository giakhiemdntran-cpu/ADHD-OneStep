"""Kho dữ liệu nhiệm vụ CHỈ CHO DEMO, không truy cập storage/onestep.db."""
import sqlite3
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path


def normalize(value):
    value = unicodedata.normalize('NFD', str(value or '').lower().replace('đ', 'd'))
    value = ''.join(ch for ch in value if unicodedata.category(ch) != 'Mn')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]+', ' ', value)).strip()


def tomorrow_at(hour, minute=0):
    day = datetime.now().astimezone().date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, hour, minute).strftime('%Y-%m-%d %H:%M')


class DemoTaskStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS demo_tasks
                (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                 scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')''')
            db.execute('''CREATE TABLE IF NOT EXISTS demo_audit
                (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                 operation TEXT NOT NULL, detail TEXT NOT NULL)''')
            count = db.execute('SELECT COUNT(*) FROM demo_tasks').fetchone()[0]
            if count == 0:
                self._seed(db)

    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _seed(db):
        db.executemany('INSERT INTO demo_tasks(title,scheduled_at,status) VALUES(?,?,?)', [
            ('Làm bài tập Toán', tomorrow_at(19,30), 'active'),
            ('Ôn tập Toán', tomorrow_at(20,0), 'active'),
            ('Đọc sách', tomorrow_at(21,0), 'active'),
        ])

    def seed_delete_scenario(self):
        """Seed ONLY an actual 19:00 tomorrow task in private DEMO DB."""
        with self._db() as db:
            db.execute('DELETE FROM demo_tasks')
            db.execute('DELETE FROM demo_audit')
            db.execute('INSERT INTO demo_tasks(title,scheduled_at,status) VALUES(?,?,?)',
                       ('Làm bài tập Toán', tomorrow_at(19,0), 'active'))
            self._audit(db,'SEED_DELETE_DEMO','Làm bài tập Toán @ '+tomorrow_at(19,0))

    def reset(self):
        with self._db() as db:
            db.execute('DELETE FROM demo_tasks')
            db.execute('DELETE FROM demo_audit')
            self._seed(db)
            self._audit(db, 'RESET', 'Khôi phục dữ liệu demo')

    @staticmethod
    def _audit(db, operation, detail):
        db.execute('INSERT INTO demo_audit(created_at,operation,detail) VALUES(?,?,?)',
                   (datetime.now().astimezone().isoformat(timespec='seconds'), operation, detail))

    def list_tasks(self):
        with self._db() as db:
            return [dict(x) for x in db.execute('SELECT * FROM demo_tasks WHERE status=? ORDER BY scheduled_at,id', ('active',))]

    def audit(self):
        with self._db() as db:
            return [dict(x) for x in db.execute('SELECT * FROM demo_audit ORDER BY id DESC LIMIT 25')]

    def create(self, title, scheduled_at):
        if not str(title).strip():
            raise ValueError('Thiếu tên nhiệm vụ')
        datetime.strptime(scheduled_at, '%Y-%m-%d %H:%M')
        with self._db() as db:
            cur=db.execute('INSERT INTO demo_tasks(title,scheduled_at,status) VALUES(?,?,?)',
                           (title.strip(), scheduled_at, 'active'))
            self._audit(db, 'CREATE', f'#{cur.lastrowid}: {title} @ {scheduled_at}')
            return cur.lastrowid

    def delete_exact(self, task_id, title, scheduled_at):
        """Khoá một bản ghi cụ thể: chỉ xoá nếu tên và giờ còn đúng như đã xác nhận."""
        with self._db() as db:
            cur=db.execute('''UPDATE demo_tasks SET status='deleted'
                WHERE id=? AND title=? AND scheduled_at=? AND status='active' ''',
                (task_id,title,scheduled_at))
            if cur.rowcount != 1:
                return False
            self._audit(db, 'DELETE', f'#{task_id}: {title} @ {scheduled_at}')
            return True

    def find(self, title_hint, desired_time, tolerance_minutes=60):
        """Đề xuất ứng viên: ưu tiên ngữ nghĩa tên + khoảng thời gian, KHÔNG tự xóa."""
        hint=normalize(title_hint)
        if not hint or len(hint)<3:
            return []
        target = datetime.strptime(desired_time,'%Y-%m-%d %H:%M')
        tokens=set(hint.split()) - {'task','nhiem','vu','luc','khoang','xoa','bo','nhac','em','mai','ngay','toi'}
        results=[]
        for task in self.list_tasks():
            when=datetime.strptime(task['scheduled_at'],'%Y-%m-%d %H:%M')
            diff=abs((when-target).total_seconds())/60
            if when.date()!=target.date() or diff>tolerance_minutes:
                continue
            name=normalize(task['title'])
            name_tokens=set(name.split())
            overlap=len(tokens & name_tokens) / max(1,len(tokens))
            similarity=SequenceMatcher(None,hint,name).ratio()
            score=0.65*overlap+0.35*similarity - 0.10*diff/max(1,tolerance_minutes)
            if overlap>=0.40 or similarity>=0.55:
                results.append(dict(task,score=round(score,4),delta_minutes=round(diff)))
        return sorted(results,key=lambda x:(-x['score'],x['delta_minutes'],x['id']))
