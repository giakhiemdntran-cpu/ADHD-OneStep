import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier

from huan_luyen_pcbm.xay_dung_du_lieu import tai_du_lieu_jsonl, xay_dung_ban_ghi_hoc

DROP_COLUMNS = {
    "user_id",
    "occurrence_id",
    "decision_time",
    "feature_schema_version",
    "label_schema_version",
    "pipeline_version",
}

ALL_LABELS = {
    "y_recall_success",
    "y_started_within_10m",
    "y_start_delay_minutes",
    "y_complete_within_30m",
    "y_complete_within_60m",
    "y_completion_delay_minutes",
    "y_snooze",
    "y_forgot",
}


def _huan_luyen(df, target):
    work = df[df[target].notna()].copy()
    if len(work) < 4:
        raise RuntimeError(f"Không đủ dữ liệu có nhãn cho {target}")

    feature_cols = [
        c for c in work.columns
        if c not in DROP_COLUMNS and c not in ALL_LABELS
    ]
    X = work[feature_cols]
    y = work[target].astype(int)

    cat_cols = [c for c in feature_cols if X[c].dtype == "object"]
    num_cols = [c for c in feature_cols if c not in cat_cols]

    pre = ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median"))
        ]), num_cols),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore"))
        ]), cat_cols),
    ])

    model = RandomForestClassifier(
        n_estimators=250,
        max_depth=8,
        random_state=42,
        class_weight="balanced",
    )

    pipe = Pipeline([
        ("preprocess", pre),
        ("model", model),
    ])
    pipe.fit(X, y)

    return {
        "pipeline": pipe,
        "feature_columns": feature_cols,
        "target": target,
        "training_rows": len(work),
        "positive_rate": float(y.mean()),
        "model_name": "RandomForestClassifier",
        "source": "sample_events",
    }


def chay_chuong_trinh():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/sample_events.jsonl")
    ap.add_argument("--model-dir", default="models")
    args = ap.parse_args()

    events = tai_du_lieu_jsonl(args.input)
    df = xay_dung_ban_ghi_hoc(events)

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    recall = _huan_luyen(df, "y_recall_success")
    completion = _huan_luyen(df, "y_complete_within_30m")

    recall_path = model_dir / "pcbm_recall.joblib"
    completion_path = model_dir / "pcbm_completion.joblib"
    joblib.dump(recall, recall_path)
    joblib.dump(completion, completion_path)

    meta = {
        "records": len(df),
        "events": len(events),
        "recall_model": str(recall_path),
        "completion_model": str(completion_path),
        "note": "Model demo được train từ sample input, không phải model cá nhân thật.",
    }
    (model_dir / "pcbm_model_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    chay_chuong_trinh()
