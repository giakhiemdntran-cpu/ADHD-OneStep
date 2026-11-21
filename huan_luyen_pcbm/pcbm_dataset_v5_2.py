"""Build an auditable dataset from the existing PCBM SQLite log.

Non-destructive, evidence-first. Never fabricates negatives for missing events.
Train/test split columns are assigned by user and time as separate audit protocols.
"""
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import pandas as pd
from huan_luyen_pcbm.pcbm_mix_v5 import load_events, build_dataframe, TARGETS, _verified_coverage

VERSION='PCBM-V5.2-EVIDENCE'
TARGET_ANCHOR={
 'y_cue_assisted_recall':'REMINDER_SENT',
 'y_independent_task_initiation':'TASK_CREATED',
 'y_complete_within_30m_verified':'REMINDER_SENT',
}

def _split_by_users(users):
    uniq=sorted(set(str(u) for u in users))
    ranked=sorted(uniq,key=lambda u:hashlib.sha256(('pcbm-v5.2-split-42:'+u).encode()).hexdigest())
    n=len(ranked); n_train=int(n*.6); n_valid=int(n*.2)
    return {u:('train' if i<n_train else 'validation' if i<n_train+n_valid else 'test') for i,u in enumerate(ranked)}


def build_audit(events, data):
    """Enrich previous v5 labels with independently inspectable event references.

    No new inference of ITI or negative Completion is performed here.
    """
    by_id={str(e['event_id']):e for e in events}
    by_occ=defaultdict(list)
    for e in events:by_occ[(e['user_id'],e['occurrence_id'])].append(e)
    for seq in by_occ.values():seq.sort(key=lambda x:(x['timestamp'],str(x['event_id'])))
    df=data.copy()
    df['dataset_version']=VERSION
    df['source_database_table']='pcbm_events'
    df['data_origin']=df['is_demo'].map(lambda d:'synthetic_or_demo' if bool(d) else 'unverified_non_demo')
    # A record's anchor cannot leak future information into features.
    df['feature_cutoff_rule']='strictly_before_decision_time'
    for target in TARGETS:
        df[target+'_status']='unknown'
        df[target+'_evidence_event_ids']=''
        df[target+'_reason']=''

    for i,row in df.iterrows():
        evt=by_id.get(str(row['source_event_id']))
        if not evt:continue
        t=evt['timestamp']; seq=by_occ[(evt['user_id'],evt['occurrence_id'])]
        before=[e for e in seq if e['timestamp']<t]
        after=[e for e in seq if e['timestamp']>t]
        for target in TARGETS:
            value=row[target]
            if pd.isna(value):
                reason=('wrong_anchor_type' if evt['event_type'] != TARGET_ANCHOR[target] else
                        'no_verified_observation_or_outcome')
                df.at[i,target+'_reason']=reason
                continue
            df.at[i,target+'_status']='positive' if int(value)==1 else 'negative'
            found=[]; reason=''
            if target=='y_cue_assisted_recall':
                matches=[e for e in after if e['event_type'] in ('RECALL_SUCCESS','RECALL_FAILURE') and e['timestamp']<=t+timedelta(minutes=2)]
                if matches:found=[matches[0]['event_id']]; reason='explicit_recall_feedback_within_2m_after_generic_cue'
            elif target=='y_independent_task_initiation':
                reminders=[e for e in after if e['event_type']=='REMINDER_SENT']
                cutoff=reminders[0]['timestamp'] if reminders else t
                if int(value)==1:
                    matches=[e for e in after if e['timestamp']<cutoff and e['event_type'] in ('TASK_STARTED','USER_REMEMBERED') and (e.get('data') or {}).get('evidence_source') in ('user_initiated_action','self_initiated_report')]
                    found=[matches[0]['event_id']] if matches else []
                    reason='verified_self_initiated_before_first_prompt'
                else:
                    matches=[e for e in seq if e['event_type'] in ('OBSERVATION_VERIFIED','MONITORING_COVERAGE_VERIFIED') and e['timestamp']>=cutoff]
                    found=[matches[0]['event_id']] if matches else []
                    reason='explicit_full_coverage_no_initiation'
            elif target=='y_complete_within_30m_verified':
                if int(value)==1:
                    matches=[e for e in after if e['event_type']=='TASK_COMPLETED' and e['timestamp']<=t+timedelta(minutes=30)]
                    found=[matches[0]['event_id']] if matches else []
                    reason='task_completed_within_30m'
                else:
                    matches=[e for e in seq if e['event_type'] in ('OBSERVATION_VERIFIED','MONITORING_COVERAGE_VERIFIED') and e['timestamp']>=t+timedelta(minutes=30)]
                    found=[matches[0]['event_id']] if matches else []
                    reason='explicit_verified_full_30m_window_no_completion'
            df.at[i,target+'_evidence_event_ids']=';'.join(str(x) for x in found)
            df.at[i,target+'_reason']=reason
            if not found:
                # Fail closed on missing evidence refs; this should never happen with valid upstream output.
                df.at[i,target]=float('nan')
                df.at[i,target+'_status']='unknown'
                df.at[i,target+'_reason']='AUDIT_REJECTED_no_source_event'
    split=_split_by_users(df['user_id'].astype(str))
    df['split_by_user']=df['user_id'].astype(str).map(split)
    # Time protocol is separate. Do not represent this as simultaneously user-independent.
    ordered=pd.to_datetime(df['decision_time'],utc=True)
    d1=ordered.quantile(.70);d2=ordered.quantile(.85)
    df['split_by_time']=['train' if t<d1 else 'validation' if t<d2 else 'test' for t in ordered]
    df['time_split_cutoff_train']=str(d1)
    df['time_split_cutoff_test']=str(d2)
    df['exclude_from_real_world_evidence']=df['is_demo'].astype(bool)
    return df


def generate_dataset(db_path, output_dir='data/pcbm_v5_2'):
    dest=Path(output_dir);dest.mkdir(parents=True,exist_ok=True)
    events=load_events(db_path)
    original=build_dataframe(events)
    if original.empty:raise ValueError('Không có quyết định TASK_CREATED/REMINDER_SENT để gán nhãn')
    df=build_audit(events,original)
    # A safe feature export: labels, evidence, metadata separated from model features.
    target_cols=list(TARGETS)
    stats={}
    for target in target_cols:
        stats[target]={
            'name':TARGETS[target],
            'positive':int((df[target]==1).sum()),
            'negative':int((df[target]==0).sum()),
            'unknown':int(df[target].isna().sum()),
            'by_user_split':{name:{'positive':int((p[target]==1).sum()),'negative':int((p[target]==0).sum()),'unknown':int(p[target].isna().sum())} for name,p in df.groupby('split_by_user')},
            'rejected_missing_evidence':int((df[target+'_reason']=='AUDIT_REJECTED_no_source_event').sum()),
        }
    meta={
        'schema_version':VERSION,'source_db':str(db_path),'source_table':'pcbm_events',
        'rows_events':len(events),'rows_decisions':len(df),'unique_users':int(df['user_id'].nunique()),
        'date_min':str(df['decision_time'].min()),'date_max':str(df['decision_time'].max()),
        'demo_records':int(df['is_demo'].sum()),'non_demo_records':int((~df['is_demo'].astype(bool)).sum()),
        'status':'TECHNICAL_DEMO_ONLY' if bool(df['is_demo'].all()) else 'MIXED_OR_UNVERIFIED_REQUIRES_AUDIT',
        'definitions':{
          'y_cue_assisted_recall':'Explicit RECALL_SUCCESS/FAILURE within 2 minutes following a generic cue',
          'y_independent_task_initiation':'Verified self-initiated start before first reminder; negative only with certified continuous observation',
          'y_complete_within_30m_verified':'Completed within 30 minutes; negative only with certified full observation window',
        },
        'unknown_policy':'Missing evidence is Unknown, never silently 0',
        'prediction_features':'Historical features generated strictly before anchor; exclude label/evidence/split columns',
        'evaluation_protocols':'Separate user-group holdout and temporal holdout; not jointly independent; demo cannot validate real-world effectiveness',
        'dataset_splits_by_user':{k:int(v) for k,v in Counter(split for split in _split_by_users(df.user_id).values()).items()},
        'targets':stats,
    }
    for target in TARGETS:
        df[target]=df[target].astype('Int64')
    csv=dest/'pcbm_v5_2_full_labeled.csv'
    df.to_csv(csv,index=False,encoding='utf-8-sig')
    # Emit separate ready-to-train datasets, ONLY eligible 0/1 labels. This is not artificial balancing.
    valid_outputs={}
    for target in TARGETS:
        work=df[df[target].isin([0,1])].copy()
        valid=dest/(target+'_eligible.csv')
        work.to_csv(valid,index=False,encoding='utf-8-sig')
        valid_outputs[target]=len(work)
    with (dest/'DATASET_MANIFEST.json').open('w',encoding='utf8') as f:json.dump(meta,f,ensure_ascii=False,indent=2)
    (dest/'DATA_QUALITY_README.txt').write_text(
        'PCBM v5.2 – Evidence-qualified dataset.\n'
        'Full CSV contains all decisions; Unknown is intentionally retained.\n'
        'Eligible CSV per target contains ONLY 0/1 cases with evidence and no synthesized negatives.\n'
        'For real-world inference, filter is_demo==False and independently verify provenance.\n'
        'Split columns are alternative protocols (by user / by time), not simultaneous proof.\n'
        'Do not use model to diagnose ADHD or automatically reduce reminders.\n',encoding='utf8')
    return meta,df

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default='storage/onestep.db')
    parser.add_argument('--output',default='data/pcbm_v5_2')
    args=parser.parse_args()
    report,_=generate_dataset(args.db,args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
