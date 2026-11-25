"""Streamlit PCBM training administrator.

This module intentionally works DIRECTLY with SQLite and local model files.
It does not call the Flask API. It is imported by ``giao_dien_quan_tri.py``.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from cau_hinh import DB_PATH, PCBM_COMPLETION_MODEL, PCBM_RECALL_MODEL
from huan_luyen_pcbm.huan_luyen_tu_csdl import (
    TRAINING_VERSION,
    dong_sang_su_kien,
    huan_luyen_tu_sqlite_dong,
)
from huan_luyen_pcbm.xay_dung_du_lieu import xay_dung_ban_ghi_hoc
from dich_vu.dich_vu_pcbm import DichVuPCBM
from pcbm_playground_y_kien import hien_thi_y_kien_playground
from dich_vu.trich_xuat_thong_tin import trich_xuat_thong_tin_nhiem_vu


MODEL_META = Path(PCBM_RECALL_MODEL).parent / "pcbm_model_meta.json"
TRAINING_CSV = Path(__file__).resolve().parent / "data" / "pcbm_training_records.csv"


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _rows(sql, params=()):
    with _connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def _scalar(sql, params=(), default=0):
    with _connect() as con:
        row = con.execute(sql, params).fetchone()
    if not row:
        return default
    return row[0] if row[0] is not None else default


def _event_rows(user_filter=None):
    sql = "SELECT * FROM pcbm_events"
    params = []
    if user_filter:
        sql += " WHERE user_id=?"
        params.append(user_filter)
    sql += " ORDER BY user_id, created_at, id"
    with _connect() as con:
        return con.execute(sql, params).fetchall()


@st.cache_data(show_spinner=False, ttl=30)
def _build_training_df(db_mtime: float, db_size: int):
    # db_mtime/db_size are cache keys; content is read directly from SQLite.
    rows = _event_rows()
    events = dong_sang_su_kien(rows)
    return xay_dung_ban_ghi_hoc(events)


def _training_df(refresh=False):
    p = Path(DB_PATH)
    if refresh:
        _build_training_df.clear()
    stat = p.stat() if p.exists() else None
    return _build_training_df(
        stat.st_mtime if stat else 0.0,
        stat.st_size if stat else 0,
    )


def _load_bundle(path):
    p = Path(path)
    if not p.exists():
        return None
    obj = joblib.load(p)
    if not isinstance(obj, dict) or "pipeline" not in obj:
        raise RuntimeError(f"Tệp mô hình không đúng định dạng bundle: {p}")
    return obj


def _safe_load_bundle(path):
    """Load model without blocking the admin UI when binary pickle is incompatible.

    Joblib/pickle files can be incompatible across NumPy/scikit-learn versions.
    In that case the PCBM training page must still open and allow a local retrain,
    which will overwrite the old binaries with files compatible with this machine.
    """
    p = Path(path)
    if not p.exists():
        return None, None
    try:
        return _load_bundle(p), None
    except Exception as exc:
        return None, exc


def _show_model_load_warning(label, err):
    if err is None:
        return
    msg = str(err)
    incompatible = (
        "BitGenerator" in msg
        or "numpy.random" in msg
        or "scikit-learn" in msg.lower()
        or "sklearn" in msg.lower()
        or "pickle" in msg.lower()
    )
    if incompatible:
        st.warning(
            f"{label}: tệp model hiện tại không tương thích với phiên bản NumPy/scikit-learn "
            "trên máy này. Dữ liệu SQLite vẫn dùng bình thường. Hãy tick xác nhận và bấm "
            "'Train PCBM từ SQLite' để tạo lại model tương thích ngay trên máy này."
        )
    else:
        st.warning(f"{label}: chưa đọc được model hiện tại: {err}")


def _prob_class_1(bundle, X):
    pipe = bundle["pipeline"]
    probs = pipe.predict_proba(X)
    classes = list(pipe.named_steps["model"].classes_)
    if 1 not in classes:
        return np.zeros(len(X), dtype=float)
    return np.asarray(probs[:, classes.index(1)], dtype=float)


def _metric_value(value):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _save_training_run(meta):
    metrics = {
        "recall": meta.get("recall_model", {}),
        "completion_30m": meta.get("completion_model", {}),
    }
    with _connect() as con:
        cur = con.execute(
            """INSERT INTO pcbm_training_runs(
                source, event_count, record_count, user_count,
                recall_rows, completion_rows, metrics_json,
                recall_model_path, completion_model_path, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                meta.get("source", "sqlite:pcbm_events"),
                int(meta.get("events", 0)),
                int(meta.get("records", 0)),
                int(meta.get("users", 0)),
                int((meta.get("recall_model") or {}).get("training_rows", 0)),
                int((meta.get("completion_model") or {}).get("training_rows", 0)),
                json.dumps(metrics, ensure_ascii=False),
                (meta.get("recall_model") or {}).get("path"),
                (meta.get("completion_model") or {}).get("path"),
                meta.get("trained_at") or datetime.now().isoformat(timespec="seconds"),
            ),
        )
        con.commit()
        return cur.lastrowid


def _normalise_event(obj, line_no):
    if not isinstance(obj, dict):
        raise ValueError(f"Dòng {line_no}: mỗi dòng phải là JSON object")
    user_id = str(obj.get("user_id") or "local_user")
    task_id = obj.get("task_id")
    occurrence_id = obj.get("occurrence_id")
    event_type = str(obj.get("event_type") or "").upper().strip()
    ts = obj.get("timestamp") or obj.get("created_at")
    if not event_type or not ts:
        raise ValueError(f"Dòng {line_no}: thiếu event_type hoặc timestamp/created_at")
    # Validate timestamp while preserving text format.
    pd.Timestamp(ts)
    data = obj.get("data")
    if data is None:
        data = obj.get("data_json", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {"raw": data}
    if not isinstance(data, dict):
        data = {"value": data}
    return (
        user_id,
        None if task_id is None else str(task_id),
        None if occurrence_id is None else str(occurrence_id),
        event_type,
        json.dumps(data, ensure_ascii=False, default=str),
        str(ts),
    )


def _import_jsonl(raw: bytes, mode: str):
    parsed = []
    errors = []
    for i, line in enumerate(io.BytesIO(raw), 1):
        line = line.decode("utf-8-sig").strip()
        if not line:
            continue
        try:
            parsed.append(_normalise_event(json.loads(line), i))
        except Exception as e:
            errors.append(str(e))
            if len(errors) >= 20:
                break
    if errors:
        raise RuntimeError("\n".join(errors))
    if not parsed:
        raise RuntimeError("Không tìm thấy sự kiện hợp lệ trong file JSONL.")

    with _connect() as con:
        if mode == "replace_test":
            con.execute("DELETE FROM pcbm_events WHERE user_id LIKE 'test_%'")
        elif mode == "replace_all":
            con.execute("DELETE FROM pcbm_events")
            con.execute("DELETE FROM pcbm_predictions")
        con.executemany(
            """INSERT INTO pcbm_events(
                user_id,task_id,occurrence_id,event_type,data_json,created_at
            ) VALUES(?,?,?,?,?,?)""",
            parsed,
        )
        con.commit()
    _build_training_df.clear()
    return len(parsed)


def _show_model_summary(title, bundle):
    """Hiển thị ngắn gọn model đang triển khai, không dùng dãy metric card."""
    st.markdown(f"#### {title}")
    if not bundle:
        st.warning("Chưa có tệp mô hình.")
        return
    st.markdown(f"**Mô hình đang triển khai:** `{bundle.get('model_name', 'N/A')}`")
    st.caption(f"Huấn luyện lúc: {bundle.get('trained_at', 'N/A')}")


def _show_leaderboard(title, bundle):
    """Hiển thị bảng đánh giá 4 mô hình theo bộ chỉ số của báo cáo PCBM."""
    if not bundle:
        return
    ev = bundle.get("evaluation") or {}
    board = ev.get("leaderboard") or []
    if not board:
        return

    selected = ev.get("selected_model") or bundle.get("model_name")
    rows = []
    for item in board:
        if not item.get("available", False):
            rows.append({
                "Model": item.get("model", "N/A"),
                "ROC-AUC": None,
                "Std": None,
                "PR-AUC": None,
                "Recall": None,
                "Specificity": None,
                "F1": None,
                "Balanced Acc.": None,
                "Selected": "Không đủ fold hợp lệ",
            })
            continue
        rows.append({
            "Model": item.get("model", "N/A"),
            "ROC-AUC": item.get("roc_auc"),
            "Std": item.get("roc_auc_std"),
            "PR-AUC": item.get("pr_auc"),
            "Recall": item.get("recall"),
            "Specificity": item.get("specificity"),
            "F1": item.get("f1"),
            "Balanced Acc.": item.get("balanced_accuracy"),
            "Selected": "✅ Selected" if item.get("model") == selected else "",
        })

    board_df = pd.DataFrame(rows)
    numeric_cols = ["ROC-AUC", "Std", "PR-AUC", "Recall", "Specificity", "F1", "Balanced Acc."]
    for c in numeric_cols:
        if c in board_df.columns:
            board_df[c] = pd.to_numeric(board_df[c], errors="coerce").round(3)

    st.markdown(f"##### {title}")
    st.caption(
        "So sánh 4 mô hình ứng viên. Std là độ lệch chuẩn ROC-AUC giữa các fold walk-forward; "
        "ưu tiên PR-AUC, sau đó Balanced Accuracy và F1 để chọn model."
    )
    st.dataframe(board_df, use_container_width=True, hide_index=True)


def _show_confusion_matrix(title, bundle):
    """Matrix từ walk-forward OOF của model được chọn, KHÔNG phải phép xác thực lâm sàng."""
    if not bundle:
        return
    ev=bundle.get("evaluation") or {}
    cm=ev.get("confusion_matrix")
    if not ev.get("available") or not isinstance(cm,list) or len(cm)!=2 or any(len(r)!=2 for r in cm):
        st.info(f"{title}: Chưa có confusion matrix hợp lệ. Cần huấn luyện với đủ fold có nhãn.")
        return
    tn,fp=cm[0]
    fn,tp=cm[1]
    st.markdown(f"##### Confusion matrix — {title}")
    st.caption("Tổng hợp các dự đoán ngoài tập train của từng fold walk-forward theo thời gian; "
               "không phải bộ test độc lập và không đánh giá trực tiếp quyết định Level 0/1/2.")
    table=pd.DataFrame([[int(tn),int(fp)],[int(fn),int(tp)]],
                       index=["Thực tế: 0", "Thực tế: 1"],
                       columns=["Dự đoán: 0", "Dự đoán: 1"])
    st.dataframe(table, use_container_width=False)
    st.caption(f"TN={int(tn)} (đúng âm) · FP={int(fp)} (báo dương sai) · "
               f"FN={int(fn)} (bỏ sót dương) · TP={int(tp)} (đúng dương). "
               f"Recall={_metric_value(ev.get('recall'))}, "
               f"Precision={_metric_value(ev.get('precision'))}, "
               f"Balanced Accuracy={_metric_value(ev.get('balanced_accuracy'))}.")
    st.info("Nhãn 1 Recall = phản hồi nhớ đúng sau generic cue (≤2 phút). "
            "Nhãn 1 Completion = hoàn thành trong ≤30 phút sau reminder. "
            "Mức hỗ trợ được bộ điều phối đề xuất theo quy tắc và có sự đồng thuận người dùng; "
            "confusion matrix không phải công thức suy ra Level.")


def _show_feedback_training_info():
    st.markdown("##### Ý kiến người dùng trong pipeline")
    st.caption("Feedback được lưu qua SUPPORT_ACCEPTED / REJECTED / DEFERRED / "
               "MORE_REQUESTED / LESS_REQUESTED. Chỉ phản hồi có timestamp trước quyết định mới "
               "được biến thành đặc trưng; không đổi nhãn Recall/Completion.")
    try:
        rows=_rows("SELECT event_type, COUNT(*) AS n FROM pcbm_events "
                   "WHERE event_type IN ('SUPPORT_ACCEPTED','SUPPORT_REJECTED',"
                   "'SUPPORT_DEFERRED','SUPPORT_MORE_REQUESTED','SUPPORT_LESS_REQUESTED') "
                   "AND user_id NOT LIKE 'DEMO%' GROUP BY event_type ORDER BY event_type")
        count=sum(int(r['n']) for r in rows)
        st.metric("Phản hồi đã ghi nhận trong SQLite (không tính DEMO)", count)
        if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        df=_training_df()
        if not df.empty and 'user_feedback_count_30d' in df:
            with_feedback=int((df['user_feedback_count_30d'].fillna(0)>0).sum())
            st.caption(f"Training records có lịch sử phản hồi trước thời điểm dự đoán: {with_feedback}/{len(df)}. "
                       "Cần nhấn Train PCBM từ SQLite để huấn luyện lại mô hình và kiểm chứng kết quả.")
        st.warning("Phản hồi là yếu tố đầu vào, KHÔNG phải trọng số tùy ý hay nhãn đúng/sai. "
                   "Nếu số lượng phản hồi ít hoặc tập trung vào vài người dùng, chưa thể kết luận "
                   "chúng làm mô hình tốt hơn; cần so sánh ablation (có/không feedback) "
                   "và test độc lập theo người/thời gian.")
    except Exception as e:
        st.warning(f"Chưa đọc được thống kê phản hồi: {e}")


def _batch_test(bundle, df, target):
    work = df[df[target].notna()].copy()
    if work.empty:
        return None, None
    cols = bundle.get("feature_columns") or []
    missing = [c for c in cols if c not in work.columns]
    if missing:
        raise RuntimeError(f"Training records thiếu đặc trưng: {', '.join(missing[:10])}")
    X = work[cols]
    y = work[target].astype(int).to_numpy()
    pred = bundle["pipeline"].predict(X).astype(int)
    prob = _prob_class_1(bundle, X)
    metrics = {
        "rows": int(len(y)),
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y, prob)) if len(np.unique(y)) > 1 else None,
        "roc_auc": float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else None,
        "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
    }
    out = work[[c for c in ["user_id", "task_id", "occurrence_id", "decision_time", target] if c in work.columns]].copy()
    out["prediction"] = pred
    out["probability_class_1"] = prob
    return metrics, out



def _fmt_pct_playground(v):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return str(v)


def _fmt_value_playground(v, suffix=""):
    if v is None:
        return "N/A"
    try:
        x = float(v)
        if x.is_integer():
            return f"{int(x)}{suffix}"
        return f"{x:.1f}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def _level_label(level):
    try:
        level = int(level)
    except Exception:
        return "N/A"
    return {
        0: "Level 0 · Quan sát / chưa nhắc",
        1: "Level 1 · Gợi ý nhẹ",
        2: "Level 2 · Nhắc rõ nhiệm vụ",
    }.get(level, f"Level {level}")


def _render_playground_result(result, compact=False):
    """Render một kết quả PCBM Playground theo dạng card dễ demo."""
    profile = result.get("profile") or {}
    pred = result.get("prediction") or {}
    uid = result.get("user_id", "N/A")

    st.markdown(f"### 👤 {uid}")
    recall = pred.get("recall_percent")
    completion = pred.get("completion_30m_percent")
    base_level = pred.get("base_prompt_level")
    rec_level = pred.get("recommended_prompt_level")

    a, b = st.columns(2)
    a.metric("P(Recall)", _fmt_pct_playground(recall))
    b.metric("P(Completion ≤30m)", _fmt_pct_playground(completion))

    if recall is not None:
        st.progress(max(0.0, min(float(recall) / 100.0, 1.0)), text=f"Khả năng tự nhớ: {_fmt_pct_playground(recall)}")
    if completion is not None and not compact:
        st.progress(max(0.0, min(float(completion) / 100.0, 1.0)), text=f"Khả năng hoàn thành ≤30 phút: {_fmt_pct_playground(completion)}")

    c1, c2 = st.columns(2)
    c1.metric("Mức hiện tại", f"Level {base_level}")
    delta = None
    try:
        d = int(rec_level) - int(base_level)
        if d > 0:
            delta = f"+{d} mức"
        elif d < 0:
            delta = f"{d} mức"
        else:
            delta = "Giữ nguyên"
    except Exception:
        pass
    c2.metric("PCBM đề xuất", f"Level {rec_level}", delta=delta, delta_color="inverse")
    st.caption(_level_label(rec_level))

    reason = pred.get("reason_vi") or pred.get("reason_code") or ""
    if rec_level is not None and base_level is not None:
        if int(rec_level) < int(base_level):
            st.success(f"⬇️ {reason}")
        elif int(rec_level) > int(base_level):
            st.warning(f"⬆️ {reason}")
        else:
            st.info(f"➡️ {reason}")

    profile_rows = [
        ("Số sự kiện", profile.get("event_count")),
        ("Lịch sử", _fmt_value_playground(profile.get("history_days"), " ngày")),
        ("Recall 7 ngày", _fmt_pct_playground(profile.get("recall_rate_7d"))),
        ("Completion 7 ngày", _fmt_pct_playground(profile.get("completion_rate_7d"))),
        ("Snooze 7 ngày", _fmt_pct_playground(profile.get("snooze_rate_7d"))),
        ("Forget 7 ngày", _fmt_pct_playground(profile.get("forget_rate_7d"))),
        ("Độ trễ bắt đầu TB", _fmt_value_playground(profile.get("avg_start_delay_7d"), " phút")),
        ("Recall streak +", profile.get("recall_success_streak", 0)),
        ("Recall streak -", profile.get("recall_failure_streak", 0)),
    ]
    st.dataframe(pd.DataFrame(profile_rows, columns=["Chỉ số", "Giá trị"]), use_container_width=True, hide_index=True)

    if not compact:
        with st.expander("🔎 Đặc trưng model đã sử dụng"):
            feats = (result.get("features") or {}).get("recall") or {}
            if feats:
                st.dataframe(pd.DataFrame([feats]), use_container_width=True, hide_index=True)
            else:
                st.info("Không có đặc trưng để hiển thị.")


def _render_compare_summary(results):
    rows = []
    for r in results:
        p = r.get("profile") or {}
        y = r.get("prediction") or {}
        rows.append({
            "User": r.get("user_id"),
            "Recall 7d": _fmt_pct_playground(p.get("recall_rate_7d")),
            "Completion 7d": _fmt_pct_playground(p.get("completion_rate_7d")),
            "Snooze 7d": _fmt_pct_playground(p.get("snooze_rate_7d")),
            "Forget 7d": _fmt_pct_playground(p.get("forget_rate_7d")),
            "Start delay": _fmt_value_playground(p.get("avg_start_delay_7d"), " phút"),
            "P(Recall)": _fmt_pct_playground(y.get("recall_percent")),
            "P(Completion)": _fmt_pct_playground(y.get("completion_30m_percent")),
            "Hiện tại": f"L{y.get('base_prompt_level')}",
            "Đề xuất": f"L{y.get('recommended_prompt_level')}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def hien_thi_quan_tri_huan_luyen_pcbm():
    st.markdown(
        '<div class="os-hero"><h2>🧪 Quản trị huấn luyện PCBM</h2>'
        '<p>Quản lý dữ liệu, huấn luyện và kiểm thử mô hình trực tiếp trên SQLite — không đi qua Flask API.</p></div>',
        unsafe_allow_html=True,
    )
    st.info(f"Kết nối trực tiếp: `{DB_PATH}` · Huấn luyện và kiểm thử trực tiếp, không qua Flask API.")

    tab_data, tab_train, tab_test, tab_playground, tab_history = st.tabs([
        "🗃️ Dữ liệu huấn luyện",
        "🧠 Huấn luyện mô hình",
        "🧪 Test mô hình",
        "🎯 PCBM Playground",
        "📜 Lịch sử huấn luyện",
    ])

    with tab_data:
        st.subheader("Dữ liệu sự kiện trong SQLite")
        users = [r["user_id"] for r in _rows("SELECT DISTINCT user_id FROM pcbm_events ORDER BY user_id")]
        a, b, c = st.columns([2, 2, 1])
        user_choice = a.selectbox("Lọc người dùng", ["Tất cả"] + users, key="pcbm_db_user_filter")
        event_types = [r["event_type"] for r in _rows("SELECT DISTINCT event_type FROM pcbm_events ORDER BY event_type")]
        event_choice = b.selectbox("Loại sự kiện", ["Tất cả"] + event_types, key="pcbm_db_event_filter")
        limit = int(c.number_input("Số dòng", min_value=20, max_value=5000, value=200, step=20))
        where, params = [], []
        if user_choice != "Tất cả":
            where.append("user_id=?")
            params.append(user_choice)
        if event_choice != "Tất cả":
            where.append("event_type=?")
            params.append(event_choice)
        sql = "SELECT id,user_id,task_id,occurrence_id,event_type,data_json,created_at FROM pcbm_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC,id DESC LIMIT ?"
        params.append(limit)
        ev_rows = _rows(sql, tuple(params))
        if ev_rows:
            st.dataframe(pd.DataFrame(ev_rows), use_container_width=True, hide_index=True)
        else:
            st.warning("Không có sự kiện phù hợp bộ lọc.")

        st.divider()
        st.subheader("Import JSONL trực tiếp vào SQLite")
        st.caption("Định dạng hỗ trợ: mỗi dòng có user_id, task_id, occurrence_id, timestamp/created_at, event_type và data.")
        uploaded = st.file_uploader("Chọn file dữ liệu huấn luyện .jsonl", type=["jsonl", "txt"], key="pcbm_training_upload")
        mode_label = st.radio(
            "Cách nạp",
            [
                "Thêm vào dữ liệu hiện có",
                "Thay bộ test_* (giữ dữ liệu người dùng thật)",
                "Thay toàn bộ pcbm_events",
            ],
            key="pcbm_import_mode",
        )
        mode = {
            "Thêm vào dữ liệu hiện có": "append",
            "Thay bộ test_* (giữ dữ liệu người dùng thật)": "replace_test",
            "Thay toàn bộ pcbm_events": "replace_all",
        }[mode_label]
        allow = True
        if mode == "replace_all":
            allow = st.checkbox("Tôi xác nhận xóa toàn bộ pcbm_events hiện tại trước khi import.")
        if st.button("📥 Import vào SQLite", type="primary", disabled=(uploaded is None or not allow), key="pcbm_direct_import"):
            try:
                raw = uploaded.getvalue()
                digest = hashlib.sha256(raw).hexdigest()
                with st.spinner("Đang ghi trực tiếp vào SQLite..."):
                    n = _import_jsonl(raw, mode)
                st.success(f"Đã import {n:,} sự kiện. SHA-256: {digest[:16]}…")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.subheader("Training records sau feature/label engineering")
        if st.button("🔄 Tạo/làm mới training records từ SQLite", key="pcbm_refresh_records"):
            _build_training_df.clear()
        try:
            with st.spinner("Đang tạo training records từ lịch sử sự kiện..."):
                df = _training_df()
            if df.empty:
                st.warning("Chưa tạo được training record.")
            else:
                recall_n = int(df["y_recall_success"].notna().sum()) if "y_recall_success" in df else 0
                comp_n = int(df["y_complete_within_30m"].notna().sum()) if "y_complete_within_30m" in df else 0
                generic_n = int((df.get("reminder_type", pd.Series([], dtype=str)).astype(str).str.lower() == "generic").sum())
                x1, x2, x3, x4 = st.columns(4)
                x1.metric("Training records", f"{len(df):,}")
                x2.metric("Generic cues", f"{generic_n:,}")
                x3.metric("Recall labels", f"{recall_n:,}")
                x4.metric("Completion labels", f"{comp_n:,}")
                show_n = st.slider("Số training records xem trước", 20, min(1000, len(df)), min(200, len(df)), step=20)
                st.dataframe(df.tail(show_n), use_container_width=True, hide_index=True)
                csv = df.to_csv(index=False).encode("utf-8-sig")
                st.download_button("⬇️ Tải training records CSV", csv, "pcbm_training_records.csv", "text/csv")
        except Exception as e:
            st.error(f"Không tạo được training records: {e}")

    with tab_train:
        st.subheader("Huấn luyện PCBM v5 – Recall, Completion 30m và ITI (16.993 sự kiện DEMO)")
        st.caption("Giữ nguyên 4 thuật toán và walk-forward của v4. Một nút chạy đủ 3 mục tiêu; "
                   "nếu thiếu nhãn xác minh, mô hình tương ứng được TRÌNH DIỄN bằng SQLite MÔ PHỎNG riêng.")
        st.warning("Dữ liệu mô phỏng chỉ phục vụ trình diễn pipeline, KHÔNG chứng minh hiệu quả trên học sinh thật.")

        # Đặt nút ngay trước bảng kết quả; không buộc tìm bảng ở đầu trang
        if st.button("🚀 Tạo 16.993 sự kiện DEMO và huấn luyện 3 mô hình PCBM", type="primary",
                     key="pcbm_v56_train_3", use_container_width=True):
            try:
                from huan_luyen_pcbm.pcbm_demo_v5 import tao_sqlite_demo
                demo_db = Path(__file__).resolve().parent / "data" / "pcbm_v5_DEMO_ONLY.db"
                demo_dir = Path(PCBM_RECALL_MODEL).parent / "v5_demo_models"
                with st.spinner("Tạo SQLite mô phỏng; train 3 mục tiêu × 4 thuật toán; đánh giá walk-forward..."):
                    n = tao_sqlite_demo(demo_db, n_users=40, n_tasks=64, target_events=16993)
                    with sqlite3.connect(demo_db) as con:
                        con.row_factory = sqlite3.Row
                        demo_rows = con.execute("SELECT * FROM pcbm_events ORDER BY user_id, created_at, id").fetchall()
                    demo_meta = huan_luyen_tu_sqlite_dong(demo_rows, demo_dir)
                    missing_demo = [k for k in ("recall_model", "completion_model", "iti_model")
                                    if not (demo_meta.get(k) or {}).get("available")]
                    if missing_demo:
                        raise RuntimeError("Dữ liệu DEMO không train đủ 3 mục tiêu: " + ", ".join(missing_demo))
                    st.session_state["pcbm_v56_demo_ready"] = True
                    st.session_state["pcbm_v56_demo_info"] = {"events": n, "meta": demo_meta}
                    # Dữ liệu hiện có được train song song, không ảnh hưởng model đang vận hành
                    try:
                        real_rows = _event_rows()
                        real_dir = Path(PCBM_RECALL_MODEL).parent / "v5_label_models"
                        st.session_state["pcbm_v56_real_meta"] = (
                            huan_luyen_tu_sqlite_dong(real_rows, real_dir) if real_rows else None)
                        st.session_state["pcbm_v56_real_error"] = None
                    except Exception as real_exc:
                        st.session_state["pcbm_v56_real_meta"] = None
                        st.session_state["pcbm_v56_real_error"] = str(real_exc)
                st.success(f"Đã tạo {n:,} sự kiện DEMO và huấn luyện đủ 3 mục tiêu. Bảng kết quả nằm ngay bên dưới.")
            except Exception as exc:
                st.session_state["pcbm_v56_demo_ready"] = False
                st.error(f"Lần huấn luyện chưa hoàn thành: {exc}")

        demo_dir = Path(PCBM_RECALL_MODEL).parent / "v5_demo_models"
        real_dir = Path(PCBM_RECALL_MODEL).parent / "v5_label_models"
        targets = [
            ("Recall – nhớ sau generic cue", "pcbm_recall_v5.joblib"),
            ("Completion 30m", "pcbm_completion_v5.joblib"),
            ("ITI – chủ động bắt đầu trước lời nhắc", "pcbm_iti_v5.joblib"),
        ]
        # Chỉ hiện kết quả nếu đã nhấn Train trong phiên này. Tránh đọc model demo cũ
        # khiến người xem nhầm với kết quả của lần chạy hiện hành.
        if st.session_state.get("pcbm_v56_demo_ready"):
            st.markdown("### Kết quả huấn luyện – 3 mục tiêu")
            st.caption("Mỗi mục tiêu hiển thị một bảng so sánh bốn thuật toán và Confusion Matrix; "
                       "nhãn nguồn dữ liệu được ghi ngay trong tiêu đề.")
            real_meta = st.session_state.get("pcbm_v56_real_meta") or {}
            mapping = ("recall_model", "completion_model", "iti_model")
            for (name, filename), key in zip(targets, mapping):
                real_ok = bool((real_meta.get(key) or {}).get("available"))
                candidate = real_dir / filename if real_ok else demo_dir / filename
                bundle, err = _safe_load_bundle(candidate)
                source_name = "SQLITE HIỆN TẠI" if real_ok else "DEMO MÔ PHỎNG"
                st.markdown(f"#### {name} — {source_name}")
                if not real_ok:
                    reason = (real_meta.get(key) or {}).get("reason", "chưa có dữ liệu thực đủ điều kiện")
                    st.caption("Sử dụng bộ dữ liệu tổng hợp tách riêng để trình diễn vì SQLite hiện tại: "
                               + str(reason) + ". KHÔNG phải số liệu thực nghiệm.")
                if bundle:
                    st.markdown(f"**Thuật toán được chọn:** `{bundle.get('model_name','N/A')}`")
                    _show_leaderboard("So sánh 4 mô hình – " + name, bundle)
                    _show_confusion_matrix(name + " (" + source_name + ")", bundle)
                else:
                    st.error(f"Không đọc được kết quả {name}: {err}")
                st.divider()
            with st.expander("Chi tiết lần train và nguồn dữ liệu"):
                st.json({"real": real_meta,
                         "demo": (st.session_state.get("pcbm_v56_demo_info") or {}).get("meta"),
                         "real_error": st.session_state.get("pcbm_v56_real_error")})
        else:
            st.info("Nhấn nút Train phía trên để tạo dataset DEMO và hiện ngay đủ 3 bảng so sánh + 3 Confusion Matrix.")

        with st.expander("📝 Thu thập bằng chứng thật cho ITI / Completion (tùy chọn)"):
            from pcbm_thu_thap_bang_chung import hien_thi_thu_thap_bang_chung
            hien_thi_thu_thap_bang_chung(DB_PATH)

    with tab_test:
        st.subheader("Test model trực tiếp")
        model_name = st.radio("Mô hình", ["Recall success", "Complete within 30m"], horizontal=True)
        if model_name == "Recall success":
            model_path = PCBM_RECALL_MODEL
            target = "y_recall_success"
        else:
            model_path = PCBM_COMPLETION_MODEL
            target = "y_complete_within_30m"
        try:
            bundle, load_error = _safe_load_bundle(model_path)
            if load_error is not None:
                _show_model_load_warning("Model test", load_error)
                st.info("Sau khi train lại PCBM trên máy này, tab Test mô hình sẽ sử dụng model mới ngay.")
            elif not bundle:
                st.warning("Chưa có model để test.")
            else:
                _show_model_summary("Model đang test", bundle)
                df = _training_df()
                work = df[df[target].notna()].copy() if target in df else pd.DataFrame()
                if work.empty:
                    st.warning("Không có bản ghi có nhãn tương ứng để test.")
                else:
                    test_mode = st.radio("Kiểu test", ["Một bản ghi", "Batch trên dữ liệu hiện tại"], horizontal=True)
                    if test_mode == "Một bản ghi":
                        sample_count = min(500, len(work))
                        candidates = work.tail(sample_count).reset_index(drop=True)
                        labels = [
                            f"#{i} · {r.get('user_id','')} · {r.get('occurrence_id','')} · {r.get('decision_time','')}"
                            for i, r in candidates.iterrows()
                        ]
                        idx = st.selectbox("Chọn training record", range(len(labels)), format_func=lambda i: labels[i])
                        row = candidates.iloc[int(idx)]
                        cols = bundle.get("feature_columns") or []
                        X = pd.DataFrame([{c: row.get(c) for c in cols}], columns=cols)
                        pred = int(bundle["pipeline"].predict(X)[0])
                        prob = float(_prob_class_1(bundle, X)[0])
                        actual = int(row[target])
                        a, b, c = st.columns(3)
                        a.metric("Xác suất class 1", f"{prob:.3f}")
                        b.metric("Dự đoán", pred)
                        c.metric("Nhãn thực", actual)
                        if pred == actual:
                            st.success("Dự đoán đúng trên bản ghi này.")
                        else:
                            st.warning("Dự đoán khác nhãn thực trên bản ghi này.")
                        with st.expander("Đặc trưng đầu vào"):
                            st.dataframe(pd.DataFrame([X.iloc[0].to_dict()]), use_container_width=True, hide_index=True)
                    else:
                        max_rows = min(5000, len(work))
                        n = int(st.slider("Số bản ghi test gần nhất", 50, max_rows, min(1000, max_rows), step=50)) if max_rows >= 50 else max_rows
                        subset = work.tail(n).copy()
                        if st.button("▶️ Chạy batch test", type="primary"):
                            metrics, result_df = _batch_test(bundle, subset, target)
                            st.session_state["pcbm_batch_metrics"] = metrics
                            st.session_state["pcbm_batch_results"] = result_df
                        metrics = st.session_state.get("pcbm_batch_metrics")
                        result_df = st.session_state.get("pcbm_batch_results")
                        if metrics:
                            k1, k2, k3, k4, k5 = st.columns(5)
                            k1.metric("Accuracy", _metric_value(metrics.get("accuracy")))
                            k2.metric("Balanced Acc.", _metric_value(metrics.get("balanced_accuracy")))
                            k3.metric("Precision", _metric_value(metrics.get("precision")))
                            k4.metric("Recall", _metric_value(metrics.get("recall")))
                            k5.metric("F1", _metric_value(metrics.get("f1")))
                            st.caption(f"PR-AUC: {_metric_value(metrics.get('pr_auc'))} · ROC-AUC: {_metric_value(metrics.get('roc_auc'))} · rows: {metrics.get('rows', 0):,}")
                            cm = metrics.get("confusion_matrix") or [[0, 0], [0, 0]]
                            st.dataframe(pd.DataFrame(cm, index=["Actual 0", "Actual 1"], columns=["Pred 0", "Pred 1"]), use_container_width=False)
                        if isinstance(result_df, pd.DataFrame) and not result_df.empty:
                            st.dataframe(result_df.tail(500), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Không test được model: {e}")

    with tab_playground:
        st.subheader("🎯 PCBM Playground")
        st.caption(
            "Test PCBM theo từng user hoặc so sánh 3 user trên cùng một tình huống. "
            "Playground chỉ chạy inference trong RAM, không ghi thêm event/prediction vào SQLite."
        )

        try:
            service = DichVuPCBM()
            user_rows = service.liet_ke_nguoi_dung(limit=500)
            user_ids = [str(r.get("user_id")) for r in user_rows if r.get("user_id")]
        except Exception as e:
            st.error(f"Không khởi tạo được PCBM Playground: {e}")
            user_ids = []
            service = None

        if service and user_ids:
            mode_one, mode_three = st.tabs(["👤 Test 1 user", "👥 So sánh 3 user"])

            with st.container(border=True):
                st.markdown("#### 📝 Tình huống chung")

                scenario_presets = {
                    "📘 Làm bài Toán buổi tối":
                        "19h tối nay em cần làm bài Toán khoảng 30 phút",
                    "🇬🇧 Học tiếng Anh":
                        "20h tối nay em cần học từ vựng tiếng Anh khoảng 25 phút",
                    "🎒 Chuẩn bị cặp sách":
                        "21h tối nay em cần chuẩn bị sách vở và đồ dùng cho ngày mai khoảng 15 phút",
                    "🔄 Quay lại sau gián đoạn":
                        "Em đang làm bài nhưng vừa bị gián đoạn, hãy giúp em quay lại nhiệm vụ trong 20 phút tiếp theo",
                    "🧩 Bắt đầu nhiệm vụ khó":
                        "Em có một bài tập khó cần bắt đầu ngay bây giờ và dự kiến làm trong 45 phút",
                    "📑 Làm dự án dài":
                        "Tối nay em cần làm dự án nhóm khoảng 60 phút nhưng thường hay trì hoãn",
                    "🧹 Việc nhà":
                        "18h30 em cần dọn bàn học và sắp xếp đồ dùng khoảng 15 phút",
                    "⏰ Nhiệm vụ sắp đến hạn":
                        "Bài tập cần nộp vào sáng mai, tối nay em cần hoàn thành trong khoảng 40 phút",
                    "✍️ Tự nhập tình huống khác...": "",
                }

                preset_labels = list(scenario_presets.keys())
                if "pcbm_pg_preset" not in st.session_state:
                    st.session_state["pcbm_pg_preset"] = preset_labels[0]
                if "pcbm_pg_sentence" not in st.session_state:
                    st.session_state["pcbm_pg_sentence"] = scenario_presets[preset_labels[0]]

                def _pcbm_apply_preset():
                    label = st.session_state.get("pcbm_pg_preset")
                    text = scenario_presets.get(label, "")
                    if text:
                        st.session_state["pcbm_pg_sentence"] = text
                    elif label == "✍️ Tự nhập tình huống khác...":
                        st.session_state["pcbm_pg_sentence"] = ""

                st.selectbox(
                    "Tình huống gợi ý",
                    preset_labels,
                    key="pcbm_pg_preset",
                    on_change=_pcbm_apply_preset,
                    help="Chọn một tình huống mẫu; nội dung sẽ tự điền xuống ô bên dưới và vẫn có thể chỉnh sửa.",
                )
                scenario_text = st.text_area(
                    "Tình huống đang test",
                    key="pcbm_pg_sentence",
                    height=90,
                    placeholder="Ví dụ: 19h tối nay em cần làm bài Toán khoảng 30 phút",
                )
                parsed = trich_xuat_thong_tin_nhiem_vu(scenario_text or "")
                parsed_title = (parsed.get("title") or scenario_text or "Nhiệm vụ thử nghiệm").strip()
                parsed_minutes = int(parsed.get("estimated_minutes") or 30)

                s1, s2, s3, s4 = st.columns(4)
                estimated_minutes = int(s1.number_input(
                    "Thời lượng (phút)", min_value=1, max_value=480,
                    value=max(1, min(parsed_minutes, 480)), key="pcbm_pg_minutes"
                ))
                base_level = int(s2.selectbox(
                    "Mức hỗ trợ hiện tại", [0, 1, 2], index=1,
                    format_func=lambda x: _level_label(x), key="pcbm_pg_base_level"
                ))
                priority = int(s3.selectbox("Ưu tiên", [1, 2, 3], index=0, key="pcbm_pg_priority"))
                channel = s4.selectbox("Kênh", ["buddy", "oneband"], index=0, key="pcbm_pg_channel")
                anchor_history = st.checkbox(
                    "Neo thời điểm demo theo lịch sử gần nhất của từng user",
                    value=True,
                    help="Nên bật với dữ liệu mô phỏng để các feature 1/3/7 ngày không bị rỗng do dataset cũ.",
                    key="pcbm_pg_anchor_history",
                )
                st.caption(
                    f"Đã hiểu câu: **{parsed_title}** · thời lượng **{estimated_minutes} phút**"
                    + (f" · thời gian nhận diện **{parsed.get('scheduled_time')}**" if parsed.get("scheduled_time") else "")
                )

            with mode_one:
                default_one = "test_U036" if "test_U036" in user_ids else user_ids[0]
                uid = st.selectbox(
                    "Chọn user",
                    user_ids,
                    index=user_ids.index(default_one),
                    key="pcbm_pg_one_user",
                )
                if st.button("▶️ Chạy PCBM cho user này", type="primary", use_container_width=True, key="pcbm_pg_run_one"):
                    try:
                        t = service.thoi_diem_demo_theo_lich_su([uid]) if anchor_history else None
                        result = service.thu_nghiem_kich_ban(
                            uid, parsed_title, base_level, estimated_minutes,
                            priority, channel, t
                        )
                        st.session_state["pcbm_pg_one_result"] = result
                    except Exception as e:
                        st.error(f"Không chạy được Playground: {e}")
                result = st.session_state.get("pcbm_pg_one_result")
                if result:
                    _render_playground_result(result, compact=False)
                    hien_thi_y_kien_playground(result, prefix="pg_one")

            with mode_three:
                defaults = [x for x in ["test_U036", "test_U029", "test_U015"] if x in user_ids]
                for uid in user_ids:
                    if len(defaults) >= 3:
                        break
                    if uid not in defaults:
                        defaults.append(uid)
                c1, c2, c3 = st.columns(3)
                u1 = c1.selectbox("User A", user_ids, index=user_ids.index(defaults[0]), key="pcbm_pg_u1")
                u2 = c2.selectbox("User B", user_ids, index=user_ids.index(defaults[1]), key="pcbm_pg_u2")
                u3 = c3.selectbox("User C", user_ids, index=user_ids.index(defaults[2]), key="pcbm_pg_u3")
                selected = [u1, u2, u3]
                duplicate = len(set(selected)) != 3
                if duplicate:
                    st.warning("Hãy chọn 3 user khác nhau.")
                if st.button(
                    "🔬 So sánh 3 user trên cùng tình huống",
                    type="primary", use_container_width=True,
                    disabled=duplicate, key="pcbm_pg_compare3"
                ):
                    try:
                        # so_sanh_nguoi_dung() tự neo từng user vào lịch sử gần nhất nếu decision_time=None.
                        # Nếu bỏ neo lịch sử, truyền decision_time hiện tại qua thu_nghiem_kich_ban từng user.
                        if anchor_history:
                            results = service.so_sanh_nguoi_dung(
                                selected, parsed_title, base_level,
                                estimated_minutes, priority, channel, None
                            )
                        else:
                            results = [
                                service.thu_nghiem_kich_ban(
                                    uid, parsed_title, base_level, estimated_minutes,
                                    priority, channel, None
                                ) for uid in selected
                            ]
                        st.session_state["pcbm_pg_compare_results"] = results
                    except Exception as e:
                        st.error(f"Không so sánh được 3 user: {e}")

                results = st.session_state.get("pcbm_pg_compare_results")
                if results:
                    st.markdown("#### 📊 Tổng hợp 3 user")
                    _render_compare_summary(results)
                    cols = st.columns(3)
                    for col, result in zip(cols, results):
                        with col:
                            with st.container(border=True):
                                _render_playground_result(result, compact=True)
                    st.info(
                        "💡 Điểm demo: cùng một nhiệm vụ và cùng Level ban đầu, PCBM có thể đưa ra "
                        "khuyến nghị khác nhau vì lịch sử hành vi của mỗi user khác nhau."
                    )
                    st.markdown("#### 🗳️ Lấy ý kiến người dùng – so sánh 3 hồ sơ (DEMO)")
                    index = st.selectbox("Hồ sơ để hỏi ý kiến", range(len(results)),
                                         format_func=lambda i: str(results[i].get("user_id", i)),
                                         key="pg_three_feedback_profile")
                    hien_thi_y_kien_playground(results[index], prefix="pg_three")
        elif not user_ids:
            st.warning("Chưa có user trong bảng pcbm_events để chạy Playground.")

    with tab_history:
        st.subheader("Lịch sử huấn luyện trong database")
        runs = _rows("SELECT * FROM pcbm_training_runs ORDER BY id DESC LIMIT 100")
        if not runs:
            st.info("Chưa có lịch sử huấn luyện.")
        else:
            simple = []
            for r in runs:
                x = dict(r)
                try:
                    metrics = json.loads(x.pop("metrics_json", "{}") or "{}")
                except Exception:
                    metrics = {}
                recall_ev = ((metrics.get("recall") or {}).get("evaluation") or {})
                comp_ev = ((metrics.get("completion_30m") or {}).get("evaluation") or {})
                x["recall_model"] = (metrics.get("recall") or {}).get("model_name") or recall_ev.get("selected_model")
                x["recall_pr_auc"] = recall_ev.get("pr_auc")
                x["completion_model"] = (metrics.get("completion_30m") or {}).get("model_name") or comp_ev.get("selected_model")
                x["completion_pr_auc"] = comp_ev.get("pr_auc")
                simple.append(x)
            st.dataframe(pd.DataFrame(simple), use_container_width=True, hide_index=True)
            run_id = st.selectbox("Xem chi tiết training run", [r["id"] for r in runs])
            selected = next(r for r in runs if r["id"] == run_id)
            try:
                selected["metrics_json"] = json.loads(selected.get("metrics_json") or "{}")
            except Exception:
                pass
            st.json(selected)
