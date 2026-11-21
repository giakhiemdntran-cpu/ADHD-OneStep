"""Live evidence capture in PCBM admin. No labels are fabricated from historical absence."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st


# SQLite may contain naive local timestamps as well as ISO8601 with UTC offset.
# Convert both to naive Vietnam local clock before subtracting from datetime.now().
def _thoi_gian_dia_phuong(raw):
    dt = datetime.fromisoformat(str(raw).strip().replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).replace(tzinfo=None)
    return dt


def _so_giay_da_qua(now, raw):
    return (now - _thoi_gian_dia_phuong(raw)).total_seconds()


def hien_thi_thu_thap_bang_chung(db_path):
    st.markdown('#### 📌 Thu thập bằng chứng cho Completion & ITI')
    st.caption('Chỉ ghi nhận phiên quan sát có thật, không tự biến log thiếu thành nhãn 0. '
               'Đây là xác nhận của người quan sát, không phải đo trí nhớ hay chẩn đoán.')
    def connect():
        con=sqlite3.connect(str(db_path),timeout=30)
        con.row_factory=sqlite3.Row
        return con
    now=datetime.now()
    with connect() as con:
        occurrences=con.execute("""SELECT o.id, o.task_id, o.scheduled_at, t.title
               FROM task_occurrences o JOIN tasks t ON t.id=o.task_id
               WHERE o.status='pending' ORDER BY o.scheduled_at DESC LIMIT 200""").fetchall()
    if not occurrences:
        st.info('Chưa có lần thực hiện đang hoạt động để mở phiên quan sát ITI.')
    else:
        options={f"#{r['id']} · {r['title']} · {r['scheduled_at']}":r for r in occurrences}
        selected=st.selectbox('Nhiệm vụ để mở phiên quan sát mới',list(options),key='pcbm_v5_obs_task')
        uid=st.text_input('User ID thực sự đang được quan sát',value='',key='pcbm_v5_obs_uid')
        if st.button('▶️ Bắt đầu quan sát ITI 30 phút',key='pcbm_v5_open_obs'):
            if not uid.strip(): st.error('Cần nhập user ID chính xác.')
            else:
                r=options[selected]
                with connect() as con:
                    already_started=con.execute('SELECT started_at FROM task_occurrences WHERE id=?',(r['id'],)).fetchone()
                    previous=con.execute("""SELECT 1 FROM pcbm_events
                       WHERE user_id=? AND occurrence_id=? AND event_type='REMINDER_SENT' LIMIT 1""",
                       (uid.strip(),str(r['id']))).fetchone()
                    if previous or (already_started and already_started['started_at']): st.error('Đã có lời nhắc hoặc nhiệm vụ đã bắt đầu; không thể mở ITI trước lời nhắc.')
                    else:
                        con.execute("""INSERT INTO pcbm_events(user_id,task_id,occurrence_id,event_type,data_json,created_at)
                           VALUES (?,?,?,?,?,?)""",(uid.strip(),str(r['task_id']),str(r['id']),'ITI_WINDOW_OPENED',
                           json.dumps({'window_minutes':30,'source':'supervised_admin_session'},ensure_ascii=False),
                           now.isoformat(timespec='seconds')))
                        con.commit()
                        st.success('Đã mở phiên quan sát. Học sinh cần dùng nút Bắt đầu nhiệm vụ của ứng dụng để ghi nhận ITI=1.')
    st.divider()
    with connect() as con:
        opened=con.execute("""SELECT e.id,e.user_id,e.task_id,e.occurrence_id,e.created_at
            FROM pcbm_events e WHERE e.event_type='ITI_WINDOW_OPENED'
            ORDER BY e.id DESC LIMIT 100""").fetchall()
    review=[r for r in opened if 1800 <= _so_giay_da_qua(now, r['created_at']) <= 172800]
    st.markdown('##### Xác minh phiên ITI đã đủ 30 phút')
    if not review: st.info('Chưa có phiên ITI nào đủ 30 phút để xác minh.')
    else:
        byid={str(r['id']):r for r in review}
        chosen=st.selectbox('Phiên ITI',list(byid),format_func=lambda k:f"#{k} · {byid[k]['user_id']} · {byid[k]['occurrence_id']}",key='pcbm_v5_close_iti_id')
        reviewer=st.text_input('Người xác minh',key='pcbm_v5_reviewer_iti')
        evidence=st.text_input('Nguồn bằng chứng (nhật ký quan sát, xác nhận trực tiếp...)',key='pcbm_v5_src_iti')
        full=st.checkbox('Tôi xác nhận đã quan sát đầy đủ cửa sổ 30 phút và KHÔNG có lần bắt đầu chủ động',key='pcbm_v5_full_iti')
        if st.button('✅ Ghi nhận ITI = 0 có xác minh',key='pcbm_v5_save_iti'):
            r=byid[chosen]
            if not (reviewer.strip() and evidence.strip() and full): st.error('Thiếu người xác minh, nguồn hoặc xác nhận.')
            else:
                with connect() as con:
                    previous=con.execute("""SELECT 1 FROM pcbm_events WHERE event_type='ITI_OBSERVATION_VERIFIED'
                         AND user_id=? AND occurrence_id=? AND json_extract(data_json,'$.window_event_id')=? LIMIT 1""",
                         (r['user_id'],r['occurrence_id'],f"DB{r['id']}")).fetchone()
                    starts=con.execute("""SELECT 1 FROM pcbm_events WHERE event_type='TASK_STARTED'
                         AND user_id=? AND occurrence_id=? AND created_at>=? AND created_at<=? LIMIT 1""",
                         (r['user_id'],r['occurrence_id'],r['created_at'],(_thoi_gian_dia_phuong(r['created_at'])+timedelta(minutes=30)).isoformat(timespec='seconds'))).fetchone()
                    cue=con.execute("""SELECT 1 FROM pcbm_events WHERE event_type='REMINDER_SENT'
                         AND user_id=? AND occurrence_id=? AND created_at>=? AND created_at<=? LIMIT 1""",
                         (r['user_id'],r['occurrence_id'],r['created_at'],(_thoi_gian_dia_phuong(r['created_at'])+timedelta(minutes=30)).isoformat(timespec='seconds'))).fetchone()
                    if previous or starts or cue: st.error('Phiên đã xác minh, có TASK_STARTED hoặc đã nhận lời nhắc trong cửa sổ; không được gán âm.')
                    else:
                        info={'window_event_id':f"DB{r['id']}",'continuous_observation':True,
                              'no_unprompted_start':True,'reviewed_by':reviewer.strip(),'evidence_source':evidence.strip()}
                        con.execute("""INSERT INTO pcbm_events(user_id,task_id,occurrence_id,event_type,data_json,created_at)
                              VALUES(?,?,?,?,?,?)""",(r['user_id'],r['task_id'],r['occurrence_id'],
                              'ITI_OBSERVATION_VERIFIED',json.dumps(info,ensure_ascii=False),now.isoformat(timespec='seconds')))
                        con.commit(); st.success('Đã ghi nhận bằng chứng âm ITI, không thay đổi dữ liệu cũ.')
    st.divider()
    st.markdown('##### Xác minh không hoàn thành trong 30 phút sau nhắc')
    with connect() as con:
        reminder=con.execute("""SELECT id,user_id,task_id,occurrence_id,created_at
         FROM pcbm_events WHERE event_type='REMINDER_SENT' ORDER BY id DESC LIMIT 500""").fetchall()
    mature=[r for r in reminder if 1800 <= _so_giay_da_qua(now, r['created_at']) <= 172800]
    if not mature: st.info('Chưa có lời nhắc nào qua 30 phút.')
    else:
        choices={str(r['id']):r for r in mature}
        rid=st.selectbox('Lần nhắc',list(choices),format_func=lambda k:f"#{k} · {choices[k]['user_id']} · {choices[k]['occurrence_id']} · {choices[k]['created_at']}",key='pcbm_v5_complete_reminder')
        who=st.text_input('Người xác minh Completion',key='pcbm_v5_completion_reviewer')
        src=st.text_input('Nguồn bằng chứng Completion',key='pcbm_v5_completion_source')
        cert=st.checkbox('Tôi xác nhận theo dõi đầy đủ 30 phút và nhiệm vụ KHÔNG hoàn thành trong khoảng đó',key='pcbm_v5_completion_cert')
        if st.button('✅ Ghi nhận Completion = 0 có xác minh',key='pcbm_v5_completion_save'):
            r=choices[rid];end=(_thoi_gian_dia_phuong(r['created_at'])+timedelta(minutes=30)).isoformat(timespec='seconds')
            if not (who.strip() and src.strip() and cert): st.error('Thiếu xác nhận hoặc nguồn bằng chứng.')
            else:
                with connect() as con:
                    completed=con.execute("""SELECT 1 FROM pcbm_events WHERE event_type='TASK_COMPLETED'
                         AND user_id=? AND occurrence_id=? AND created_at>? AND created_at<=? LIMIT 1""",
                         (r['user_id'],r['occurrence_id'],r['created_at'],end)).fetchone()
                    existing=con.execute("""SELECT 1 FROM pcbm_events WHERE event_type='OBSERVATION_WINDOW_VERIFIED'
                         AND json_extract(data_json,'$.reminder_event_id')=? LIMIT 1""",(f"DB{rid}",)).fetchone()
                    if completed or existing: st.error('Có hoàn thành đúng hạn hoặc đã xác minh lần nhắc này.')
                    else:
                        d={'reminder_event_id':f"DB{rid}",'continuous_observation':True,
                           'verified_no_completion':True,'reviewed_by':who.strip(),'evidence_source':src.strip()}
                        con.execute("""INSERT INTO pcbm_events(user_id,task_id,occurrence_id,event_type,data_json,created_at)
                              VALUES(?,?,?,?,?,?)""",(r['user_id'],r['task_id'],r['occurrence_id'],
                              'OBSERVATION_WINDOW_VERIFIED',json.dumps(d,ensure_ascii=False),now.isoformat(timespec='seconds')))
                        con.commit();st.success('Đã lưu bằng chứng Completion = 0.')
    st.warning('Chỉ xác minh quan sát có thật. Các tài khoản test_ không được xem là dữ liệu thực nghiệm độc lập. Sau khi ghi sự kiện, nhấn Train lại để cập nhật nhãn.')
