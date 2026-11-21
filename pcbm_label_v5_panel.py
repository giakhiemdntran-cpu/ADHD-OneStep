"""Streamlit page for evidence-aware PCBM v5 label inspection.

Read-only; it NEVER trains models, changes labels in DB, or changes support levels.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from huan_luyen_pcbm.nhan_v5 import tao_nhan_v5, ap_dung_kiem_tra_coverage

ROOT = Path(__file__).resolve().parent
DB = ROOT / "storage" / "onestep.db"
DISPLAY = {
    "recall_after_cue": "Nhớ sau gợi ý chung (2 phút)",
    "independent_recall": "Tự nhớ trước lời nhắc",
    "started_within_10m": "Bắt đầu trong 10 phút",
    "completed_within_30m": "Hoàn thành trong 30 phút",
}
REASONS = {
    "no_recall_answer_in_2m": "Không có câu trả lời ghi nhận trong cửa sổ 2 phút",
    "recall_window_not_fully_observed": "Chưa quan sát đủ cửa sổ 2 phút",
    "not_a_generic_cue": "Đây không phải lời gợi ý chung",
    "independent_recall_not_observed": "Không có bằng chứng tự nhớ độc lập đủ điều kiện",
    "started_within_10m_censored": "Chưa quan sát đủ 10 phút",
    "completed_within_30m_censored": "Chưa quan sát đủ 30 phút",
    "started_within_10m_no_verified_coverage": "Không xác minh được quan sát liên tục 10 phút",
    "completed_within_30m_no_verified_coverage": "Không xác minh được quan sát liên tục 30 phút",
}


def _fmt_label(value):
    return "Unknown" if value is None else str(int(value))


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _as_events(rows):
    events = []
    for row in rows:
        dt = _parse_time(row["created_at"])
        if dt is None:
            continue
        try:
            info = json.loads(row["data_json"] or "{}")
            if not isinstance(info, dict):
                info = {}
        except (ValueError, TypeError):
            info = {}
        events.append({"event_id": row["id"], "user_id": row["user_id"],
                       "occurrence_id": row["occurrence_id"], "event_type": row["event_type"],
                       "timestamp": dt, "data": info})
    return sorted(events, key=lambda e: (e["timestamp"], e["event_id"]))


def _read_connection():
    if not DB.is_file():
        raise FileNotFoundError(f"Không tìm thấy database: {DB}")
    con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _load_userids():
    with _read_connection() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT user_id FROM pcbm_events WHERE user_id IS NOT NULL ORDER BY user_id")]


def _load_occurrences(user_id, limit=100):
    # No read of arbitrary user-supplied SQL. Select only task occurrences with actual reminder event.
    with _read_connection() as con:
        return [dict(row) for row in con.execute(
            """SELECT occurrence_id, MAX(created_at) AS latest, COUNT(*) AS event_count
               FROM pcbm_events WHERE user_id = ? AND occurrence_id IS NOT NULL
               AND occurrence_id != ''
               GROUP BY occurrence_id
               HAVING SUM(CASE WHEN event_type = 'REMINDER_SENT' THEN 1 ELSE 0 END) > 0
               ORDER BY latest DESC LIMIT ?""", (user_id, limit))]


def _load_events(user_id, occurrence_id):
    with _read_connection() as con:
        rows = con.execute(
            """SELECT id, user_id, occurrence_id, event_type, data_json, created_at
               FROM pcbm_events WHERE user_id = ? AND occurrence_id = ?
               ORDER BY created_at, id""", (user_id, occurrence_id)).fetchall()
    return _as_events(rows)


def _prior_prompt(events, decision):
    prev = [e["timestamp"] for e in events if e["event_type"] == "REMINDER_SENT" and e["timestamp"] < decision["timestamp"]]
    return max(prev) if prev else None


def _analyze(events, decision, observation_end, verified_coverage=False):
    result = tao_nhan_v5(events, decision, observation_end,
                        previous_prompt_time=_prior_prompt(events, decision))
    return ap_dung_kiem_tra_coverage(result, observed_continuously=verified_coverage)


def _show_labels(result):
    data = []
    for key, desc in DISPLAY.items():
        value = result.get(key)
        data.append({"Nhãn": desc, "Giá trị": _fmt_label(value),
                     "Cách hiểu": "Có bằng chứng dương tính" if value == 1 else
                                  ("Âm tính có điều kiện quan sát" if value == 0 else "Chưa đủ bằng chứng để kết luận")})
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    st.caption(f"Chất lượng nhãn: {result.get('label_quality', '—')} | Schema: {result.get('label_schema_version', '—')}")
    reasons = [REASONS.get(x, x) for x in result.get("label_reasons", [])]
    if reasons:
        st.info("**Lý do / giới hạn:** " + "; ".join(reasons))
    if result.get("independent_recall") is None:
        st.caption("Không kết luận 'tự nhớ' từ việc hoàn thành nhiệm vụ hoặc chỉ từ việc có sự kiện Recall sau lời nhắc.")


def _scenario(name):
    t = datetime(2026, 11, 20, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    decision = {"user_id": "DEMO_LABEL", "occurrence_id": "demo_01",
                "event_type": "REMINDER_SENT", "timestamp": t,
                "data": {"reminder_type": "generic"}}
    def event(kind, minute, data=None):
        return {"user_id": "DEMO_LABEL", "occurrence_id": "demo_01", "event_type": kind,
                "timestamp": t + timedelta(minutes=minute), "data": data or {}}
    if name == "Nhớ sau gợi ý (không phải tự nhớ)":
        return [decision, event("RECALL_SUCCESS", 1)], decision, t + timedelta(minutes=3), False
    if name == "Mới quan sát 3 phút":
        return [decision], decision, t + timedelta(minutes=3), False
    if name == "Hoàn thành ở phút 20":
        return [decision, event("TASK_STARTED", 3), event("TASK_COMPLETED", 20)], decision, t + timedelta(minutes=31), False
    if name == "Đủ 30 phút nhưng không xác nhận giám sát":
        return [decision], decision, t + timedelta(minutes=40), False
    if name == "Giám sát đầy đủ 30 phút (giả lập)":
        return [decision], decision, t + timedelta(minutes=40), True
    if name == "Có USER_REMEMBERED trước lời nhắc":
        # Shows limitation: no prior prompting boundary => cannot conclude independent recall.
        return [event("USER_REMEMBERED", -5, {"evidence_source": "user_initiated_action"}), decision], decision, t + timedelta(minutes=3), False
    raise ValueError(name)


def render_pcbm_label_v5():
    st.title("🏷️ Kiểm thử nhãn PCBM v5")
    st.caption("Định nghĩa nhãn theo bằng chứng, xem 0 / 1 / Unknown. Có tab huấn luyện thử trên SQLite; không thay Level và không ghi vào SQLite.")
    st.warning("Recall sau gợi ý ≠ tự nhớ độc lập. Thiếu sự kiện không đồng nghĩa thất bại; cần xác minh giám sát đủ thời gian để gán nhãn 0.")
    a, b, c, d = st.tabs(["🧪 Kịch bản mẫu", "🗄️ Kiểm tra trên SQLite", "📊 Đánh giá độc lập từ CSV", "🧬 Huấn luyện kết hợp v5"])

    with a:
        st.subheader("Thử quy tắc gán nhãn bằng tình huống mô phỏng")
        options = ["Nhớ sau gợi ý (không phải tự nhớ)", "Mới quan sát 3 phút", "Hoàn thành ở phút 20",
                   "Đủ 30 phút nhưng không xác nhận giám sát", "Giám sát đầy đủ 30 phút (giả lập)",
                   "Có USER_REMEMBERED trước lời nhắc"]
        chosen = st.selectbox("Chọn tình huống", options, key="label_v5_scenario")
        events, decision, end, coverage = _scenario(chosen)
        st.caption(f"Dữ liệu DEMO • Mốc nhắc: {decision['timestamp'].isoformat()} • Thời điểm quan sát: {end.isoformat()}")
        result = _analyze(events, decision, end, coverage)
        _show_labels(result)
        with st.expander("Xem sự kiện dùng để gán nhãn"):
            st.dataframe(pd.DataFrame([{"Thời điểm": x["timestamp"].isoformat(), "Sự kiện": x["event_type"],
                                      "Thông tin": json.dumps(x["data"], ensure_ascii=False)} for x in events]),
                         use_container_width=True, hide_index=True)

    with b:
        st.subheader("Đọc sự kiện PCBM có thật trong SQLite")
        st.caption("Chỉ kiểm tra nhãn từ nhật ký; dữ liệu test_Uxxx trong SQLite vẫn là dữ liệu mô phỏng. Không coi là thử nghiệm lâm sàng.")
        try:
            users = _load_userids()
            if not users:
                st.info("Không tìm thấy user trong bảng pcbm_events.")
            else:
                user = st.selectbox("Người dùng", users, key="label_v5_user")
                occ = _load_occurrences(user)
                if not occ:
                    st.info("Người dùng chưa có occurrence chứa REMINDER_SENT.")
                else:
                    names = [f"{r['occurrence_id']} · {r['event_count']} events" for r in occ]
                    idx = st.selectbox("Lần thực hiện nhiệm vụ", range(len(occ)),
                                       format_func=lambda x: names[x], key="label_v5_occ")
                    events = _load_events(user, occ[idx]["occurrence_id"])
                    choices = [e for e in events if e["event_type"] == "REMINDER_SENT"]
                    if choices:
                        index = st.selectbox("Chọn lần nhắc (điểm quyết định)", range(len(choices)),
                                             format_func=lambda j: f"{choices[j]['timestamp'].isoformat()} · {choices[j]['data'].get('reminder_type','?')}",
                                             key="label_v5_decision")
                        decision = choices[index]
                        last_event_time = events[-1]["timestamp"]
                        observation_end = max(last_event_time, decision["timestamp"])
                        st.caption(f"Thời điểm event cuối trong occurrence: {observation_end.isoformat()} (không có nghĩa đã giám sát liên tục)")
                        st.info("Để tránh nhãn âm sai, trang mặc định **không xác nhận giám sát liên tục**; các giá trị 0 vì không có sự kiện sẽ chuyển thành Unknown.")
                        result = _analyze(events, decision, observation_end, False)
                        _show_labels(result)
                        with st.expander("Xem nhật ký làm bằng chứng"):
                            st.dataframe(pd.DataFrame([{"Thời điểm": e["timestamp"].isoformat(),
                                                       "Loại": e["event_type"],
                                                       "Dữ liệu": json.dumps(e["data"],ensure_ascii=False)} for e in events]),
                                         use_container_width=True, hide_index=True)
        except (sqlite3.Error, OSError, FileNotFoundError) as exc:
            st.error(f"Không đọc được database: {exc}")

    with c:
        st.subheader("ROC-AUC / Confusion Matrix cho dữ liệu nhãn v5")
        st.caption("Tải CSV đã được gán nhãn, có user_id, decision_time, nhãn 0/1/Unknown và các đặc trưng số chỉ lấy từ quá khứ. Phép thử là baseline tách người dùng, không phải model PCBM đang triển khai.")
        upload = st.file_uploader("Chọn CSV nhãn v5", type=["csv"], key="label_v5_csv")
        if upload:
            if st.button("Đánh giá trên người dùng độc lập", key="label_v5_evaluate"):
                try:
                    from huan_luyen_pcbm.danh_gia_doc_lap_v5 import evaluate, LABELS
                    df = pd.read_csv(io.BytesIO(upload.getvalue()))
                    if not {"user_id", "decision_time"}.issubset(df.columns):
                        st.error("CSV cần có cột user_id và decision_time.")
                    else:
                        # Prevent target/future leakage: only explicitly named past/history
                        # numeric features are allowed in this optional baseline test.
                        allowed = {"user_id", "decision_time", *LABELS}
                        allowed.update(col for col in df.columns if col.startswith(("past_", "hist_")))
                        clean = df[[col for col in df.columns if col in allowed]].copy()
                        if not any(col.startswith(("past_", "hist_")) for col in clean.columns):
                            st.error("Chưa có feature hợp lệ: đặt tiền tố past_ hoặc hist_ cho đặc trưng được tính trước thời điểm dự đoán.")
                            st.stop()
                        report = {target: evaluate(clean, target) if target in clean.columns else
                                  {"status": "not_evaluable", "reason": "missing_target"} for target in LABELS}
                        for label, report_item in report.items():
                            st.markdown(f"**{label}**")
                            if report_item.get("status") != "evaluated":
                                st.info(f"Chưa thể đánh giá: {report_item.get('reason', 'không rõ')}.")
                            else:
                                v1, v2, v3 = st.columns(3)
                                v1.metric("ROC-AUC", f"{report_item['roc_auc']:.3f}")
                                v2.metric("PR-AUC", f"{report_item['pr_auc']:.3f}")
                                v3.metric("Mẫu kiểm thử", report_item["test_rows"])
                                st.dataframe(pd.DataFrame(report_item["confusion_matrix_TN_FP_FN_TP"],
                                                           index=["Thực tế 0","Thực tế 1"],
                                                           columns=["Dự đoán 0","Dự đoán 1"]), use_container_width=True)
                        st.download_button("Tải báo cáo đánh giá JSON",
                                           json.dumps({"schema": "v5-web-evaluation-baseline", "targets": report}, ensure_ascii=False, indent=2),
                                           file_name="pcbm_label_v5_web_report.json", mime="application/json")
                except (ValueError, KeyError, ImportError, TypeError) as exc:
                    st.error(f"Không thể đánh giá CSV: {exc}")
        else:
            st.info("Chưa có CSV nhãn v5. Hai tab đầu vẫn kiểm thử được ngay, không cần chuẩn bị CSV.")
    with d:
        from cau_hinh import DB_PATH
        st.info("Để huấn luyện đồng thời ba mô hình và xem Confusion Matrix, vào tab 🧠 Huấn luyện mô hình → Huấn luyện 3 mục tiêu PCBM v5.")

    st.divider()
    st.caption("Thử nghiệm nhãn v5 KHÔNG chứng minh PCBM chẩn đoán ADHD hoặc cải thiện hành vi thực tế.")
