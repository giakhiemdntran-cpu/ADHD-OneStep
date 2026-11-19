"""Post-change PCBM evaluation. No model files are overwritten.

Reports date-scoped temporal 80/20 holdout *within existing collected data*.
This is NOT independent external/user-held-out evidence; it cannot unlock fading.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.base import clone
from huan_luyen_pcbm.huan_luyen_tu_csdl import (
    dong_sang_su_kien, _cot_dac_trung, _ung_vien, _xac_suat_lop_1, _metrics,
)
from huan_luyen_pcbm.xay_dung_du_lieu import xay_dung_ban_ghi_hoc

TARGETS = ['y_recall_success', 'y_complete_within_30m']


def evaluate_temporal_holdout(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute('SELECT * FROM pcbm_events ORDER BY user_id,created_at,id').fetchall()
    finally:
        con.close()
    df = xay_dung_ban_ghi_hoc(dong_sang_su_kien(rows))
    result = {'evaluated_at': datetime.now().isoformat(timespec='seconds'),
              'source': 'sqlite:pcbm_events', 'protocol': 'global chronological 80/20 holdout',
              'status': 'retrospective_internal_holdout_NOT_independent',
              'training_data_contains_demo_or_simulation': True,
              'limitations': 'No external/user-independent validation. No automatic support reduction authorized.',
              'total_records': int(len(df)), 'models': {}}
    for target in TARGETS:
        name = target
        work = df[df[target].notna()].copy().sort_values('decision_time').reset_index(drop=True)
        if len(work) < 60 or work[target].nunique() < 2:
            result['models'][name] = {'available': False, 'reason': 'Insufficient labelled records/classes'}
            continue
        cut = int(len(work)*0.8)
        train,test=work.iloc[:cut], work.iloc[cut:]
        if train[target].nunique()<2 or test[target].nunique()<2:
            result['models'][name] = {'available': False, 'reason': 'Only one class in temporal split'}
            continue
        cols=_cot_dac_trung(work)
        # One pre-declared baseline model for an honest fixed-protocol audit, not selection on test.
        pipe=clone(_ung_vien(cols,train[cols])['LogisticRegression'])
        pipe.fit(train[cols],train[target].astype(int))
        y=test[target].astype(int)
        prob=_xac_suat_lop_1(pipe,test[cols])
        pred=(prob>=0.5).astype(int)
        m=_metrics(y,pred,prob)
        result['models'][name] = {'available':True, 'model':'LogisticRegression (fixed baseline)',
           'train_rows':len(train),'test_rows':len(test),
           'first_test_time':str(test['decision_time'].min()),
           'last_test_time':str(test['decision_time'].max()),
           'positive_test_rate':float(y.mean()), **m}
    return result


def save_audit(db_path, output_path):
    report=evaluate_temporal_holdout(db_path)
    path=Path(output_path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--output',required=True)
    a=parser.parse_args()
    print(json.dumps(save_audit(a.db,a.output),ensure_ascii=False,indent=2))
