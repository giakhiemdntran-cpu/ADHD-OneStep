from datetime import datetime,timedelta,timezone
import unittest
from huan_luyen_pcbm.pcbm_mix_v5 import _label_iti,_label_reminder,build_dataframe
T=datetime(2026,10,1,9,tzinfo=timezone.utc)

def ev(kind,m,oid='A',data=None):
 return {'event_id':f'{kind}{m}','event_type':kind,'timestamp':T+timedelta(minutes=m),'user_id':'real_user','task_id':'taskA','occurrence_id':oid,'data':data or {}}
class TestMixedLabels(unittest.TestCase):
 def test_iti_positive_proved(self):
  c=ev('TASK_CREATED',0, data={'task_type':'homework'});seq=[c,ev('TASK_STARTED',4,data={'evidence_source':'user_initiated_action'}),ev('REMINDER_SENT',10)]
  self.assertEqual(_label_iti(seq,c)[0],1)
 def test_iti_unknown_without_evidence(self):
  c=ev('TASK_CREATED',0);seq=[c,ev('TASK_STARTED',4),ev('REMINDER_SENT',10)]
  self.assertIsNone(_label_iti(seq,c)[0])
 def test_demo_not_positive(self):
  c=ev('TASK_CREATED',0);seq=[c,ev('TASK_STARTED',4,data={'evidence_source':'user_initiated_action','is_demo':True}),ev('REMINDER_SENT',10)]
  self.assertIsNone(_label_iti(seq,c)[0])
 def test_iti_verified_negative(self):
  c=ev('TASK_CREATED',0);seq=[c,ev('REMINDER_SENT',10),ev('OBSERVATION_VERIFIED',11,data={'verified_continuous_coverage':True,'coverage_start':T.isoformat(),'coverage_end':(T+timedelta(minutes=10)).isoformat()})]
  self.assertEqual(_label_iti(seq,c)[0],0)
 def test_no_false_negative_without_coverage_window(self):
  c=ev('TASK_CREATED',0);seq=[c,ev('REMINDER_SENT',10),ev('OBSERVATION_VERIFIED',11,data={'verified_continuous_coverage':True})]
  self.assertIsNone(_label_iti(seq,c)[0])
 def test_recall_after_generic(self):
  r=ev('REMINDER_SENT',10,data={'reminder_type':'generic'});s=[r,ev('RECALL_SUCCESS',11)]
  self.assertEqual(_label_reminder(s,r)[0],1)
 def test_completion_unknown_missing_coverage(self):
  r=ev('REMINDER_SENT',10,data={'reminder_type':'generic'});self.assertIsNone(_label_reminder([r],r)[1])
 def test_completion_positive(self):
  r=ev('REMINDER_SENT',10);self.assertEqual(_label_reminder([r,ev('TASK_COMPLETED',20)],r)[1],1)
 def test_iti_metadata_at_creation(self):
  c=ev('TASK_CREATED',0,data={'task_type':'homework','priority':2,'estimated_minutes':15});r=ev('REMINDER_SENT',10)
  df=build_dataframe([c,r]);row=df.loc[df.decision_type=='TASK_CREATED'].iloc[0]
  self.assertEqual(row.task_type,'homework')
if __name__=='__main__':unittest.main()
