
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_MAP={"thứ hai":0,"thu hai":0,"thứ ba":1,"thu ba":1,"thứ tư":2,"thu tu":2,"thứ năm":3,"thu nam":3,"thứ sáu":4,"thu sau":4,"thứ bảy":5,"thu bay":5,"chủ nhật":6,"chu nhat":6}
WEEKDAY_CODE={0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}

def _hien_tai(tz):
    try:return datetime.now(ZoneInfo(tz))
    except:return datetime.now()

def chuan_hoa_lich_loai(v):
    if v is None:return None
    s=str(v).strip().lower()
    if s in {"","null","none"}: return None
    if s in {"fixed","single","one_time","one-time","once"}: return "once"
    if s in {"weekly","week","repeat_weekly"}: return "weekly"
    return None

def _dong_ho(text):
    low=text.lower()
    pats=[
        r"\b(?:vào\s+lúc|vao\s+luc|lúc|luc)?\s*(\d{1,2})\s*[:h]\s*(\d{2})\b",
        r"\b(?:vào\s+lúc|vao\s+luc|lúc|luc)?\s*(\d{1,2})\s*(?:giờ|gio)\s*(\d{1,2})?\b",
    ]
    for p in pats:
        m=re.search(p,low,re.I)
        if m:
            hh=int(m.group(1)); mm=int(m.group(2) or 0)
            if 0<=hh<=23 and 0<=mm<=59:return hh,mm
    return None,None

def _lap_lai_ngay(text):
    low=text.lower(); out=[]
    for name,wd in WEEKDAY_MAP.items():
        if name in low and WEEKDAY_CODE[wd] not in out: out.append(WEEKDAY_CODE[wd])
    return out

def _ngay(text,now):
    low=text.lower()
    if re.search(r"\bngày\s+mai\b|\bmai\b",low): return (now+timedelta(days=1)).date(),True
    if re.search(r"\bhôm\s+nay\b|\bhom\s+nay\b",low): return now.date(),True
    m=re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",low)
    if m:
        d=int(m.group(1)); mo=int(m.group(2)); y=int(m.group(3)) if m.group(3) else now.year
        if y<100:y+=2000
        try:return datetime(y,mo,d).date(),True
        except:pass
    for name,wd in WEEKDAY_MAP.items():
        if name in low:
            delta=(wd-now.weekday())%7
            if delta==0:delta=7
            return (now+timedelta(days=delta)).date(),True
    return None,False

def trich_xuat_tieu_de(text):
    s=str(text or "").strip()
    pats=[
        r"^\s*nhắc\s+(?:mình|tôi)\s+",r"^\s*nhac\s+(?:minh|toi)\s+",
        r"^\s*nhắc\s+",r"^\s*nhac\s+",
        r"^\s*muốn\s+bạn\s+đặt\s+lịch\s+giúp\s+(?:mình|tôi)\s*",
        r"^\s*muon\s+ban\s+dat\s+lich\s+giup\s+(?:minh|toi)\s*",
        r"^\s*bạn\s+đặt\s+lịch\s+giúp\s+(?:mình|tôi)\s*",
        r"^\s*ban\s+dat\s+lich\s+giup\s+(?:minh|toi)\s*",
    ]
    for p in pats:s=re.sub(p,"",s,flags=re.I)
    s=re.sub(r"\b(?:vào\s+lúc|vao\s+luc|lúc|luc)?\s*\d{1,2}\s*[:h]\s*\d{2}\b"," ",s,flags=re.I)
    s=re.sub(r"\b(?:vào\s+lúc|vao\s+luc|lúc|luc)?\s*\d{1,2}\s*(?:giờ|gio)\s*\d{0,2}\b"," ",s,flags=re.I)
    s=re.sub(r"\b\d{1,3}\s*(?:phút|phut)\s+nữa\b"," ",s,flags=re.I)
    s=re.sub(r"\b(?:ngày\s+mai|mai|hôm\s+nay|hom\s+nay)\b"," ",s,flags=re.I)
    for name in sorted(WEEKDAY_MAP,key=len,reverse=True): s=re.sub(r"\b"+re.escape(name)+r"\b"," ",s,flags=re.I)
    s=re.sub(r"\b(?:mình|tôi)\s+sẽ\b"," ",s,flags=re.I)
    s=re.sub(r"\b(?:nhé|nha)\b"," ",s,flags=re.I)
    s=re.sub(r"\s+"," ",s).strip(" ,.-")
    return s[:1].upper()+s[1:] if s else None

def trich_xuat_thong_tin_nhiem_vu(text,tz_name="Asia/Ho_Chi_Minh",base=None):
    now=base or _hien_tai(tz_name); raw=str(text or "")
    out={"title":trich_xuat_tieu_de(raw),"schedule_type":None,"scheduled_at":None,"scheduled_time":None,"repeat_days":[],"estimated_minutes":None,"deadline_at":None,"snooze_minutes":None}
    m=re.search(r"\b(?:mất|mat|khoảng|khoang)\s+(\d{1,3})\s*(?:phút|phut)\b",raw,re.I)
    if m:out["estimated_minutes"]=int(m.group(1))
    m=re.search(r"\b(?:sau|lại\s+sau|lai\s+sau|hoãn|hoan)\s+(\d{1,3})\s*(?:phút|phut)\b",raw,re.I)
    if m:out["snooze_minutes"]=int(m.group(1))
    m=re.search(r"\b(\d{1,3})\s*(?:phút|phut)\s+nữa\b",raw,re.I)
    if m:
        dt=now+timedelta(minutes=int(m.group(1)))
        out.update(schedule_type="once",scheduled_time=dt.strftime("%H:%M"),scheduled_at=dt.replace(second=0,microsecond=0).isoformat(timespec="minutes"))
        return out
    hh,mm=_dong_ho(raw); days=_lap_lai_ngay(raw); out["repeat_days"]=days
    if days or any(x in raw.lower() for x in ["hàng tuần","hang tuan","mỗi tuần","moi tuan"]):
        out["schedule_type"]="weekly"
        if hh is not None:out["scheduled_time"]=f"{hh:02d}:{mm:02d}"
        return out
    if hh is not None:
        d,explicit=_ngay(raw,now)
        if d is None:d=now.date()
        dt=datetime(d.year,d.month,d.day,hh,mm,tzinfo=now.tzinfo)
        if not explicit and dt<=now:dt+=timedelta(days=1)
        out.update(schedule_type="once",scheduled_time=f"{hh:02d}:{mm:02d}",scheduled_at=dt.isoformat(timespec="minutes"))
    return out
