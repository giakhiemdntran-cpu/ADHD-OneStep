"""PCBM combined-label v5: auditable pilot, non-deploying, evidence-first."""
from __future__ import annotations
import json, sqlite3
import joblib
from pathlib import Path
from collections import Counter
from datetime import timedelta
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, balanced_accuracy_score, confusion_matrix, precision_score, recall_score, f1_score
from sklearn.model_selection import GroupShuffleSplit

TARGETS = {
 'y_cue_assisted_recall': 'Nhớ đúng sau gợi ý chung (2 phút)',
 'y_independent_task_initiation': 'Chủ động bắt đầu trước lời nhắc (ITI)',
 'y_complete_within_30m_verified': 'Hoàn thành trong 30 phút, nhãn có kiểm chứng',
}
LABELS = set(TARGETS) | {'y_recall_success','y_started_within_10m','y_complete_within_30m','y_complete_within_60m','y_start_delay_minutes','y_completion_delay_minutes','y_snooze','y_forgot'}
META = {'user_id','task_id','occurrence_id','decision_time','decision_type','label_schema_version','feature_schema_version','pipeline_version','observation_quality','label_reason','is_demo','source_event_id'}


def _demo(e):
    d=e.get('data') or {}; u=str(e.get('user_id','')).lower()
    return bool(d.get('is_demo') or d.get('simulation') or u.startswith(('test_', 'demo_', 'synthetic_')))


def load_events(db_path):
    from huan_luyen_pcbm.huan_luyen_tu_csdl import dong_sang_su_kien
    p=Path(db_path)
    if not p.is_file(): raise FileNotFoundError(f'Không tìm thấy SQLite: {p}')
    with sqlite3.connect(str(p)) as c:
        c.row_factory=sqlite3.Row
        cols={r['name'] for r in c.execute('PRAGMA table_info(pcbm_events)')}
        if not {'id','user_id','task_id','occurrence_id','event_type','created_at','data_json'} <= cols:
            raise ValueError('Không thấy bảng pcbm_events đúng cấu trúc')
        rows=c.execute('SELECT id,user_id,task_id,occurrence_id,event_type,created_at,data_json FROM pcbm_events ORDER BY created_at,id').fetchall()
    return dong_sang_su_kien(rows)


def _visible(events, e, until):
    return [x for x in events if x['occurrence_id']==e['occurrence_id'] and x['user_id']==e['user_id'] and x['timestamp']<=until]


def _verified_coverage(evs, anchor, end):
    # ONLY explicit independently logged monitoring certification, never last event timestamp.
    for x in evs:
        d=x.get('data') or {}
        if x['event_type'] in ('OBSERVATION_VERIFIED','MONITORING_COVERAGE_VERIFIED') and x['timestamp']>=end and d.get('verified_continuous_coverage') is True:
            # Require explicit temporal coverage boundaries, not just a boolean flag.
            try:
                start_logged=pd.Timestamp(d['coverage_start'])
                end_logged=pd.Timestamp(d['coverage_end'])
                start_ref=pd.Timestamp(anchor)
                end_ref=pd.Timestamp(end)
                if start_logged<=start_ref and end_logged>=end_ref: return True
            except (KeyError,TypeError,ValueError):
                pass
    return False


def _label_reminder(evs, decision):
    t=decision['timestamp']; data=decision.get('data') or {}
    current=_visible(evs,decision,t+timedelta(minutes=30))
    follow=[x for x in current if x['timestamp']>t]
    recall=None
    if str(data.get('reminder_type','')).lower()=='generic':
        answers=sorted((e for e in follow if e['event_type'] in ('RECALL_SUCCESS','RECALL_FAILURE') and e['timestamp']<=t+timedelta(minutes=2)),key=lambda a:a['timestamp'])
        if answers: recall=int(answers[0]['event_type']=='RECALL_SUCCESS')
    done=any(x['event_type']=='TASK_COMPLETED' and x['timestamp']<=t+timedelta(minutes=30) for x in follow)
    completion=1 if done else (0 if _verified_coverage(current,t,t+timedelta(minutes=30)) else None)
    return recall,completion


def _label_iti(evs, created):
    # Prediction anchor = TASK_CREATED; outcome until FIRST reminder. No post-creation features.
    t=created['timestamp']; oid=created['occurrence_id']; uid=created['user_id']
    seq=sorted((x for x in evs if x['user_id']==uid and x['occurrence_id']==oid and x['timestamp']>=t),key=lambda x:x['timestamp'])
    prompts=[e for e in seq if e['event_type']=='REMINDER_SENT']
    if not prompts: return None,'no_first_reminder_boundary'
    boundary=prompts[0]['timestamp']
    if boundary<=t: return None,'no_pre_prompt_window'
    pre=[e for e in seq if t<e['timestamp']<boundary]
    positive= [e for e in pre if e['event_type'] in ('TASK_STARTED','USER_REMEMBERED') and (e.get('data') or {}).get('evidence_source') in ('user_initiated_action','self_initiated_report') and not _demo(e)]
    if positive: return 1,'verified_self_initiated_before_first_prompt'
    # False is not inferred from missing start event. Verification requires an explicit coverage event.
    if _verified_coverage(seq,t,boundary):return 0,'verified_no_initiation_before_first_prompt'
    return None,'unknown_no_verified_self_initiation_or_coverage'


def build_dataframe(events):
    from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung
    by_user={}
    for e in events: by_user.setdefault(e['user_id'],[]).append(e)
    rows=[]; counts=Counter()
    for uid, seq in by_user.items():
        seq.sort(key=lambda e:(e['timestamp'],str(e['event_id'])))
        for decision in seq:
            if decision['event_type'] not in ('REMINDER_SENT','TASK_CREATED'):continue
            # Features are computed solely from events with timestamps before anchor.
            f=xay_dung_dac_trung(seq,decision)
            if decision['event_type']=='TASK_CREATED':
                # Task metadata known at creation is allowed (not a future label).
                d=decision.get('data') or {}
                f['task_type']=d.get('task_type','UNKNOWN')
                f['priority']=d.get('priority')
                f['estimated_minutes']=d.get('estimated_minutes')
            f.update({k:None for k in TARGETS})
            f['source_event_id']=decision['event_id'];f['label_schema_version']='5.1-mixed-pilot'
            f['is_demo']=any(_demo(e) for e in seq if e['occurrence_id']==decision['occurrence_id'])
            if decision['event_type']=='REMINDER_SENT':
                recall,completion=_label_reminder(seq,decision)
                f['y_cue_assisted_recall']=recall
                f['y_complete_within_30m_verified']=completion
                f['label_reason']='after_generic_cue' if recall is not None else 'no_observed_cue_answer'
            else:
                iti,reason=_label_iti(seq,decision)
                f['y_independent_task_initiation']=iti
                f['label_reason']=reason
            rows.append(f)
    df=pd.DataFrame(rows)
    if not df.empty: df=df.sort_values(['decision_time','user_id','occurrence_id']).reset_index(drop=True)
    return df


def _split(work, method='user', test_size=.25):
    if method=='user':
        groups=work['user_id'].astype(str)
        if groups.nunique()<4: return None,None,'Cần ít nhất 4 người dùng độc lập.'
        splitter=GroupShuffleSplit(n_splits=1,test_size=test_size,random_state=42)
        tr,te=next(splitter.split(work,groups=groups))
        return tr,te,None
    if method=='time':
        idx=np.argsort(pd.to_datetime(work['decision_time'],utc=True).to_numpy())
        cut=int(len(idx)*(1-test_size))
        return idx[:cut],idx[cut:],None
    raise ValueError('method phải là user hoặc time')


def evaluate_target(df,target,method='user',exclude_demo=True,output_dir=None):
    if target not in TARGETS:raise ValueError('Nhãn không được hỗ trợ')
    full=df.copy(); full[target]=pd.to_numeric(full[target],errors='coerce')
    stats={'target':target,'name':TARGETS[target],'total':int(len(full)), 'unknown':int(full[target].isna().sum()),'positives':int((full[target]==1).sum()),'negatives':int((full[target]==0).sum()),'demo_rows':int(full['is_demo'].fillna(False).sum())}
    work=full[full[target].isin([0,1])].copy()
    if exclude_demo: work=work[~work['is_demo'].fillna(False)].copy()
    stats['eligible_after_filter']=int(len(work));stats['split']=method
    if len(work)<30 or work[target].nunique()<2:
        
        reason = ('Toàn bộ nhãn có bằng chứng thuộc dữ liệu demo/test và đã bị lọc.' if len(work)==0 and stats['positives']+stats['negatives']>0 and exclude_demo else
                  'Chưa có nhãn 0/1 có bằng chứng (chỉ có Unknown).' if stats['positives']+stats['negatives']==0 else
                  'Chỉ có một lớp nhãn 0/1; cần cả hai lớp để huấn luyện và tính AUC.' if work[target].nunique()<2 else
                  'Ít hơn 30 mẫu nhãn hợp lệ sau lọc.')
        return {**stats,'status':'insufficient_data','reason':reason}
    tr,te,err=_split(work,method)
    if err: return {**stats,'status':'insufficient_data','reason':err}
    train,test=work.iloc[tr],work.iloc[te]
    if train[target].nunique()<2 or test[target].nunique()<2:
        return {**stats,'status':'insufficient_data','reason':'Train hoặc test chỉ có một lớp; không thể tính ROC-AUC hợp lệ.','train_n':len(train),'test_n':len(test)}
    # Feature columns: hard allowlist sourced from pre-anchor feature function, not post-event labels.
    numeric=['hour','weekday','is_weekend','hour_sin','hour_cos','priority','estimated_minutes','prompt_level','completion_rate_7d','completion_rate_30d','snooze_rate_7d','forget_rate_7d','avg_start_delay_7d','recall_rate_1d','recall_rate_3d','recall_rate_7d','recall_count_1d','recall_count_3d','recall_count_7d','recall_success_streak','recall_failure_streak','minutes_since_last_recall','same_task_recall_rate','same_task_recall_count','same_task_completion_rate','event_count_before','history_days','is_cold_start','user_feedback_count_30d','user_feedback_accept_rate_30d','user_feedback_keep_count_30d','user_feedback_more_count_30d','user_feedback_less_count_30d','user_feedback_last_final_level','user_feedback_age_days']
    categorical=['time_of_day','task_type','last_recall_feedback','user_feedback_last_action','reminder_type','channel']
    numeric=[c for c in numeric if c in work.columns and work[c].notna().any()]
    categorical=[c for c in categorical if c in work.columns and work[c].notna().any()]
    if not numeric and not categorical:return {**stats,'status':'insufficient_data','reason':'Không có đặc trưng lịch sử hợp lệ.'}
    preprocess=ColumnTransformer([('num',Pipeline([('fill',SimpleImputer(strategy='median')),('scale',StandardScaler())]),numeric),('cat',Pipeline([('fill',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),categorical)])
    mdl=Pipeline([('pre',preprocess),('model',LogisticRegression(max_iter=1500,class_weight='balanced',random_state=42))])
    mdl.fit(train,train[target].astype(int))
    prob=mdl.predict_proba(test)[:,list(mdl.named_steps['model'].classes_).index(1)]
    pred=(prob>=.5).astype(int);y=test[target].astype(int).to_numpy()
    cm=confusion_matrix(y,pred,labels=[0,1]); baseline=DummyClassifier(strategy='prior');baseline.fit(np.zeros((len(train),1)),train[target].astype(int));prior=baseline.predict_proba(np.zeros((len(test),1)))[:,list(baseline.classes_).index(1)]
    saved_model = None
    if output_dir is not None:
        model_file = Path(output_dir) / f'{target}_{method}.joblib'
        model_file.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({'pipeline':mdl,'target':target,'split':method,'label_version':'v5',
                     'note':'research-only, no deployment, trained on train split only'}, model_file)
        saved_model = str(model_file)
    return {**stats,'saved_model':saved_model,'status':'evaluated','train_n':int(len(train)),'test_n':int(len(test)),'train_users':int(train['user_id'].nunique()),'test_users':int(test['user_id'].nunique()),'user_overlap':int(len(set(train['user_id']) & set(test['user_id']))),'train_last':str(train['decision_time'].max()),'test_first':str(test['decision_time'].min()),'roc_auc':float(roc_auc_score(y,prob)),'pr_auc':float(average_precision_score(y,prob)),'dummy_pr_auc':float(average_precision_score(y,prior)),'balanced_accuracy':float(balanced_accuracy_score(y,pred)),'precision':float(precision_score(y,pred,zero_division=0)),'recall':float(recall_score(y,pred,zero_division=0)),'f1':float(f1_score(y,pred,zero_division=0)),'confusion_matrix':cm.tolist(),'feature_columns':numeric+categorical,'methodology':'Exploratory holdout, not prospective or externally independent.'}


def run_experiment(db_path,method='user',exclude_demo=True,output_dir='models/v5_experiments',dataset_df=None):
    events=load_events(db_path);df=build_dataframe(events) if dataset_df is None else dataset_df.copy()
    results={k:evaluate_target(df,k,method,exclude_demo,output_dir=output_dir) for k in TARGETS}
    report={'version':'pcbm-v5-mixed-pilot','notice':'NO DEPLOYMENT; no automatic support changes; not ADHD diagnosis','events':len(events),'records':len(df),'split':method,'exclude_demo':exclude_demo,'targets':results,'training_input':'evidence_audited_dataset_v5_2' if dataset_df is not None else 'legacy_v5_generated_labels'}
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'pcbm_mix_v5_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    df.to_csv(out/'pcbm_mix_v5_labels.csv',index=False,encoding='utf-8-sig')
    return report,df
