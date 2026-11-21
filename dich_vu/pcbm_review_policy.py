from __future__ import annotations
"""Human-in-the-loop consent policy. No automatic support reduction.
Evidence of consistency is NOT proof of clinical efficacy.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cau_hinh import BASE_DIR
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl

AUDIT_PATH = Path(BASE_DIR) / 'models' / 'pcbm_safety_audit.json'

def _parse(ts):
    try:
        t=datetime.fromisoformat(str(ts).replace('Z','+00:00'))
        return t.replace(tzinfo=timezone(timedelta(hours=7))) if t.tzinfo is None else t
    except (TypeError, ValueError):
        return None

def history_evidence(user_id, now=None):
    now=now or datetime.now(timezone(timedelta(hours=7)))
    with lay_ket_noi_csdl() as con:
        rows=con.execute("SELECT event_type, created_at FROM pcbm_events WHERE user_id=? AND event_type IN ('REMINDER_SENT','RECALL_SUCCESS','RECALL_FAILURE','TASK_COMPLETED','USER_REMEMBERED') ORDER BY created_at DESC LIMIT 2000", (str(user_id),)).fetchall()
    recent=[]
    for row in rows:
        t=_parse(row['created_at'])
        if t and timedelta(0) <= now-t <= timedelta(days=30):
            recent.append((str(row['event_type']),t))
    counts={k:sum(e==k for e,_ in recent) for k in ('REMINDER_SENT','RECALL_SUCCESS','RECALL_FAILURE','TASK_COMPLETED','USER_REMEMBERED')}
    days=len({t.date() for e,t in recent if e=='REMINDER_SENT'})
    # thresholds are a cautious product policy, not a statistical validation
    enough=(counts['REMINDER_SENT']>=12 and days>=3 and counts['RECALL_SUCCESS']+counts['RECALL_FAILURE']>=6)
    return {'counts':counts,'days':days,'enough':enough,
            'reason':('Đủ số phiên tối thiểu để xin ý kiến; chưa đồng nghĩa mô hình được kiểm định độc lập.' if enough else 'Chưa đủ lịch sử: cần ít nhất 12 lần nhắc trên 3 ngày và 6 phản hồi Recall trong 30 ngày.')}

def independent_reduction_gate():
    """Require explicit independent review before suggesting reduced prompts.
    Do NOT interpret a walk-forward/demo AUC as independent verification.
    """
    if not AUDIT_PATH.exists():
        return False, 'Chưa có báo cáo đánh giá độc lập cho việc giảm hỗ trợ.'
    try:
        a=json.loads(AUDIT_PATH.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return False, 'Báo cáo đánh giá chưa đọc được.'
    # Explicit review/certification field must be authored by an independent validation process.
    check=a.get('independent_review') or {}
    if not (isinstance(check,dict) and check.get('approved') is True and
            check.get('sample_size',0)>=100 and check.get('roc_auc',0)>=0.7 and
            check.get('has_real_user_data') is True and check.get('passed_safety_review') is True):
        return False, 'Chưa có phê duyệt kiểm định độc lập và dữ liệu sử dụng thực.'
    return True, 'Đã có bằng chứng kiểm định độc lập theo cấu hình.'

def cooldown_ok(user_id,days=7):
    with lay_ket_noi_csdl() as con:
        r=con.execute("SELECT created_at FROM pcbm_events WHERE user_id=? AND event_type='SUPPORT_REVIEW_OFFERED' ORDER BY id DESC LIMIT 1",(str(user_id),)).fetchone()
    if not r: return True
    dt=_parse(r['created_at'])
    return not dt or datetime.now(timezone(timedelta(hours=7)))-dt>=timedelta(days=days)

def evaluate(user_id,current,recommended,model_ready,auto=False):
    h=history_evidence(user_id)
    if not h['enough']: return dict(eligible=False, evidence=h, reason=h['reason'])
    if not model_ready: return dict(eligible=False,evidence=h,reason='Mô hình Recall/Completion chưa được tải đầy đủ.')
    if int(current)==int(recommended): return dict(eligible=False,evidence=h,reason='AI đang đề xuất giữ nguyên mức hỗ trợ.')
    if int(recommended)<int(current):
        ok,why=independent_reduction_gate()
        if not ok: return dict(eligible=False,evidence=h,reason=why)
    if auto and not cooldown_ok(user_id):
        return dict(eligible=False,evidence=h,reason='Đã hỏi ý kiến trong 7 ngày qua.')
    return dict(eligible=True,evidence=h,reason='Có thể hỏi ý kiến; người dùng luôn được quyền giữ nguyên.',recommended=int(recommended))
