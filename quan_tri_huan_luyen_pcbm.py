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


def hien_thi_quan_tri_huan_luyen_pcbm():
    st.markdown(
        '<div class="os-hero"><h2>🧪 Quản trị huấn luyện PCBM</h2>'
        '<p>Quản lý dữ liệu, huấn luyện và kiểm thử mô hình trực tiếp trên SQLite — không đi qua Flask API.</p></div>',
        unsafe_allow_html=True,
    )
    st.info(f"Kết nối trực tiếp: `{DB_PATH}` · Huấn luyện và kiểm thử trực tiếp, không qua Flask API.")

    tab_data, tab_train, tab_test, tab_history = st.tabs([
        "🗃️ Dữ liệu huấn luyện",
        "🧠 Huấn luyện mô hình",
        "🧪 Test mô hình",
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
        st.subheader("Huấn luyện trực tiếp từ pcbm_events")
        st.warning("Nút này đọc SQLite, tạo feature/label, train model và ghi .joblib trực tiếp. Flask API không được gọi.")
        recall_bundle, recall_load_error = _safe_load_bundle(PCBM_RECALL_MODEL)
        completion_bundle, completion_load_error = _safe_load_bundle(PCBM_COMPLETION_MODEL)
        _show_model_load_warning("Recall", recall_load_error)
        _show_model_load_warning("Completion 30m", completion_load_error)
        _show_model_summary("Mô hình Recall hiện tại", recall_bundle)
        _show_leaderboard("So sánh 4 mô hình Recall", recall_bundle)
        _show_model_summary("Mô hình Completion 30m hiện tại", completion_bundle)
        _show_leaderboard("So sánh 4 mô hình Completion 30m", completion_bundle)

        if st.session_state.pop("pcbm_train_success", None):
            st.success("Huấn luyện PCBM thành công. Hai model đang triển khai và leaderboard đã được cập nhật.")

        confirm_train = st.checkbox("Tôi xác nhận ghi đè hai model hiện tại khi huấn luyện thành công.", key="pcbm_confirm_train")
        if st.button("🚀 Train PCBM từ SQLite", type="primary", disabled=not confirm_train, use_container_width=True):
            try:
                rows = _event_rows()
                with st.spinner("Đang chạy PCBM: feature engineering → labeling → walk-forward → so sánh 4 mô hình → chọn model → final fit..."):
                    meta = huan_luyen_tu_sqlite_dong(rows, Path(PCBM_RECALL_MODEL).parent)
                    run_id = _save_training_run(meta)
                    # Save an inspectable training-record snapshot next to the dataset.
                    df = _training_df(refresh=True)
                    TRAINING_CSV.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(TRAINING_CSV, index=False)
                st.session_state["pcbm_direct_train_meta"] = meta
                st.session_state["pcbm_train_success"] = True
                st.rerun()
            except Exception as e:
                st.error(f"Huấn luyện thất bại: {e}")

        meta = st.session_state.get("pcbm_direct_train_meta")
        if meta:
            with st.expander("Chi tiết kỹ thuật lần huấn luyện gần nhất"):
                st.json(meta)

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
