"""Independent evaluation for pre-built labeled CSV; no retraining of deployed models.

Usage:
 python -m huan_luyen_pcbm.danh_gia_doc_lap_v5 --input data/v5_labeled.csv --output models/label_v5_independent_audit.json
"""
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, confusion_matrix, precision_score, recall_score, balanced_accuracy_score

LABELS = ('recall_after_cue', 'completed_within_30m')
BASE_FIELDS = {'user_id','task_id','occurrence_id','decision_time','label_quality', 'label_schema_version','independent_recall', *LABELS}

def evaluate(df, target):
    x = df[df[target].isin([0,1])].copy()
    x['decision_time'] = pd.to_datetime(x['decision_time'], errors='coerce')
    x = x.dropna(subset=['user_id','decision_time'])
    if x.empty:
        return {'status':'not_evaluable', 'reason':'no_valid_labels'}
    # Sorted unseen-user test: last 25% user IDs, deterministic SHA-like grouping not random rows.
    users = sorted(x['user_id'].astype(str).unique().tolist())
    if len(users) < 4:
        return {'status':'not_evaluable','reason':'need_at_least_4_users','n_users':len(users)}
    n_test = max(1, int(np.ceil(len(users)*0.25)))
    test_users = set(users[-n_test:]); train_users = set(users[:-n_test])
    tr = x[x['user_id'].astype(str).isin(train_users)].copy()
    te = x[x['user_id'].astype(str).isin(test_users)].copy()
    if tr[target].nunique() < 2 or te[target].nunique() < 2:
        return {'status':'not_evaluable', 'reason':'one_class_train_or_test', 'train_rows':len(tr), 'test_rows':len(te)}
    # Avoid future-to-past leakage across users: only train before first heldout date.
    cutoff = te['decision_time'].min()
    tr = tr[tr['decision_time'] < cutoff].copy()
    if tr[target].nunique() < 2 or len(tr) < 20:
        return {'status':'not_evaluable','reason':'insufficient_training_before_heldout_time','train_rows':len(tr),'test_rows':len(te)}
    # Only numeric features available at decision time; exclude all targets and metadata.
    forbidden = BASE_FIELDS | {c for c in x.columns if c.startswith('y_') or c.endswith('_label') or c.startswith('label_')}
    features = [c for c in x.columns if c not in forbidden and pd.api.types.is_numeric_dtype(x[c])]
    if not features:
        return {'status':'not_evaluable','reason':'no_numeric_past_only_features'}
    model = make_pipeline(SimpleImputer(strategy='median', add_indicator=True), StandardScaler(), LogisticRegression(max_iter=1000, class_weight='balanced'))
    model.fit(tr[features], tr[target].astype(int))
    p = model.predict_proba(te[features])[:,1]
    pred = (p >= 0.5).astype(int)
    y = te[target].astype(int).to_numpy()
    cm = confusion_matrix(y, pred, labels=[0,1]).tolist()
    return {'status':'evaluated','protocol':'unseen_users_with_past_only_training',
            'warning':'baseline evaluation; not the deployed PCBM model; no hyperparameter tuning on heldout set',
            'train_rows':int(len(tr)),'test_rows':int(len(te)), 'train_users':int(len(train_users)), 'test_users':int(len(test_users)),
            'test_start':str(cutoff), 'roc_auc':float(roc_auc_score(y,p)),
            'pr_auc':float(average_precision_score(y,p)),
            'balanced_accuracy':float(balanced_accuracy_score(y,pred)),
            'precision':float(precision_score(y,pred,zero_division=0)),
            'recall':float(recall_score(y,pred,zero_division=0)),
            'confusion_matrix_TN_FP_FN_TP':cm, 'numeric_features':features}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',required=True)
    args=ap.parse_args()
    df=pd.read_csv(args.input)
    if 'user_id' not in df.columns or 'decision_time' not in df.columns:
        raise ValueError('Missing user_id / decision_time')
    result={'schema':'pcbm-v5-eval-preview','status':'baseline_only','targets':{k:evaluate(df,k) if k in df.columns else {'status':'not_evaluable','reason':'column_missing'} for k in LABELS}}
    dest=Path(args.output); dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
