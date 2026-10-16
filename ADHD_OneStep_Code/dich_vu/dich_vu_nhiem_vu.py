import json
from datetime import datetime, timedelta
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl
from cau_hinh import DEFAULT_DELAY_MINUTES

DAY={0:"MON",1:"TUE",2:"WED",3:"THU",4:"FRI",5:"SAT",6:"SUN"}

class DichVuNhiemVu:
    def _nhiem_vu(self,r):
        if r is None: return None
        d=dict(r)
        d["steps"]=json.loads(d.get("steps") or "[]")
        d["repeat_days"]=json.loads(d.get("repeat_days") or "[]")
        d["enabled"]=bool(d.get("enabled",1))
        return d

    def liet_ke_nhiem_vu(self):
        with lay_ket_noi_csdl() as c:
            rows=c.execute("SELECT * FROM tasks WHERE enabled=1 ORDER BY id DESC").fetchall()
        return [self._nhiem_vu(x) for x in rows]

    def lay_nhiem_vu(self,tid):
        with lay_ket_noi_csdl() as c:
            r=c.execute("SELECT * FROM tasks WHERE id=?",(tid,)).fetchone()
        return self._nhiem_vu(r)

    def them_nhiem_vu(self,title,steps=None,schedule_type="once",scheduled_at=None,scheduled_time=None,
                 repeat_days=None,created_by="web",estimated_minutes=None,deadline_at=None,habit_key=None):
        title=(title or "").strip()
        if not title: raise ValueError("Thiếu tên nhiệm vụ")
        steps=[str(x).strip() for x in (steps or []) if str(x).strip()] or [title]
        repeat_days=repeat_days or []
        now=datetime.now()
        if schedule_type=="once":
            if not scheduled_at:
                scheduled_at=(now+timedelta(minutes=DEFAULT_DELAY_MINUTES)).replace(second=0,microsecond=0).isoformat(timespec="minutes")
            scheduled_time=None; repeat_days=[]
        elif schedule_type=="weekly":
            if not scheduled_time:
                scheduled_time=(now+timedelta(minutes=DEFAULT_DELAY_MINUTES)).strftime("%H:%M")
            if not repeat_days: repeat_days=[DAY[now.weekday()]]
            scheduled_at=None
        else:
            raise ValueError("schedule_type không hợp lệ")
        with lay_ket_noi_csdl() as c:
            cur=c.execute("""
              INSERT INTO tasks(title,steps,schedule_type,scheduled_at,scheduled_time,repeat_days,enabled,created_by,created_at,
                                estimated_minutes,deadline_at,habit_key)
              VALUES(?,?,?,?,?,?,1,?,?,?,?,?)
            """,(title,json.dumps(steps,ensure_ascii=False),schedule_type,scheduled_at,scheduled_time,
                   json.dumps(repeat_days),created_by,now.isoformat(timespec="seconds"),estimated_minutes,deadline_at,habit_key))
            tid=cur.lastrowid
        self.dam_bao_lan_thuc_hien()
        return self.lay_nhiem_vu(tid)

    def cap_nhat_nhiem_vu(self,tid,data):
        old=self.lay_nhiem_vu(tid)
        if not old: raise ValueError("Không tìm thấy task")
        title=str(data.get("title",old["title"])).strip()
        steps=data.get("steps",old["steps"])
        typ=data.get("schedule_type",old["schedule_type"])
        sat=data.get("scheduled_at",old.get("scheduled_at")); stm=data.get("scheduled_time",old.get("scheduled_time"))
        days=data.get("repeat_days",old["repeat_days"]); enabled=1 if data.get("enabled",old["enabled"]) else 0
        est=data.get("estimated_minutes",old.get("estimated_minutes")); deadline=data.get("deadline_at",old.get("deadline_at")); habit=data.get("habit_key",old.get("habit_key"))
        if typ=="once": stm=None; days=[]
        else: sat=None
        with lay_ket_noi_csdl() as c:
            c.execute("""UPDATE tasks SET title=?,steps=?,schedule_type=?,scheduled_at=?,scheduled_time=?,repeat_days=?,enabled=?,
                       estimated_minutes=?,deadline_at=?,habit_key=? WHERE id=?""",
                      (title,json.dumps(steps,ensure_ascii=False),typ,sat,stm,json.dumps(days),enabled,est,deadline,habit,tid))
            c.execute("DELETE FROM task_occurrences WHERE task_id=? AND status='pending'",(tid,))
        self.dam_bao_lan_thuc_hien(); return self.lay_nhiem_vu(tid)

    def xoa_nhiem_vu(self,tid):
        with lay_ket_noi_csdl() as c:
            c.execute("DELETE FROM task_occurrences WHERE task_id=?",(tid,)); c.execute("DELETE FROM tasks WHERE id=?",(tid,))

    def huy_nhiem_vu(self,tid):
        task=self.lay_nhiem_vu(tid)
        if not task: return {"success":False,"message":"Không tìm thấy nhiệm vụ."}
        now=datetime.now().isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            c.execute("""INSERT INTO task_history(task_id,title,scheduled_at,completed_at,snooze_count,final_status,
                       estimated_minutes,actual_minutes,start_delay_minutes,habit_key) VALUES(?,?,?,?,0,'cancelled',?,?,?,?)""",
                      (tid,task["title"],task.get("scheduled_at"),now,task.get("estimated_minutes"),None,None,task.get("habit_key")))
            c.execute("DELETE FROM task_occurrences WHERE task_id=? AND status='pending'",(tid,)); c.execute("DELETE FROM tasks WHERE id=?",(tid,))
        return {"success":True,"task_id":tid,"title":task["title"]}

    def huy_hien_tai_nhiem_vu(self):
        cur=self.lay_nhiem_vu_hien_tai()
        if cur.get("done"): return {"success":False,"message":"Hiện không có nhiệm vụ nào để hủy."}
        return self.huy_nhiem_vu(cur["task_id"])

    def _chen(self,c,tid,when):
        c.execute("""INSERT OR IGNORE INTO task_occurrences(task_id,scheduled_at,status,current_step,snooze_count,created_at)
                     VALUES(?,?,'pending',0,0,?)""",(tid,when,datetime.now().isoformat(timespec="seconds")))

    def dam_bao_lan_thuc_hien(self):
        now=datetime.now()
        with lay_ket_noi_csdl() as c:
            for rr in c.execute("SELECT * FROM tasks WHERE enabled=1").fetchall():
                t=self._nhiem_vu(rr)
                if t["schedule_type"]=="once" and t.get("scheduled_at"):
                    self._chen(c,t["id"],t["scheduled_at"])
                elif t["schedule_type"]=="weekly" and t.get("scheduled_time"):
                    hh,mm=map(int,t["scheduled_time"].split(":"))
                    for off in range(8):
                        d=(now+timedelta(days=off)).date()
                        if DAY[d.weekday()] in t["repeat_days"]:
                            self._chen(c,t["id"],datetime(d.year,d.month,d.day,hh,mm).isoformat(timespec="minutes"))

    def _hien_tai_tu_dong(self,r):
        if not r: return {"done":True,"message":"Hiện chưa có nhiệm vụ nào."}
        d=dict(r); steps=json.loads(d.get("steps") or "[]") or [d["title"]]
        idx=max(0,min(int(d["current_step"]),len(steps)-1))
        return {"done":False,"occurrence_id":d["id"],"task_id":d["task_id"],"task_name":d["title"],
                "schedule_type":d["schedule_type"],"scheduled_at":d["scheduled_at"],"current_step":steps[idx],
                "step_index":idx+1,"total_steps":len(steps),"reminded_at":d.get("reminded_at"),
                "started_at":d.get("started_at"),"start_delay_minutes":d.get("start_delay_minutes"),
                "estimated_minutes":d.get("estimated_minutes"),"deadline_at":d.get("deadline_at"),
                "habit_key":d.get("habit_key")}

    def lay_nhiem_vu_hien_tai(self):
        self.dam_bao_lan_thuc_hien(); now=datetime.now().isoformat(timespec="minutes")
        with lay_ket_noi_csdl() as c:
            r=c.execute("""SELECT o.*,t.title,t.steps,t.schedule_type,t.estimated_minutes,t.deadline_at,t.habit_key
                         FROM task_occurrences o JOIN tasks t ON t.id=o.task_id
                         WHERE o.status='pending' AND t.enabled=1
                         ORDER BY CASE WHEN o.scheduled_at<=? THEN 0 ELSE 1 END,o.scheduled_at LIMIT 1""",(now,)).fetchone()
        return self._hien_tai_tu_dong(r)

    def danh_dau_da_nhac(self,occurrence_id):
        with lay_ket_noi_csdl() as c:
            c.execute("UPDATE task_occurrences SET reminded_at=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),occurrence_id))

    def bat_dau_lan_thuc_hien(self,occurrence_id):
        now=datetime.now(); now_s=now.isoformat(timespec="seconds")
        with lay_ket_noi_csdl() as c:
            r=c.execute("SELECT * FROM task_occurrences WHERE id=? AND status='pending'",(occurrence_id,)).fetchone()
            if not r: return {"success":False,"message":"Không tìm thấy nhiệm vụ đang hoạt động."}
            if r["started_at"]: return {"success":True,"started_at":r["started_at"],"start_delay_minutes":r["start_delay_minutes"]}
            due=datetime.fromisoformat(r["scheduled_at"]); delay=max(0.0,(now-due).total_seconds()/60.0)
            c.execute("UPDATE task_occurrences SET started_at=?,start_delay_minutes=? WHERE id=?",(now_s,round(delay,2),occurrence_id))
        return {"success":True,"started_at":now_s,"start_delay_minutes":round(delay,2)}

    def bat_dau_hien_tai_nhiem_vu(self):
        cur=self.lay_nhiem_vu_hien_tai()
        if cur.get("done"): return cur
        return self.bat_dau_lan_thuc_hien(cur["occurrence_id"])

    def hoan_thanh_lan_thuc_hien_buoc(self,occurrence_id):
        with lay_ket_noi_csdl() as c:
            r=c.execute("""SELECT o.*,t.title,t.steps,t.schedule_type,t.estimated_minutes,t.habit_key
                         FROM task_occurrences o JOIN tasks t ON t.id=o.task_id WHERE o.id=? AND o.status='pending'""",(occurrence_id,)).fetchone()
            if not r: return {"done":True,"message":"Nhiệm vụ này không còn hoạt động."}
            steps=json.loads(r["steps"] or "[]") or [r["title"]]; nxt=r["current_step"]+1
            if nxt>=len(steps):
                done_dt=datetime.now(); done=done_dt.isoformat(timespec="seconds")
                actual=None
                if r["started_at"]:
                    actual=round(max(0,(done_dt-datetime.fromisoformat(r["started_at"])).total_seconds()/60.0),2)
                c.execute("""INSERT INTO task_history(task_id,title,scheduled_at,completed_at,snooze_count,final_status,
                           estimated_minutes,actual_minutes,start_delay_minutes,habit_key) VALUES(?,?,?,?,?,'completed',?,?,?,?)""",
                          (r["task_id"],r["title"],r["scheduled_at"],done,r["snooze_count"],r["estimated_minutes"],actual,r["start_delay_minutes"],r["habit_key"]))
                c.execute("UPDATE task_occurrences SET status='completed',completed_at=?,actual_minutes=? WHERE id=?",(done,actual,r["id"]))
                result={"done":True,"message":f"Đã hoàn thành {r['title']}.","title":r["title"],"task_id":r["task_id"],
                        "occurrence_id":r["id"],"actual_minutes":actual,"start_delay_minutes":r["start_delay_minutes"],
                        "snooze_count":r["snooze_count"],"habit_key":r["habit_key"]}
                if r["schedule_type"]=="once":
                    c.execute("DELETE FROM task_occurrences WHERE task_id=?",(r["task_id"],)); c.execute("DELETE FROM tasks WHERE id=?",(r["task_id"],))
                return result
            c.execute("UPDATE task_occurrences SET current_step=? WHERE id=?",(nxt,r["id"]))
        return self.lay_nhiem_vu_hien_tai()

    def hoan_thanh_hien_tai_buoc(self):
        cur=self.lay_nhiem_vu_hien_tai()
        if cur.get("done"): return cur
        return self.hoan_thanh_lan_thuc_hien_buoc(cur["occurrence_id"])

    def hoan_lan_thuc_hien(self,occurrence_id,minutes=5):
        when=(datetime.now()+timedelta(minutes=minutes)).replace(second=0,microsecond=0).isoformat(timespec="minutes")
        with lay_ket_noi_csdl() as c:
            c.execute("""UPDATE task_occurrences SET scheduled_at=?,snooze_count=snooze_count+1,reminded_at=NULL
                         WHERE id=? AND status='pending'""",(when,occurrence_id))
        return {"success":True,"until":when,"minutes":minutes}

    def hoan_nhiem_vu_hien_tai(self,minutes=5):
        cur=self.lay_nhiem_vu_hien_tai()
        if cur.get("done"): return cur
        return self.hoan_lan_thuc_hien(cur["occurrence_id"],minutes)

    def lay_lich_su(self,limit=100):
        with lay_ket_noi_csdl() as c:
            rows=c.execute("SELECT * FROM task_history ORDER BY completed_at DESC LIMIT ?",(limit,)).fetchall()
        return [dict(x) for x in rows]
