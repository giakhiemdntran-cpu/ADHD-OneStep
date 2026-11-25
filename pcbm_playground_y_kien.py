"""PCBM Playground – khảo sát quyết định hỗ trợ (demo tách SQLite thật).

Dùng cùng kết quả inference đang thấy trên Playground. Không tạo nhãn Recall/ITI,
không gửi sự kiện thử nghiệm sang storage/onestep.db, không thay đổi Level Buddy.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

DEMO_DB = Path(__file__).resolve().parent / "data" / "pcbm_playground_feedback_demo.db"
ACTIONS = {
    "accept": "✅ Đồng ý theo đề xuất AI",
    "keep": "= Giữ nguyên mức hiện tại",
    "more": "+ Muốn hỗ trợ thêm",
    "less": "− Muốn giảm lời nhắc",
    "later": "? Để quyết định sau",
}

def _db():
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DEMO_DB), timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("""CREATE TABLE IF NOT EXISTS playground_support_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        before_level INTEGER NOT NULL,
        ai_proposed_level INTEGER NOT NULL,
        after_level INTEGER NOT NULL,
        reason_code TEXT,
        evidence_source TEXT NOT NULL DEFAULT 'PLAYGROUND_DEMO',
        note TEXT,
        created_at TEXT NOT NULL
    )""")
    return db

def decide_level(current, proposed, action):
    """Quy tắc lựa chọn dành riêng cho demo; không áp dụng vào Level thật."""
    if action not in ACTIONS:
        raise ValueError("Lựa chọn không hợp lệ")
    a = min(2, max(0, int(current)))
    b = min(2, max(0, int(proposed)))
    if action == "accept":
        return b
    if action == "more":
        return min(2, a + 1)
    if action == "less":
        return max(0, a - 1)
    return a

def save_demo_feedback(user_id, current, proposed, action, *, reason="", note="", request_id=None):
    if not str(user_id).strip():
        raise ValueError("Thiếu user_id")
    after = decide_level(current, proposed, action)
    request_id = request_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _db() as db:
        db.execute("""INSERT INTO playground_support_feedback
            (request_id, user_id, action, before_level, ai_proposed_level,
             after_level, reason_code, note, created_at)
             VALUES (?,?,?,?,?,?,?,?,?)""",
             (request_id, str(user_id), action, int(current), int(proposed),
              after, str(reason), str(note)[:500], now))
    return after

def get_demo_feedback(user_id, limit=25):
    with _db() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""SELECT created_at, action, before_level,
                ai_proposed_level, after_level, reason_code, note
                FROM playground_support_feedback WHERE user_id=?
                ORDER BY id DESC LIMIT ?""", (str(user_id), int(limit))).fetchall()
        return [dict(row) for row in rows]

def reset_demo_feedback(user_id):
    with _db() as db:
        db.execute("DELETE FROM playground_support_feedback WHERE user_id=?",(str(user_id),))

def hien_thi_y_kien_playground(result: dict, *, prefix: str):
    user_id=str(result.get('user_id') or '').strip()
    pred=result.get('prediction') or {}
    if not user_id:
        st.warning('Chưa xác định được user để lấy ý kiến.')
        return
    try:
        current=int(pred.get('base_prompt_level'))
        proposed=int(pred.get('recommended_prompt_level'))
    except (ValueError, TypeError):
        st.warning('Chưa có đề xuất Level hợp lệ.')
        return
    with st.container(border=True):
        st.markdown('#### 💬 PCBM hỏi ý kiến về mức hỗ trợ')
        st.caption('**PLAYGROUND DEMO:** lựa chọn chỉ lưu trong database mô phỏng, '
                   'không thay đổi Level của Buddy hay làm nhãn huấn luyện.')
        if proposed < current:
            action_text=f'thử giảm hỗ trợ từ Level {current} xuống Level {proposed}'
        elif proposed > current:
            action_text=f'thử tăng hỗ trợ từ Level {current} lên Level {proposed}'
        else:
            action_text=f'giữ nguyên Level {current}'
        st.info(f'Buddy: Dựa trên lịch sử hiện có, PCBM đề xuất **{action_text}**. '
                'Em muốn đồng ý, giữ nguyên hay cần một mức hỗ trợ khác? '
                'Em luôn có thể chọn để sau.')
        if proposed < current:
            st.warning('Việc AI đề xuất giảm hỗ trợ không đủ để tự động áp dụng. '
                       'Trong hệ thống thực cần qua Safe Gate và có sự đồng ý.')
        key=f'{prefix}_feedback_{user_id}'.replace(' ', '_')
        with st.form(key=f'{key}_form', clear_on_submit=False):
            action=st.radio('Ý kiến của người dùng', list(ACTIONS),
                            format_func=lambda x:ACTIONS[x],
                            index=1, key=f'{key}_choice')
            note=st.text_input('Ghi chú của người dùng (không bắt buộc)', key=f'{key}_note')
            submitted=st.form_submit_button('💾 Ghi nhận ý kiến (DEMO)', type='primary',
                                            use_container_width=True)
        if submitted:
            try:
                new=save_demo_feedback(user_id,current,proposed,action,
                         reason=str(pred.get('reason_code') or ''), note=note)
                st.success(f'Đã ghi nhận {ACTIONS[action]}. Mức thử nghiệm: '
                           f'Level {current} → Level {new}. Mức thực tế không thay đổi.')
            except Exception as exc:
                st.error(f'Không lưu được ý kiến: {exc}')
        try:
            history=get_demo_feedback(user_id)
        except Exception as exc:
            st.error(f'Không đọc được lịch sử demo: {exc}')
            return
        if history:
            counts={a:sum(x['action']==a for x in history) for a in ACTIONS}
            a,b,c=st.columns(3)
            a.metric('Lượt phản hồi gần đây', len(history))
            b.metric('Giữ nguyên', counts['keep'])
            c.metric('Đồng ý AI', counts['accept'])
            with st.expander('📋 Lịch sử phản hồi trên Playground', expanded=True):
                st.dataframe(pd.DataFrame([
                    {'Thời điểm':r['created_at'], 'Lựa chọn':ACTIONS.get(r['action'],r['action']),
                     'Mức trước':r['before_level'], 'AI đề xuất':r['ai_proposed_level'],
                     'Mức demo sau lựa chọn':r['after_level'],'Ghi chú':r['note']}
                    for r in history]),use_container_width=True, hide_index=True)
                st.download_button('⬇️ Xuất lịch sử phản hồi CSV',
                    pd.DataFrame(history).to_csv(index=False).encode('utf-8-sig'),
                    file_name=f'pcbm_feedback_demo_{user_id}.csv', mime='text/csv',
                    key=f'{key}_export')
                with st.popover('🗑️ Xóa lịch sử demo của user này'):
                    if st.button('Xác nhận xóa dữ liệu demo', key=f'{key}_reset'):
                        reset_demo_feedback(user_id)
                        st.rerun()
        else:
            st.caption('Chưa có phản hồi nào cho hồ sơ này trong Playground.')
        st.caption('Phản hồi demo chỉ kiểm tra chức năng hỏi và ghi nhận. '
                   'Để sử dụng làm feature khi Train thực tế, cần thu thập phản hồi '
                   'từ phiên Buddy thật, theo đúng thời điểm và đồng ý của người dùng.')
