"""OneStep v11 – persistence for review prompts and demo preferences.
Observations are only *consistency signals*, never independent clinical/model validation.
"""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

class ReviewStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS observations (user_id TEXT NOT NULL, day TEXT NOT NULL, current_level INTEGER NOT NULL, proposed_level INTEGER NOT NULL, PRIMARY KEY(user_id, day))")
            con.execute("CREATE TABLE IF NOT EXISTS notifications (user_id TEXT NOT NULL, proposed_level INTEGER NOT NULL, shown_at TEXT NOT NULL, PRIMARY KEY(user_id, proposed_level))")
            con.execute("CREATE TABLE IF NOT EXISTS demo_choices (profile_id TEXT PRIMARY KEY, final_level INTEGER NOT NULL, action TEXT NOT NULL, decided_at TEXT NOT NULL)")
    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=10)
    def observe(self, user_id, current, proposed, day=None):
        day = day or date.today().isoformat()
        with self._connect() as con:
            con.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?)",(str(user_id), str(day), int(current), int(proposed)))
    def consistent_days(self, user_id, current, proposed, minimum=3, today=None):
        """Count consecutive calendar days of matching suggestions, ending today.
        Note: consistency != independently validated model.
        """
        today = today or date.today()
        with self._connect() as con:
            rows = dict(con.execute("SELECT day, proposed_level FROM observations WHERE user_id=? AND current_level=?",(str(user_id),int(current))).fetchall())
        days=0
        for n in range(max(minimum,30)):
            d=(today-timedelta(days=n)).isoformat()
            if rows.get(d)!=int(proposed): break
            days+=1
        return days
    def should_offer(self, user_id, current, proposed, today=None, minimum=3):
        if int(current)==int(proposed): return False
        if self.consistent_days(user_id,current,proposed,minimum,today)<minimum: return False
        today = today or date.today()
        with self._connect() as con:
            r=con.execute("SELECT shown_at FROM notifications WHERE user_id=? AND proposed_level=?",(str(user_id),int(proposed))).fetchone()
        # At most one prompt per suggestion every 7 days; user can open manually whenever they want.
        if r:
            try:
                return datetime.fromisoformat(r[0]).date() <= today-timedelta(days=7)
            except ValueError: return False
        return True
    def mark_offered(self,user_id,proposed):
        with self._connect() as con:
            con.execute("INSERT OR REPLACE INTO notifications VALUES (?,?,?)",(str(user_id),int(proposed),datetime.now().isoformat(timespec='seconds')))
    def save_demo_choice(self,profile_id,level,action):
        with self._connect() as con:
            con.execute("INSERT OR REPLACE INTO demo_choices VALUES (?,?,?,?)",(str(profile_id),int(level),str(action),datetime.now().isoformat(timespec='seconds')))
    def get_demo_choice(self,profile_id,default=1):
        with self._connect() as con:
            row=con.execute("SELECT final_level FROM demo_choices WHERE profile_id=?",(str(profile_id),)).fetchone()
        return int(row[0]) if row else int(default)
    def reset_demo(self,profile_id):
        with self._connect() as con:
            con.execute("DELETE FROM demo_choices WHERE profile_id=?",(str(profile_id),))
