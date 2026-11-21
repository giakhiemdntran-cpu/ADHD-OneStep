import unittest
from datetime import datetime, timedelta
from huan_luyen_pcbm.nhan_v5 import tao_nhan_v5, ap_dung_kiem_tra_coverage

T=datetime(2026,11,20,10)
def ev(kind, minute, data=None):
    return {'user_id':'u1','occurrence_id':'o1','event_type':kind,'timestamp':T+timedelta(minutes=minute),'data':data or {}}
D=ev('REMINDER_SENT',0,{'reminder_type':'generic'})
class TestLabels(unittest.TestCase):
    def test_generic_recall_is_not_spontaneous(self):
        v=tao_nhan_v5([D,ev('RECALL_SUCCESS',1)],D,T+timedelta(minutes=35))
        self.assertEqual(v['recall_after_cue'],1); self.assertIsNone(v['independent_recall'])
    def test_missing_completion_without_coverage_is_unknown(self):
        v=tao_nhan_v5([D],D,T+timedelta(minutes=40))
        v=ap_dung_kiem_tra_coverage(v,observed_continuously=False)
        self.assertIsNone(v['completed_within_30m'])
    def test_complete_detected(self):
        v=tao_nhan_v5([D,ev('TASK_COMPLETED',20)],D,T+timedelta(minutes=40))
        self.assertEqual(v['completed_within_30m'],1)
    def test_short_followup_is_unknown(self):
        v=tao_nhan_v5([D],D,T+timedelta(minutes=3))
        self.assertIsNone(v['completed_within_30m'])
    def test_spontaneous_only_if_explicit_evidence(self):
        v=tao_nhan_v5([ev('USER_REMEMBERED',-1,{'evidence_source':'self_initiated_report'}),D],D,T+timedelta(minutes=31),previous_prompt_time=T-timedelta(minutes=20))
        self.assertEqual(v['independent_recall'],1)
    def test_demo_cannot_be_spontaneous(self):
        v=tao_nhan_v5([ev('USER_REMEMBERED',-1,{'evidence_source':'self_initiated_report','is_demo':True}),D],D,T+timedelta(minutes=31),previous_prompt_time=T-timedelta(minutes=20))
        self.assertIsNone(v['independent_recall'])
if __name__=='__main__':unittest.main()
