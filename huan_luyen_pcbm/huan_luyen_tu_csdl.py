from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, confusion_matrix, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from huan_luyen_pcbm.xay_dung_du_lieu import xay_dung_ban_ghi_hoc

DROP_COLUMNS = {
    "user_id", "occurrence_id", "decision_time", "feature_schema_version",
    "label_schema_version", "pipeline_version",
}
ALL_LABELS = {
    "y_recall_success", "y_started_within_10m", "y_start_delay_minutes",
    "y_complete_within_30m", "y_complete_within_60m",
    "y_completion_delay_minutes", "y_snooze", "y_forgot",
}


def dong_sang_su_kien(rows):
    events = []
    for r in rows:
        try:
            data = json.loads(r["data_json"] or "{}")
        except Exception:
            data = {}
        try:
            ts = pd.Timestamp(r["created_at"]).to_pydatetime()
        except Exception:
            continue
        events.append({
            "event_id": f"DB{r['id']}",
            "user_id": str(r["user_id"] or "local_user"),
            "task_id": str(r["task_id"] or ""),
            "occurrence_id": str(r["occurrence_id"] or ""),
            "timestamp": ts,
            "event_type": str(r["event_type"] or "").upper().strip(),
            "data": data,
        })
    events.sort(key=lambda x: (x["user_id"], x["timestamp"], x["event_id"]))
    return events


def _tao_quy_trinh(feature_cols, X):
    cat_cols = [c for c in feature_cols if X[c].dtype == "object"]
    num_cols = [c for c in feature_cols if c not in cat_cols]
    pre = ColumnTransformer([
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median"))]), num_cols),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), cat_cols),
    ])
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=10,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )
    return Pipeline([("preprocess", pre), ("model", model)])


def _danh_gia_theo_thoi_gian(work, feature_cols, target):
    work = work.sort_values("decision_time").reset_index(drop=True)
    if len(work) < 10:
        return {"available": False, "reason": "Không đủ dữ liệu để tách tập kiểm thử theo thời gian."}

    cut = max(1, int(len(work) * 0.8))
    if cut >= len(work):
        cut = len(work) - 1
    train = work.iloc[:cut]
    test = work.iloc[cut:]
    if train[target].nunique() < 2:
        return {"available": False, "reason": "Tập huấn luyện chỉ có một lớp."}

    X_train = train[feature_cols]
    y_train = train[target].astype(int)
    X_test = test[feature_cols]
    y_test = test[target].astype(int)

    pipe = _tao_quy_trinh(feature_cols, X_train)
    pipe.fit(X_train, y_train)
    pred = pipe.predict(X_test)

    metrics = {
        "available": True,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "accuracy": float(accuracy_score(y_test, pred)),
        "recall": float(recall_score(y_test, pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_test, pred, labels=[0, 1]).tolist(),
    }

    try:
        if y_test.nunique() > 1:
            proba = pipe.predict_proba(X_test)
            classes = list(pipe.named_steps["model"].classes_)
            if 1 in classes:
                metrics["roc_auc"] = float(roc_auc_score(y_test, proba[:, classes.index(1)]))
            else:
                metrics["roc_auc"] = None
        else:
            metrics["roc_auc"] = None
    except Exception:
        metrics["roc_auc"] = None
    return metrics


def _huan_luyen_cuoi(df, target, source):
    work = df[df[target].notna()].copy()
    if len(work) < 4:
        raise RuntimeError(f"Không đủ dữ liệu có nhãn cho {target}: {len(work)} bản ghi")
    if work[target].astype(int).nunique() < 2:
        raise RuntimeError(f"Nhãn {target} chỉ có một lớp, chưa thể huấn luyện mô hình phân loại.")

    feature_cols = [c for c in work.columns if c not in DROP_COLUMNS and c not in ALL_LABELS]
    X = work[feature_cols]
    y = work[target].astype(int)

    evaluation = _danh_gia_theo_thoi_gian(work, feature_cols, target)
    pipe = _tao_quy_trinh(feature_cols, X)
    pipe.fit(X, y)

    bundle = {
        "pipeline": pipe,
        "feature_columns": feature_cols,
        "target": target,
        "training_rows": int(len(work)),
        "positive_rate": float(y.mean()),
        "model_name": "RandomForestClassifier",
        "source": source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "evaluation": evaluation,
    }
    return bundle


def huan_luyen_tu_sqlite_dong(rows, model_dir: Path):
    events = dong_sang_su_kien(rows)
    if not events:
        raise RuntimeError("Bảng pcbm_events không có dữ liệu hợp lệ.")

    df = xay_dung_ban_ghi_hoc(events)
    if df.empty:
        raise RuntimeError("Không tạo được training record. Cần có REMINDER_SENT và các sự kiện kết quả tương ứng.")

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    source = "sqlite:pcbm_events"

    recall = _huan_luyen_cuoi(df, "y_recall_success", source)
    completion = _huan_luyen_cuoi(df, "y_complete_within_30m", source)

    recall_path = model_dir / "pcbm_recall.joblib"
    completion_path = model_dir / "pcbm_completion.joblib"
    joblib.dump(recall, recall_path)
    joblib.dump(completion, completion_path)

    users = sorted({e["user_id"] for e in events})
    meta = {
        "source": source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "events": int(len(events)),
        "records": int(len(df)),
        "users": int(len(users)),
        "user_ids": users,
        "recall_model": {
            "path": str(recall_path),
            "training_rows": recall["training_rows"],
            "positive_rate": recall["positive_rate"],
            "evaluation": recall["evaluation"],
        },
        "completion_model": {
            "path": str(completion_path),
            "training_rows": completion["training_rows"],
            "positive_rate": completion["positive_rate"],
            "evaluation": completion["evaluation"],
        },
        "note": "Mô hình được huấn luyện trực tiếp từ lịch sử sự kiện trong SQLite. Đặc trưng lịch sử được tính riêng theo từng user_id.",
    }
    (model_dir / "pcbm_model_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
