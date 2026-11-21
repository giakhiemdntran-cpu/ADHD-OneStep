import unittest
from datetime import datetime,timezone,timedelta
import pandas as pd
from huan_luyen_pcbm.pcbm_dataset_v5_2 import _split_by_users,build_audit

class DatasetV52Tests(unittest.TestCase):
    def test_user_split_disjoint_and_deterministic(self):
        x=[f'u{i}' for i in range(40)]
        a=_split_by_users(x);b=_split_by_users(x[::-1])
        self.assertEqual(a,b)
        self.assertEqual({k:sum(v==k for v in a.values()) for k in ['train','validation','test']},{'train':24,'validation':8,'test':8})
    def test_no_unknown_to_negative(self):
        t=datetime(2026,1,1,tzinfo=timezone.utc)
        e={'event_id':'DB1','user_id':'test_01','task_id':'T','occurrence_id':'O','event_type':'TASK_CREATED','timestamp':t,'data':{}}
        df=pd.DataFrame([{'user_id':'test_01','source_event_id':'DB1','occurrence_id':'O','decision_time':t.isoformat(),'is_demo':True, 'y_cue_assisted_recall':None,'y_independent_task_initiation':None,'y_complete_within_30m_verified':None}])
        got=build_audit([e],df)
        self.assertTrue(pd.isna(got['y_independent_task_initiation'][0]))
        self.assertTrue(pd.isna(got['y_complete_within_30m_verified'][0]))
    def test_cue_requires_event_evidence(self):
        t=datetime(2026,1,1,tzinfo=timezone.utc)
        a={'event_id':'DB1','user_id':'test_01','task_id':'T','occurrence_id':'O','event_type':'REMINDER_SENT','timestamp':t,'data':{'reminder_type':'generic'}}
        b={'event_id':'DB2',**{k:a[k] for k in ['user_id','task_id','occurrence_id']},'event_type':'RECALL_SUCCESS','timestamp':t+timedelta(seconds=35),'data':{}}
        df=pd.DataFrame([{'user_id':'test_01','source_event_id':'DB1','occurrence_id':'O','decision_time':t.isoformat(),'is_demo':True,'y_cue_assisted_recall':1,'y_independent_task_initiation':None,'y_complete_within_30m_verified':None}])
        got=build_audit([a,b],df)
        self.assertEqual(got['y_cue_assisted_recall_evidence_event_ids'][0],'DB2')
        self.assertEqual(got['y_cue_assisted_recall'][0],1)

if __name__=='__main__':unittest.main()
