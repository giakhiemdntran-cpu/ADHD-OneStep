from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from huan_luyen_pcbm.xay_dung_du_lieu import xay_dung_ban_ghi_hoc

TRAINING_VERSION = "PCBM-label-v5"
MODEL_SELECTION_METRIC = "pr_auc"

DROP_COLUMNS = {
    "user_id", "occurrence_id", "decision_time", "feature_schema_version",
    "label_schema_version", "pipeline_version", "decision_event_type",
}
ALL_LABELS = {
    "y_recall_success", "y_started_within_10m", "y_start_delay_minutes",
    "y_complete_within_30m", "y_complete_within_60m",
    "y_completion_delay_minutes", "y_snooze", "y_forgot",
    "y_cue_assisted_recall", "y_independent_task_initiation", "y_complete_within_30m_verified",
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
            if ts.tzinfo is not None:
                ts = ts.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)
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


def _cot_dac_trung(work):
    return [c for c in work.columns if c not in DROP_COLUMNS and c not in ALL_LABELS]


def _tao_tien_xu_ly(feature_cols, X, scale_numeric=False):
    cat_cols = [c for c in feature_cols if X[c].dtype == "object"]
    num_cols = [c for c in feature_cols if c not in cat_cols]

    num_steps = [("imputer", SimpleImputer(strategy="median", keep_empty_features=True))]
    if scale_numeric:
        num_steps.append(("scaler", StandardScaler()))

    return ColumnTransformer([
        ("num", Pipeline(num_steps), num_cols),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), cat_cols),
    ], remainder="drop")


def _ung_vien(feature_cols, X):
    """Các mô hình ứng viên PCBM: Dummy, Logistic, Random Forest và Gradient Boosting."""
    return {
        "DummyPrior": Pipeline([
            ("preprocess", _tao_tien_xu_ly(feature_cols, X, scale_numeric=False)),
            ("model", DummyClassifier(strategy="prior", random_state=42)),
        ]),
        "LogisticRegression": Pipeline([
            ("preprocess", _tao_tien_xu_ly(feature_cols, X, scale_numeric=True)),
            ("model", LogisticRegression(
                max_iter=2000,
                class_weight="balanced",
                random_state=42,
            )),
        ]),
        "RandomForestClassifier": Pipeline([
            ("preprocess", _tao_tien_xu_ly(feature_cols, X, scale_numeric=False)),
            ("model", RandomForestClassifier(
                n_estimators=400,
                max_depth=8,
                min_samples_leaf=3,
                random_state=42,
                class_weight="balanced",
                n_jobs=-1,
            )),
        ]),
        "GradientBoostingClassifier": Pipeline([
            ("preprocess", _tao_tien_xu_ly(feature_cols, X, scale_numeric=False)),
            ("model", GradientBoostingClassifier(
                n_estimators=150,
                learning_rate=0.04,
                max_depth=2,
                random_state=42,
            )),
        ]),
    }


def _xac_suat_lop_1(pipe, X):
    p = pipe.predict_proba(X)
    classes = list(pipe.named_steps["model"].classes_)
    if 1 not in classes:
        return np.zeros(len(X), dtype=float)
    return np.asarray(p[:, classes.index(1)], dtype=float)


def _ece(y_true, prob, bins=10):
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(prob, dtype=float)
    if len(y) == 0:
        return None
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    err = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        acc = float(y[mask].mean())
        conf = float(p[mask].mean())
        err += (n / total) * abs(acc - conf)
    return float(err)


def _metrics(y_true, pred, prob):
    y = np.asarray(y_true, dtype=int)
    pred = np.asarray(pred, dtype=int)
    prob = np.asarray(prob, dtype=float)
    cm = confusion_matrix(y, pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    out = {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "specificity": specificity,
        "f1": float(f1_score(y, pred, zero_division=0)),
        "confusion_matrix": cm.tolist(),
        "brier_score": float(brier_score_loss(y, prob)),
        "ece_10bin": _ece(y, prob, bins=10),
    }
    out["pr_auc"] = float(average_precision_score(y, prob)) if len(np.unique(y)) > 1 else None
    out["roc_auc"] = float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else None
    return out




def _chon_nguong_tu_qua_khu(base_pipe, X_train, y_train):
    """Tune threshold on historical TRAIN segment only; never look at test labels.

    Uses the last 25% of train for threshold selection; if insufficient,
    returns 0.5. The chosen threshold is frozen before seeing the next fold.
    """
    y_train = pd.Series(y_train).reset_index(drop=True)
    size = len(y_train)
    cut = int(size * 0.75)
    if cut < 35 or size - cut < 15 or y_train.iloc[:cut].nunique() < 2 or y_train.iloc[cut:].nunique() < 2:
        return 0.5
    probe = clone(base_pipe)
    probe.fit(X_train.iloc[:cut], y_train.iloc[:cut])
    p = _xac_suat_lop_1(probe, X_train.iloc[cut:])
    y = y_train.iloc[cut:].to_numpy(dtype=int)
    # The business cost is missing completion: constrain both sensitivity
    # and specificity so lowering threshold cannot blindly mark all as 1.
    eligible=[]
    for thr in np.linspace(0.15, 0.85, 71):
        pred = (p >= thr).astype(int)
        tp = int(((y == 1) & (pred == 1)).sum())
        fn = int(((y == 1) & (pred == 0)).sum())
        tn = int(((y == 0) & (pred == 0)).sum())
        fp = int(((y == 0) & (pred == 1)).sum())
        recall = tp / (tp + fn) if tp + fn else 0
        specificity = tn / (tn + fp) if tn + fp else 0
        if recall >= 0.50 and specificity >= 0.50:
            eligible.append((f1_score(y, pred, zero_division=0),
                             balanced_accuracy_score(y, pred), -abs(thr-0.5), float(thr)))
    if not eligible:
        return 0.5
    return max(eligible)[-1]

def _danh_gia_walk_forward(work, feature_cols, target, n_splits=3):
    work = work.sort_values("decision_time").reset_index(drop=True)
    if len(work) < 30:
        return {
            "available": False,
            "reason": "Không đủ dữ liệu cho walk-forward validation (cần ít nhất 30 bản ghi).",
        }, None

    n_splits = min(int(n_splits), max(2, len(work) // 20))
    if n_splits >= len(work):
        n_splits = max(2, len(work) - 1)

    X_all = work[feature_cols]
    y_all = work[target].astype(int).reset_index(drop=True)
    candidates = _ung_vien(feature_cols, X_all)
    tscv = TimeSeriesSplit(n_splits=n_splits)
    leaderboard = []

    for name, base_pipe in candidates.items():
        ys, preds, probs = [], [], []
        folds = []
        for fold_no, (train_idx, test_idx) in enumerate(tscv.split(X_all), 1):
            X_train = X_all.iloc[train_idx]
            y_train = y_all.iloc[train_idx]
            X_test = X_all.iloc[test_idx]
            y_test = y_all.iloc[test_idx]
            if y_train.nunique() < 2:
                folds.append({"fold": fold_no, "skipped": True, "reason": "train_one_class"})
                continue
            # Completion: optimize decision threshold on the PAST ONLY.
            threshold = (_chon_nguong_tu_qua_khu(base_pipe, X_train, y_train)
                         if target in {"y_complete_within_30m", "y_complete_within_30m_verified"}
                         else 0.5)
            pipe = clone(base_pipe)
            pipe.fit(X_train, y_train)
            prob = _xac_suat_lop_1(pipe, X_test)
            pred = (prob >= threshold).astype(int)
            m = _metrics(y_test, pred, prob)
            folds.append({
                "fold": fold_no,
                "train_rows": int(len(train_idx)),
                "test_rows": int(len(test_idx)),
                "decision_threshold": float(threshold),
                **m,
            })
            ys.extend(y_test.tolist())
            preds.extend(np.asarray(pred, dtype=int).tolist())
            probs.extend(np.asarray(prob, dtype=float).tolist())

        if not ys:
            leaderboard.append({"model": name, "available": False, "folds": folds})
            continue
        overall = _metrics(ys, preds, probs)
        fold_roc_auc = [
            float(f["roc_auc"])
            for f in folds
            if not f.get("skipped", False) and f.get("roc_auc") is not None
        ]
        roc_auc_std = float(np.std(fold_roc_auc, ddof=0)) if fold_roc_auc else None
        leaderboard.append({
            "model": name,
            "available": True,
            "thresholds_by_fold": [f.get("decision_threshold") for f in folds if not f.get("skipped")],
            "fold_count": int(sum(not f.get("skipped", False) for f in folds)),
            "test_rows": int(len(ys)),
            "folds": folds,
            "roc_auc_std": roc_auc_std,
            **overall,
        })

    valid = [x for x in leaderboard if x.get("available")]
    if not valid:
        return {"available": False, "reason": "Không có fold hợp lệ.", "leaderboard": leaderboard}, None

    # Ưu tiên PR-AUC vì dữ liệu có thể lệch lớp; nếu gần nhau thì dùng
    # Balanced Accuracy rồi F1 để phá hòa.
    def rank_key(x):
        pr = x.get("pr_auc")
        return (
            (-1.0 if pr is None else pr),
            x.get("balanced_accuracy", -1.0),
            x.get("f1", -1.0),
        )

    # Completion uses an operationally meaningful selection criterion.
    # Keep PR-AUC within 0.03 of the best to avoid discarding ranking quality,
    # then prefer a higher F1 and balanced accuracy. Recall unchanged.
    is_completion = target in {"y_complete_within_30m", "y_complete_within_30m_verified"}
    if is_completion:
        top_pr = max((x.get("pr_auc") if x.get("pr_auc") is not None else -1) for x in valid)
        shortlist = [x for x in valid if (x.get("pr_auc") or -1) >= top_pr - 0.03]
        best = max(shortlist, key=lambda x: (x.get("f1", 0), x.get("balanced_accuracy", 0), x.get("pr_auc", -1)))
    else:
        best = max(valid, key=rank_key)
    final_train_rows = int(len(work) - max(1, len(work) // (n_splits + 1)))
    evaluation = {
        "available": True,
        "method": "walk_forward_time_series",
        "selection_metric": "f1_with_pr_auc_guard_0.03" if is_completion else MODEL_SELECTION_METRIC,
        "threshold_policy": "past_training_only_f1_with_recall_specificity_floor_0.50" if is_completion else "fixed_0.5",
        "n_splits": n_splits,
        "train_rows": final_train_rows,
        "test_rows": best["test_rows"],
        "selected_model": best["model"],
        "decision_thresholds_by_fold": best.get("thresholds_by_fold", []),
        "accuracy": best["accuracy"],
        "balanced_accuracy": best["balanced_accuracy"],
        "precision": best["precision"],
        "recall": best["recall"],
        "specificity": best["specificity"],
        "f1": best["f1"],
        "pr_auc": best["pr_auc"],
        "roc_auc": best["roc_auc"],
        "roc_auc_std": best.get("roc_auc_std"),
        "brier_score": best["brier_score"],
        "ece_10bin": best["ece_10bin"],
        "confusion_matrix": best["confusion_matrix"],
        "leaderboard": leaderboard,
    }
    return evaluation, best["model"]


def _huan_luyen_cuoi(df, target, source):
    work = df[df[target].notna()].copy()
    if len(work) < 4:
        raise RuntimeError(f"Không đủ dữ liệu có nhãn cho {target}: {len(work)} bản ghi")
    work[target] = work[target].astype(int)
    if work[target].nunique() < 2:
        raise RuntimeError(f"Nhãn {target} chỉ có một lớp, chưa thể huấn luyện mô hình phân loại.")

    feature_cols = _cot_dac_trung(work)
    X = work[feature_cols]
    y = work[target].astype(int)

    evaluation, selected_model = _danh_gia_walk_forward(work, feature_cols, target)
    if not selected_model:
        selected_model = "RandomForestClassifier"
    candidates = _ung_vien(feature_cols, X)
    pipe = candidates[selected_model]
    # Final training threshold estimated without peeking into future/test folds.
    chosen_threshold = (_chon_nguong_tu_qua_khu(pipe, X, y)
                        if target in {"y_complete_within_30m", "y_complete_within_30m_verified"}
                        else 0.5)
    pipe.fit(X, y)

    bundle = {
        "decision_threshold": float(chosen_threshold),
        "pipeline": pipe,
        "feature_columns": feature_cols,
        "target": target,
        "training_rows": int(len(work)),
        "positive_rate": float(y.mean()),
        "model_name": selected_model,
        "training_version": TRAINING_VERSION,
        "source": source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "evaluation": evaluation,
    }
    return bundle


def _huan_luyen_neu_du(df, target, source, path):
    """Reuse exact four-candidate v4 trainer; never create one-class classifiers."""
    values = df[target].dropna() if target in df else pd.Series(dtype=float)
    counts = {"0": int((values == 0).sum()), "1": int((values == 1).sum()),
              "unknown": int(len(df) - len(values))}
    if len(values) < 30 or counts["0"] == 0 or counts["1"] == 0:
        why = ("no_verified_labels" if len(values) == 0 else
               "single_class" if min(counts["0"], counts["1"]) == 0 else "too_few_rows")
        return {"available": False, "reason": why, "counts": counts, "path": None}
    try:
        bundle = _huan_luyen_cuoi(df, target, source)
        joblib.dump(bundle, path)
        return {"available": True, "counts": counts, "path": str(path),
                "model_name": bundle["model_name"], "training_rows": bundle["training_rows"],
        "decision_threshold": bundle.get("decision_threshold", 0.5),
                "positive_rate": bundle["positive_rate"], "evaluation": bundle["evaluation"]}
    except Exception as exc:
        return {"available": False, "reason": "training_error", "error": str(exc),
                "counts": counts, "path": None}


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

    recall_result = _huan_luyen_neu_du(df, "y_cue_assisted_recall", source,
                                      model_dir / "pcbm_recall_v5.joblib")
    completion_result = _huan_luyen_neu_du(df, "y_complete_within_30m_verified", source,
                                          model_dir / "pcbm_completion_v5.joblib")
    iti_result = _huan_luyen_neu_du(df, "y_independent_task_initiation", source,
                                   model_dir / "pcbm_iti_v5.joblib")

    users = sorted({e["user_id"] for e in events})
    recall_rows = int(df["y_recall_success"].notna().sum())
    generic_rows = int((df["reminder_type"].astype(str).str.lower() == "generic").sum())
    meta = {
        "training_version": TRAINING_VERSION,
        "source": source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "events": int(len(events)), "records": int(len(df)),
        "users": int(len(users)), "user_ids": users,
        "dataset_summary": {
            "generic_cue_records": generic_rows,
            "recall_labeled_records": recall_rows,
            "recall_label_definition": "Explicit RECALL_SUCCESS/FAILURE within 2 min of generic cue",
            "iti_label_definition": "Verified unprompted start before reminder; otherwise unknown unless complete observation",
            "completion_label_definition": "TASK_COMPLETED within 30m; negative only after verified full observation",
        },
        "recall_model": recall_result,
        "completion_model": completion_result,
        "iti_model": iti_result,
        "note": "Four v4 algorithms and walk-forward retained; v5 models isolated from deployed Buddy; test/demo data is not independent evidence.",
    }
    (model_dir / "pcbm_v5_model_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
