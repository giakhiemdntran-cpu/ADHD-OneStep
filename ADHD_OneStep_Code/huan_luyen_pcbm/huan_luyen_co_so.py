import argparse
from pathlib import Path

import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.ensemble import RandomForestClassifier

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

def chay_chuong_trinh():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--target", default="y_complete_within_30m")
    ap.add_argument("--model-out", default="outputs/baseline_model.joblib")
    args = ap.parse_args()

    df = pd.read_csv(args.input)

    if args.target not in df.columns:
        raise SystemExit(f"Unknown target: {args.target}")

    # Kết quả chưa biết KHÔNG được tự động xem là lớp âm.
    df = df[df[args.target].notna()].copy()

    # Chia theo thời gian: 70% dữ liệu đầu để huấn luyện, 30% dữ liệu sau để kiểm thử.
    df["decision_time"] = pd.to_datetime(df["decision_time"], utc=True)
    df = df.sort_values("decision_time").reset_index(drop=True)

    if len(df) < 4:
        raise SystemExit("Need at least 4 labeled records for demo training.")

    cut = max(1, int(len(df) * 0.7))
    train = df.iloc[:cut]
    test = df.iloc[cut:]

    feature_cols = [
        c for c in df.columns
        if c not in DROP_COLUMNS
        and c not in ALL_LABELS
    ]

    X_train = train[feature_cols]
    y_train = train[args.target].astype(int)

    X_test = test[feature_cols]
    y_test = test[args.target].astype(int)

    cat_cols = [
        c for c in feature_cols
        if X_train[c].dtype == "object"
    ]
    num_cols = [c for c in feature_cols if c not in cat_cols]

    pre = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="median"))
                ]),
                num_cols
            ),
            (
                "cat",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore"))
                ]),
                cat_cols
            )
        ]
    )

    model = RandomForestClassifier(
        n_estimators=250,
        max_depth=8,
        random_state=42,
        class_weight="balanced"
    )

    pipe = Pipeline([
        ("preprocess", pre),
        ("model", model)
    ])

    pipe.fit(X_train, y_train)

    pred = pipe.predict(X_test)

    print("Target:", args.target)
    print("Train rows:", len(train))
    print("Test rows:", len(test))
    print(classification_report(y_test, pred, zero_division=0))

    if len(set(y_test)) > 1 and hasattr(pipe, "predict_proba"):
        p = pipe.predict_proba(X_test)[:, 1]
        print("ROC-AUC:", round(roc_auc_score(y_test, p), 4))

    out = Path(args.model_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": pipe,
            "feature_columns": feature_cols,
            "target": args.target
        },
        out
    )
    print("Saved:", out)

if __name__ == "__main__":
    chay_chuong_trinh()
