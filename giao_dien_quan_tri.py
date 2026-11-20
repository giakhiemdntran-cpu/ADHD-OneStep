import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, date, time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from cau_hinh import DB_PATH, OLLAMA_MODEL, OLLAMA_URL, APP_TIMEZONE
from quan_tri_huan_luyen_pcbm import hien_thi_quan_tri_huan_luyen_pcbm
from pcbm_evidence_panel import render_pcbm_evidence

API_BASE = os.getenv("ONESTEP_API_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_PASSWORD = os.getenv("ONESTEP_ADMIN_PASSWORD", "")
REQUEST_TIMEOUT = int(os.getenv("ONESTEP_ADMIN_TIMEOUT", "15"))

st.set_page_config(
    page_title="ADHD OneStep – Trung tâm điều khiển",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {--os-radius:18px;}
      .block-container {padding-top: 1.25rem; padding-bottom: 2.5rem; max-width: 1500px;}
      [data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.16);}
      [data-testid="stSidebar"] .block-container {padding-top: 1.1rem;}
      div[data-testid="stMetric"] {
        border:1px solid rgba(128,128,128,.16); border-radius:var(--os-radius);
        padding:14px 16px; background:rgba(128,128,128,.045);
      }
      div[data-testid="stMetricValue"] {font-size:1.55rem;font-weight:750;}
      div[data-testid="stDataFrame"] {border:1px solid rgba(128,128,128,.14); border-radius:14px; overflow:hidden;}
      .stButton>button, .stDownloadButton>button {border-radius:12px; font-weight:650;}
      .os-hero {
        padding:20px 22px; border:1px solid rgba(128,128,128,.16); border-radius:22px;
        background:linear-gradient(135deg, rgba(80,90,255,.10), rgba(0,190,170,.07));
        margin:0 0 1.1rem 0;
      }
      .os-hero h2 {margin:0 0 .3rem 0; font-size:1.65rem;}
      .os-hero p {margin:0; opacity:.78;}
      .os-card {padding:14px 16px;border:1px solid rgba(128,128,128,.16);border-radius:16px;background:rgba(128,128,128,.035);}
      .small-note {opacity:.72;font-size:.90rem;}
      .ok {color:#15803d;font-weight:650;}
      .bad {color:#b91c1c;font-weight:650;}
      hr {margin-top:1.4rem;margin-bottom:1.4rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def trang_tieu_de(icon, title, subtitle=""):
    st.markdown(
        f'<div class="os-hero"><h2>{icon} {title}</h2><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def viet_hoa_trang_thai(value):
    mapping = {
        "pending": "Đang chờ", "completed": "Hoàn thành", "cancelled": "Đã hủy",
        "once": "Một lần", "weekly": "Hằng tuần", "active": "Đang hoạt động",
        "success": "Thành công", "failed": "Thất bại",
    }
    return mapping.get(str(value).lower(), value)


def viet_hoa_bang_du_lieu(rows):
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).copy()
    rename = {
        "id":"Mã", "title":"Tên nhiệm vụ", "steps":"Các bước", "schedule_type":"Kiểu lặp",
        "scheduled_at":"Thời điểm", "scheduled_time":"Giờ", "repeat_days":"Ngày lặp",
        "estimated_minutes":"Dự kiến (phút)", "deadline_at":"Hạn chót", "habit_key":"Mã thói quen",
        "enabled":"Đang bật", "status":"Trạng thái", "current_step":"Bước hiện tại",
        "snooze_count":"Số lần hoãn", "reminded_at":"Đã nhắc lúc", "started_at":"Bắt đầu lúc",
        "start_delay_minutes":"Trễ bắt đầu (phút)", "prompt_level":"Mức hỗ trợ",
        "user_id":"Người dùng", "task_id":"Mã nhiệm vụ", "occurrence_id":"Mã phiên",
        "event_type":"Loại sự kiện", "created_at":"Thời gian", "model_version":"Phiên bản mô hình",
        "recall_probability":"Khả năng tự nhớ", "completion_30m_probability":"Khả năng hoàn thành 30 phút",
        "recommended_prompt_level":"Mức hỗ trợ đề xuất", "reason_code":"Lý do",
    }
    for col in list(df.columns):
        if col == "status":
            df[col] = df[col].map(viet_hoa_trang_thai)
    return df.rename(columns={k:v for k,v in rename.items() if k in df.columns})




def _dang_nhap_cong():
    if not ADMIN_PASSWORD:
        return
    if st.session_state.get("admin_ok"):
        return
    st.title("🔐 ADHD OneStep Admin")
    st.caption("Nhập mật khẩu quản trị. Đặt bằng biến môi trường ONESTEP_ADMIN_PASSWORD.")
    password = st.text_input("Mật khẩu", type="password")
    if st.button("Đăng nhập", type="primary"):
        if password == ADMIN_PASSWORD:
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("Mật khẩu không đúng.")
    st.stop()


_dang_nhap_cong()


def xu_ly_api(method, path, payload=None, params=None, timeout=REQUEST_TIMEOUT):
    url = f"{API_BASE}{path}"
    try:
        r = requests.request(method, url, json=payload, params=params, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        if not r.ok:
            msg = data.get("message") if isinstance(data, dict) else None
            raise RuntimeError(msg or f"HTTP {r.status_code}: {r.text[:300]}")
        return data
    except requests.RequestException as e:
        raise RuntimeError(f"Không kết nối được API {url}: {e}") from e


def kiem_tra_api_truc_tuyen():
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=2)
        return r.ok, r.json() if r.ok else {}
    except Exception:
        return False, {}


def db_truy_van(sql, params=()):
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def an_toan_json(v):
    if isinstance(v, (dict, list)):
        return v
    if v in (None, ""):
        return []
    try:
        return json.loads(v)
    except Exception:
        return v


def chuan_hoa_nhiem_vu_dong(rows):
    out = []
    for r in rows or []:
        x = dict(r)
        if "steps" in x:
            x["steps"] = " → ".join(an_toan_json(x["steps"]) or []) if not isinstance(x["steps"], list) else " → ".join(x["steps"])
        if "repeat_days" in x:
            x["repeat_days"] = ", ".join(an_toan_json(x["repeat_days"]) or []) if not isinstance(x["repeat_days"], list) else ", ".join(x["repeat_days"])
        out.append(x)
    return out


def lay_trang_thai():
    try:
        return xu_ly_api("GET", "/api/state")
    except Exception:
        return {
            "tasks": db_truy_van("SELECT * FROM tasks WHERE enabled=1 ORDER BY id DESC"),
            "history": db_truy_van("SELECT * FROM task_history ORDER BY id DESC LIMIT 100"),
            "current": {"done": True, "message": "API chưa chạy"},
            "coaching": db_truy_van("SELECT * FROM habit_profiles ORDER BY updated_at DESC"),
            "memory_checks": db_truy_van("SELECT * FROM memory_checks ORDER BY id DESC LIMIT 20"),
            "vision": {"enabled": None},
            "adhd_mode_enabled": None,
            "coaching_device_mode": None,
        }


def ket_hop_thoi_gian(d: date, t: time):
    return datetime.combine(d, t).isoformat(timespec="minutes")


online, health = kiem_tra_api_truc_tuyen()
state = lay_trang_thai()

st.sidebar.title("🧠 ADHD OneStep")
st.sidebar.caption("Huấn luyện viên nhận thức AI")
if online:
    st.sidebar.success("Máy chủ OneStep: Đang hoạt động")
else:
    st.sidebar.error("Máy chủ OneStep: Chưa kết nối")
st.sidebar.code(API_BASE, language=None)
st.sidebar.caption(f"DB: {DB_PATH}")
st.sidebar.caption(f"Ollama: {OLLAMA_MODEL}")
if st.sidebar.button("🔄 Làm mới"):
    st.rerun()

page = st.sidebar.radio(
    "Chức năng",
    [
        "📊 Tổng quan",
        "➕ Tạo nhiệm vụ",
        "🗂️ Quản lý nhiệm vụ",
        "▶️ Nhiệm vụ hiện tại",
        "🧠 Huấn luyện ghi nhớ",
        "👁️ Bộ nhớ đồ vật",
        "🤖 AI nhận thức cá nhân",
        "🧪 Quản trị huấn luyện PCBM",
        "🛡️ Minh chứng & An toàn PCBM",
        "🔌 Kiểm thử API",
        "🗄️ Kho dữ liệu",
        "⚙️ Hệ thống",
    ],
)


if page == "📊 Tổng quan":
    trang_tieu_de("📊", "Tổng quan", "Theo dõi nhiệm vụ, tiến trình hỗ trợ và trạng thái toàn hệ thống.")
    tasks = state.get("tasks") or []
    hist = state.get("history") or []
    current = state.get("current") or {}
    habits = state.get("coaching") or []

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nhiệm vụ đang bật", len(tasks))
    c2.metric("Lịch sử thao tác", len(hist))
    c3.metric("Hồ sơ thói quen", len(habits))
    c4.metric("Máy chủ", "Online" if online else "Offline")

    st.subheader("Nhiệm vụ hiện tại")
    if current.get("done"):
        st.info(current.get("message", "Hiện chưa có task."))
    else:
        a, b, c = st.columns([2, 1, 1])
        a.markdown(f"### {current.get('task_name','')}")
        a.write(f"Bước {current.get('step_index')}/{current.get('total_steps')}: **{current.get('current_step','')}**")
        b.metric("Thời gian", current.get("scheduled_at") or "-")
        c.metric("Prompt level", next((h.get("prompt_level") for h in habits if h.get("habit_key") == current.get("habit_key")), "-"))

    st.subheader("Nhiệm vụ theo lịch")
    if tasks:
        st.dataframe(viet_hoa_bang_du_lieu(chuan_hoa_nhiem_vu_dong(tasks)), use_container_width=True, hide_index=True)
    else:
        st.caption("Chưa có nhiệm vụ.")

    if hist:
        st.subheader("Hoạt động gần đây")
        st.dataframe(viet_hoa_bang_du_lieu(hist[:12]), use_container_width=True, hide_index=True)


elif page == "➕ Tạo nhiệm vụ":
    trang_tieu_de("➕", "Tạo nhiệm vụ", "Tạo bằng câu lệnh tiếng Việt hoặc nhập thủ công.")
    tab_ai, tab_manual = st.tabs(["✨ Tạo bằng câu tiếng Việt", "📝 Nhập thủ công"])

    with tab_ai:
        st.caption("Qwen 3B xác định intent; Hybrid Parser của v9.7 bóc title, ngày, giờ, lặp và thời lượng.")
        utterance = st.text_area(
            "Nhập câu lệnh",
            placeholder="Ví dụ: Thứ hai, thứ tư, thứ sáu lúc 6:30 nhắc mình tập thể dục 20 phút",
            height=110,
        )
        col1, col2 = st.columns([1, 3])
        if col1.button("Phân tích", type="primary", disabled=not utterance.strip()):
            try:
                parsed = xu_ly_api("POST", "/api/ai/parse", {"text": utterance})
                st.session_state.ai_parsed = parsed.get("command", parsed)
            except Exception as e:
                st.error(str(e))

        parsed = st.session_state.get("ai_parsed")
        if parsed:
            st.json(parsed)
            if parsed.get("intent") not in {"create_task", "coach_task"}:
                st.warning(f"Intent hiện là `{parsed.get('intent')}` nên chưa tạo task tự động.")
            elif st.button("✅ Tạo task từ kết quả này"):
                payload = {
                    "title": parsed.get("title"),
                    "steps": [parsed.get("title")] if parsed.get("title") else [],
                    "schedule_type": parsed.get("schedule_type") or "once",
                    "scheduled_at": parsed.get("scheduled_at"),
                    "scheduled_time": parsed.get("scheduled_time"),
                    "repeat_days": parsed.get("repeat_days") or [],
                    "estimated_minutes": parsed.get("estimated_minutes"),
                    "deadline_at": parsed.get("deadline_at"),
                    "habit_key": None,
                }
                try:
                    r = xu_ly_api("POST", "/api/tasks", payload)
                    st.success(f"Đã tạo: {r['task']['title']}")
                    st.session_state.ai_parsed = None
                except Exception as e:
                    st.error(str(e))

    with tab_manual:
        with st.form("create_task_manual", clear_on_submit=False):
            title = st.text_input("Tên nhiệm vụ *", placeholder="Uống nước")
            steps_text = st.text_area("Các bước – mỗi dòng một bước", placeholder="Lấy bình nước\nUống một cốc")
            habit_key = st.text_input("Mã thói quen", placeholder="drink_water")
            est = st.number_input("Thời lượng dự kiến (phút)", min_value=0, max_value=600, value=0, step=5)
            typ = st.radio("Kiểu lặp", ["once", "weekly"], horizontal=True)

            if typ == "once":
                c1, c2 = st.columns(2)
                d = c1.date_input("Ngày", value=date.today())
                t = c2.time_input("Giờ", value=(datetime.now().replace(second=0, microsecond=0)).time())
                scheduled_at = ket_hop_thoi_gian(d, t)
                scheduled_time = None
                repeat_days = []
            else:
                scheduled_at = None
                scheduled_time = st.time_input("Giờ lặp", value=time(7, 0)).strftime("%H:%M")
                weekday_map = {"Thứ Hai":"MON", "Thứ Ba":"TUE", "Thứ Tư":"WED", "Thứ Năm":"THU", "Thứ Sáu":"FRI", "Thứ Bảy":"SAT", "Chủ Nhật":"SUN"}
                selected_days = st.multiselect(
                    "Ngày trong tuần",
                    list(weekday_map.keys()),
                    default=["Thứ Hai", "Thứ Tư", "Thứ Sáu"],
                )
                repeat_days = [weekday_map[x] for x in selected_days]

            deadline_enabled = st.checkbox("Có hạn chót")
            deadline_at = None
            if deadline_enabled:
                c1, c2 = st.columns(2)
                dd = c1.date_input("Ngày hạn chót", value=date.today(), key="deadline_date")
                dt = c2.time_input("Giờ hạn chót", value=time(23, 59), key="deadline_time")
                deadline_at = ket_hop_thoi_gian(dd, dt)

            submitted = st.form_submit_button("Tạo nhiệm vụ", type="primary")
            if submitted:
                payload = {
                    "title": title,
                    "steps": [x.strip() for x in steps_text.splitlines() if x.strip()],
                    "schedule_type": typ,
                    "scheduled_at": scheduled_at,
                    "scheduled_time": scheduled_time,
                    "repeat_days": repeat_days,
                    "estimated_minutes": int(est) if est else None,
                    "deadline_at": deadline_at,
                    "habit_key": habit_key.strip() or None,
                }
                try:
                    r = xu_ly_api("POST", "/api/tasks", payload)
                    st.success(f"Đã lưu nhiệm vụ #{r['task']['id']}: {r['task']['title']}")
                except Exception as e:
                    st.error(str(e))


elif page == "🗂️ Quản lý nhiệm vụ":
    trang_tieu_de("🗂️", "Quản lý nhiệm vụ", "Chỉnh sửa, hủy hoặc xóa các nhiệm vụ đang hoạt động.")
    tasks = state.get("tasks") or []
    if not tasks:
        st.info("Chưa có nhiệm vụ đang bật.")
    else:
        st.dataframe(viet_hoa_bang_du_lieu(chuan_hoa_nhiem_vu_dong(tasks)), use_container_width=True, hide_index=True)
        labels = {f"#{t['id']} – {t['title']}": t for t in tasks}
        selected_label = st.selectbox("Chọn nhiệm vụ", list(labels))
        tsk = labels[selected_label]
        with st.form("edit_task"):
            title = st.text_input("Tên", value=tsk.get("title") or "")
            steps = st.text_area("Các bước", value="\n".join(tsk.get("steps") or []))
            habit_key = st.text_input("Mã thói quen", value=tsk.get("habit_key") or "")
            estimate = st.number_input("Dự kiến (phút)", min_value=0, max_value=600, value=int(tsk.get("estimated_minutes") or 0))
            submitted = st.form_submit_button("💾 Lưu thay đổi")
            if submitted:
                payload = {
                    "title": title,
                    "steps": [x.strip() for x in steps.splitlines() if x.strip()],
                    "habit_key": habit_key.strip() or None,
                    "estimated_minutes": estimate or None,
                }
                try:
                    xu_ly_api("PUT", f"/api/tasks/{tsk['id']}", payload)
                    st.success("Đã cập nhật.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        c1, c2 = st.columns(2)
        if c1.button("Hủy nhiệm vụ và ghi lịch sử", type="secondary"):
            try:
                xu_ly_api("POST", f"/api/tasks/{tsk['id']}/cancel")
                st.success("Đã hủy nhiệm vụ.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
        if c2.button("Xóa nhiệm vụ hoàn toàn", type="secondary"):
            try:
                xu_ly_api("DELETE", f"/api/tasks/{tsk['id']}")
                st.success("Đã xóa nhiệm vụ.")
                st.rerun()
            except Exception as e:
                st.error(str(e))


elif page == "▶️ Nhiệm vụ hiện tại":
    trang_tieu_de("▶️", "Nhiệm vụ hiện tại", "Điều khiển nhiệm vụ đang đến lượt thực hiện.")
    cur = state.get("current") or {}
    if cur.get("done"):
        st.info(cur.get("message", "Không có nhiệm vụ."))
    else:
        st.markdown(f"## {cur.get('task_name')}")
        st.write(f"**Bước {cur.get('step_index')}/{cur.get('total_steps')}:** {cur.get('current_step')}")
        st.write(f"**Lịch:** {cur.get('scheduled_at')}")
        st.write(f"**Habit:** {cur.get('habit_key') or '-'}")
        st.write(f"**Dự kiến:** {cur.get('estimated_minutes') or '-'} phút")

        c1, c2, c3, c4 = st.columns(4)
        if c1.button("▶ Bắt đầu", use_container_width=True):
            try:
                st.json(xu_ly_api("POST", "/api/tasks/current/start"))
            except Exception as e:
                st.error(str(e))
        if c2.button("✅ Xong bước", use_container_width=True):
            try:
                st.json(xu_ly_api("POST", "/api/tasks/current/complete"))
                st.rerun()
            except Exception as e:
                st.error(str(e))
        snooze = c3.number_input("Hoãn phút", min_value=1, max_value=120, value=5, label_visibility="collapsed")
        if c3.button("⏰ Hoãn", use_container_width=True):
            try:
                st.json(xu_ly_api("POST", "/api/tasks/current/snooze", {"minutes": int(snooze)}))
                st.rerun()
            except Exception as e:
                st.error(str(e))
        if c4.button("🗑 Hủy", use_container_width=True):
            try:
                st.json(xu_ly_api("POST", "/api/tasks/current/cancel"))
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.subheader("Các phiên nhiệm vụ đang chờ")
    pending = db_truy_van("""
        SELECT o.id occurrence_id,o.task_id,t.title,o.scheduled_at,o.status,o.current_step,
               o.snooze_count,o.reminded_at,o.started_at,o.start_delay_minutes
        FROM task_occurrences o JOIN tasks t ON t.id=o.task_id
        WHERE o.status='pending' ORDER BY o.scheduled_at
    """)
    st.dataframe(viet_hoa_bang_du_lieu(pending), use_container_width=True, hide_index=True) if pending else st.caption("Không có phiên nhiệm vụ nào đang chờ.")


elif page == "🧠 Huấn luyện ghi nhớ":
    trang_tieu_de("🧠", "Huấn luyện ghi nhớ 2 → 1 → 0", "Giảm dần mức hỗ trợ khi người dùng có thể tự nhớ ổn định hơn.")
    try:
        progress = xu_ly_api("GET", "/api/coaching/progress").get("habits", [])
        checks = xu_ly_api("GET", "/api/coaching/memory-checks", params={"limit": 100}).get("checks", [])
        events = xu_ly_api("GET", "/api/coaching/events").get("events", [])
    except Exception as e:
        st.warning(str(e))
        progress = db_truy_van("SELECT * FROM habit_profiles ORDER BY updated_at DESC")
        checks = db_truy_van("SELECT * FROM memory_checks ORDER BY id DESC LIMIT 100")
        events = db_truy_van("SELECT * FROM coaching_events ORDER BY id DESC LIMIT 100")

    t1, t2, t3 = st.tabs(["Hồ sơ thói quen", "Kiểm tra ghi nhớ", "Sự kiện huấn luyện"])
    with t1:
        if progress:
            st.dataframe(viet_hoa_bang_du_lieu(progress), use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có hồ sơ thói quen.")
    with t2:
        if checks:
            st.dataframe(viet_hoa_bang_du_lieu(checks), use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có lần kiểm tra ghi nhớ.")
    with t3:
        if events:
            st.dataframe(viet_hoa_bang_du_lieu(events), use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có sự kiện huấn luyện.")


elif page == "👁️ Bộ nhớ đồ vật":
    trang_tieu_de("👁️", "Bộ nhớ đồ vật", "Hỗ trợ kiểm tra và ghi nhớ vị trí đồ dùng khi người dùng chủ động yêu cầu.")
    try:
        status = xu_ly_api("GET", "/api/vision/status")
        st.json(status)
    except Exception as e:
        st.warning(str(e))

    c1, c2 = st.columns([2, 1])
    item = c1.text_input("Tên đồ vật cần tìm", placeholder="bottle / backpack / book")
    live = c2.checkbox("Kiểm tra bằng camera", value=True)
    if st.button("🔎 Tìm đồ vật", disabled=not item.strip()):
        try:
            r = xu_ly_api("POST", "/api/vision/find", {"object": item, "try_live": live}, timeout=45)
            st.json(r)
            if r.get("snapshot_url"):
                st.image(f"{API_BASE}{r['snapshot_url']}", caption=r.get("message", "Vision snapshot"), use_container_width=True)
        except Exception as e:
            st.error(str(e))

    c1, c2 = st.columns(2)
    if c1.button("🧹 Cleanup dữ liệu Vision > retention"):
        try:
            st.json(xu_ly_api("POST", "/api/vision/cleanup"))
        except Exception as e:
            st.error(str(e))
    limit = c2.number_input("Số lần quan sát", min_value=10, max_value=500, value=100, step=10)
    try:
        sightings = xu_ly_api("GET", "/api/vision/sightings", params={"limit": int(limit)}).get("sightings", [])
    except Exception:
        sightings = db_truy_van("SELECT * FROM object_sightings ORDER BY seen_at DESC LIMIT ?", (int(limit),))
    if sightings:
        st.dataframe(viet_hoa_bang_du_lieu(sightings), use_container_width=True, hide_index=True)



elif page == "🤖 AI nhận thức cá nhân":
    trang_tieu_de("🤖", "AI nhận thức cá nhân", "Học từ lịch sử hành vi trong SQLite để dự đoán mức hỗ trợ phù hợp cho từng người dùng.")
    st.caption(
        "OneStep học trực tiếp từ lịch sử hành vi được lưu cục bộ. Các đặc trưng được tính riêng "
        "cho từng người dùng; hai mô hình hiện tại dự đoán khả năng tự nhớ và khả năng hoàn thành nhiệm vụ trong 30 phút."
    )

    try:
        ps = xu_ly_api("GET", "/api/pcbm/status")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mô hình cá nhân", "BẬT" if ps.get("enabled") else "TẮT")
        c2.metric("Mô hình tự nhớ", "Đã nạp" if ps.get("recall_model_loaded") else "Chưa có")
        c3.metric("Sự kiện hành vi", ps.get("live_event_count", 0))
        c4.metric("Số lần dự đoán", ps.get("prediction_count", 0))

        test_events = db_truy_van("SELECT COUNT(*) AS n FROM pcbm_events WHERE user_id LIKE 'test_%'")[0]["n"]
        test_users = db_truy_van("SELECT COUNT(DISTINCT user_id) AS n FROM pcbm_events WHERE user_id LIKE 'test_%'")[0]["n"]
        total_users = db_truy_van("SELECT COUNT(DISTINCT user_id) AS n FROM pcbm_events")[0]["n"]
        st.markdown("### Dữ liệu phục vụ huấn luyện")
        d1, d2, d3 = st.columns(3)
        d1.metric("Sự kiện thử nghiệm", f"{test_events:,}")
        d2.metric("Người dùng thử nghiệm", f"{test_users:,}")
        d3.metric("Tổng người dùng trong dữ liệu", f"{total_users:,}")
        st.caption("Bộ dữ liệu thử nghiệm đi qua cùng quy trình tạo đặc trưng, tạo nhãn và huấn luyện như dữ liệu hành vi thực tế.")

        sample_large = Path(__file__).resolve().parent / "data" / "sample_events_v4_1_large.jsonl"
        if sample_large.exists():
            with st.expander("Nạp lại bộ dữ liệu PCBM large (16.693 sự kiện)"):
                st.warning("Thao tác này chỉ xóa các sự kiện có mã người dùng bắt đầu bằng test_ rồi nạp lại bộ dữ liệu thử nghiệm; dữ liệu người dùng thật không bị xóa.")
                if st.button("📥 Nạp lại 16.693 sự kiện thử nghiệm", use_container_width=True):
                    cmd = [sys.executable, str(Path(__file__).resolve().parent / "cong_cu" / "nhap_du_lieu_pcbm_large.py"), "--file", str(sample_large), "--reset"]
                    with st.spinner("Đang nạp dữ liệu thử nghiệm vào SQLite..."):
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if proc.returncode == 0:
                        st.success("Đã nạp lại dữ liệu thử nghiệm thành công.")
                        st.code(proc.stdout[-4000:])
                    else:
                        st.error("Không thể nạp dữ liệu thử nghiệm.")
                        st.code((proc.stderr or proc.stdout)[-4000:])

        st.subheader("Huấn luyện từ lịch sử hành vi")
        st.info(
            "PCBM sử dụng trực tiếp nhật ký hành vi trong SQLite; nhãn recall chỉ lấy sau generic cue, "
            "bổ sung đặc trưng recall 1/3/7 ngày, streak và same-task; sau đó đánh giá walk-forward, "
            "so sánh nhiều mô hình và lưu mô hình tốt nhất theo PR-AUC."
        )

        if st.button("🧠 Huấn luyện mô hình cá nhân từ dữ liệu SQLite", type="primary", use_container_width=True):
            with st.spinner("Đang tạo đặc trưng, nhãn và huấn luyện hai mô hình..."):
                r = xu_ly_api("POST", "/api/pcbm/train-db", timeout=180)
            st.session_state["pcbm_train_db_result"] = r
            st.success(
                f"Đã huấn luyện xong từ {r.get('events_used', 0):,} sự kiện, "
                f"tạo {r.get('training_records', 0):,} bản ghi huấn luyện."
            )

        train_result = st.session_state.get("pcbm_train_db_result")
        if train_result:
            st.subheader("Kết quả huấn luyện gần nhất")
            a, b, c = st.columns(3)
            a.metric("Sự kiện đã dùng", f"{train_result.get('events_used', 0):,}")
            b.metric("Bản ghi huấn luyện", f"{train_result.get('training_records', 0):,}")
            c.metric("Số người dùng", f"{train_result.get('users', 0):,}")

            def hien_thi_mo_hinh_ket_qua(title, item):
                st.markdown(f"**{title}**")
                ev = (item or {}).get("evaluation") or {}
                x1, x2, x3, x4 = st.columns(4)
                x1.metric("Bản ghi huấn luyện", (item or {}).get("training_rows", 0))
                x2.metric("Mô hình chọn", (item or {}).get("model_name") or ev.get("selected_model") or "N/A")
                x3.metric("PR-AUC", f"{ev.get('pr_auc'):.3f}" if ev.get("available") and ev.get("pr_auc") is not None else "N/A")
                x4.metric("F1", f"{ev.get('f1'):.3f}" if ev.get("available") and ev.get("f1") is not None else "N/A")
                if ev.get("available"):
                    st.caption(
                        f"Walk-forward {ev.get('n_splits', 0)} folds · "
                        f"ROC-AUC: {ev.get('roc_auc') if ev.get('roc_auc') is not None else 'N/A'} · "
                        f"Accuracy: {ev.get('accuracy', 0):.3f} · Recall: {ev.get('recall', 0):.3f} · "
                        f"Brier: {ev.get('brier_score', 0):.3f} · ECE: {ev.get('ece_10bin', 0):.3f}"
                    )
                else:
                    st.warning(ev.get("reason", "Chưa đủ dữ liệu để đánh giá."))

            hien_thi_mo_hinh_ket_qua("Mô hình dự đoán khả năng tự nhớ", train_result.get("recall_model"))
            hien_thi_mo_hinh_ket_qua("Mô hình dự đoán hoàn thành trong 30 phút", train_result.get("completion_model"))

            st.markdown("**Tệp mô hình đã lưu**")
            st.json(train_result.get("saved_models", {}))

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("🧪 Huấn luyện nhanh từ bộ dữ liệu mẫu nhỏ"):
            with st.spinner("Đang huấn luyện mô hình mẫu..."):
                r = xu_ly_api("POST", "/api/pcbm/train-sample", timeout=180)
            st.success("Đã huấn luyện lại mô hình mẫu.")
            st.code(r.get("stdout", ""))

        if c2.button("🎯 Tạo khuyến nghị cho nhiệm vụ hiện tại"):
            try:
                r = xu_ly_api("GET", "/api/pcbm/recommend/current")
                st.session_state["pcbm_rec"] = r.get("recommendation")
            except Exception as e:
                st.error(str(e))

        if st.session_state.get("pcbm_rec"):
            st.subheader("Khuyến nghị hiện tại")
            st.json(st.session_state["pcbm_rec"])

        with st.expander("Trạng thái mô hình và lần huấn luyện gần nhất"):
            st.json(ps)

        st.subheader("Nhật ký hành vi dùng cho AI")
        ev = xu_ly_api("GET", "/api/pcbm/events?limit=100").get("events", [])
        if ev:
            st.dataframe(viet_hoa_bang_du_lieu(ev), use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có sự kiện PCBM.")

        st.subheader("Lịch sử dự đoán và khuyến nghị")
        pred = xu_ly_api("GET", "/api/pcbm/predictions?limit=50").get("predictions", [])
        if pred:
            rows = []
            for x in pred:
                y = dict(x)
                out = y.pop("output", {}) or {}
                y["recall_probability"] = out.get("recall_probability")
                y["completion_30m_probability"] = out.get("completion_30m_probability")
                y["recommended_prompt_level"] = out.get("recommended_prompt_level")
                y["reason_code"] = out.get("reason_code")
                y.pop("features", None)
                rows.append(y)
            st.dataframe(viet_hoa_bang_du_lieu(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Chưa có dự đoán.")
    except Exception as e:
        st.error(f"Không đọc được PCBM API: {e}")


elif page == "🧪 Quản trị huấn luyện PCBM":
    hien_thi_quan_tri_huan_luyen_pcbm()


elif page == "🛡️ Minh chứng & An toàn PCBM":
    render_pcbm_evidence()

elif page == "🔌 Kiểm thử API":
    trang_tieu_de("🔌", "Kiểm thử API", "Công cụ kỹ thuật để kiểm tra các dịch vụ của OneStep.")
    st.caption("Dùng để test Flask API của OneStep trực tiếp từ trình duyệt quản trị.")
    endpoints = [
        "GET /api/health",
        "GET /api/state",
        "GET /api/coaching/progress",
        "GET /api/vision/status",
        "GET /api/band/state",
        "POST /api/ai/parse",
        "POST /api/pcbm/train-db",
        "POST /api/tasks",
        "POST /api/tasks/current/start",
        "POST /api/tasks/current/complete",
        "POST /api/tasks/current/snooze",
        "POST /api/tasks/current/cancel",
    ]
    st.code("\n".join(endpoints))

    c1, c2 = st.columns([1, 3])
    method = c1.selectbox("Phương thức", ["GET", "POST", "PUT", "DELETE"])
    path = c2.text_input("Đường dẫn", value="/api/state")
    body = st.text_area("Nội dung JSON", value="{}", height=140)
    if st.button("Gửi yêu cầu", type="primary"):
        try:
            payload = json.loads(body or "{}") if method != "GET" else None
            result = xu_ly_api(method, path, payload=payload)
            st.json(result)
        except Exception as e:
            st.error(str(e))


elif page == "🗄️ Kho dữ liệu":
    trang_tieu_de("🗄️", "Kho dữ liệu", "Xem dữ liệu cục bộ phục vụ kiểm thử, huấn luyện và đánh giá.")
    tables = [r["name"] for r in db_truy_van("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    table = st.selectbox("Bảng dữ liệu", tables)
    limit = st.slider("Số dòng hiển thị", 20, 1000, 200, step=20)
    if table:
        rows = db_truy_van(f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT ?', (limit,))
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            st.download_button(
                "⬇️ Tải CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{table}_{datetime.now():%Y%m%d_%H%M}.csv",
                mime="text/csv",
            )
    st.caption("Trang này chỉ đọc dữ liệu thô. Tạo/sửa/xóa task nên dùng trang Quản lý Task để bảo toàn logic occurrences/coaching.")


elif page == "⚙️ Hệ thống":
    trang_tieu_de("⚙️", "Hệ thống", "Kiểm tra cấu hình, kết nối và dịch vụ đang sử dụng.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Ứng dụng OneStep")
        st.json({
            "api_base": API_BASE,
            "api_online": online,
            "db_path": str(DB_PATH),
            "db_exists": Path(DB_PATH).exists(),
            "timezone": APP_TIMEZONE,
        })
    with c2:
        st.subheader("Ollama")
        st.json({"url": OLLAMA_URL, "model": OLLAMA_MODEL})
        if st.button("Kiểm tra Ollama"):
            try:
                r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
                r.raise_for_status()
                tags = r.json()
                st.success("Ollama đang hoạt động.")
                st.json(tags)
            except Exception as e:
                st.error(f"Không kết nối được Ollama: {e}")

    st.subheader("Trạng thái máy chủ")
    st.json(health if online else {"online": False})
    st.info("Giao diện quản trị dùng chung cơ sở dữ liệu với Robot Buddy. Khi máy chủ OneStep đang chạy, các thao tác thay đổi được gửi qua API để bảo toàn logic nhiệm vụ và huấn luyện.")
