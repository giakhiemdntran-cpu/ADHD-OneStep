"""Resolve delete requests conservatively against persisted task records.
No fuzzy matching when confidence is low; deletion requires explicit task ID confirmation.
"""
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re
import unicodedata

STOP = {"lam","bai","tap","viec","nhac","nho","em","minh","task","nhiem","vu","xoa","huy","vao","luc","khoang","tam","ngay","mai","toi","sang","chieu","hom","giup","oi","buddy","cho","di","cai","co","mot","tren"}

def normalize(s):
    s=unicodedata.normalize('NFD',str(s or '').lower())
    s=''.join(ch for ch in s if unicodedata.category(ch)!='Mn')
    s=s.replace('đ','d')
    return re.sub(r'[^a-z0-9 ]+',' ',s).strip()

def tokens(s):
    return {x for x in normalize(s).split() if x not in STOP and not x.isdigit()}

def parse_requested_time(raw, now=None):
    now=now or datetime.now()
    low=normalize(raw)
    day=None
    if 'ngay mai' in low or 'hom sau' in low:
        day=(now+timedelta(days=1)).date()
    elif 'hom nay' in low:
        day=now.date()
    # H or hh:mm, with contextual morning/evening
    m=re.search(r'(?<!\d)(\d{1,2})\s*(?:h|gio)(?:\s*(\d{1,2}))?',low)
    if not m:
        m=re.search(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)',low)
    hour=minute=None
    if m:
        hour=int(m.group(1)); minute=int(m.group(2) or 0)
        if hour>23 or minute>59: return day,None
        if hour<12 and any(x in low for x in ('toi','chieu')): hour+=12
        if hour==12 and 'sang' in low: hour=0
    return day, (hour*60+minute if hour is not None else None)

def describe(task):
    return f"#{task['id']} – {task['title']} – {(task.get('scheduled_at') or task.get('scheduled_time') or 'chưa rõ lịch').replace('T',' ')}"

def resolve_candidates(raw, tasks, now=None):
    # Exact task records, not invented model completions.
    day, minutes=parse_requested_time(raw,now)
    words=tokens(raw)
    if not words:
        return []   # Never propose deletion without a meaningful task name.
    matches=[]
    for task in tasks:
        if not task.get('enabled',True) or task.get('schedule_type')!='once':
            continue   # Recurring task deletion needs separate clarification of scope.
        stamp=task.get('scheduled_at')
        if not stamp: continue
        try: when=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        except (TypeError,ValueError): continue
        if when.tzinfo is not None:
            from zoneinfo import ZoneInfo
            when=when.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).replace(tzinfo=None)
        if day is not None and when.date()!=day: continue
        if minutes is not None:
            delta=abs((when.hour*60+when.minute)-minutes)
            if delta>45: continue
        else: delta=0
        titlewords=tokens(task['title'])
        if words:
            overlap=len(words & titlewords)/max(1,len(words))
            similarity=SequenceMatcher(None,normalize(raw),normalize(task['title'])).ratio()
            if overlap<0.5 and similarity<0.62: continue
        score=(len(words & titlewords)/max(1,len(words)) if words else 0) - delta/1000
        matches.append((score,task))
    return [task for _,task in sorted(matches,key=lambda it:(-it[0],it[1]['id']))]
