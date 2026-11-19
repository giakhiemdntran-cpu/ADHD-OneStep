import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung

class FeedbackFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2026,11,19,9,0,0)
        self.decision={'timestamp':self.t,'user_id':'user01','task_id':'math','occurrence_id':'math1',
                       'event_type':'REMINDER_SENT','data':{'reminder_type':'generic','prompt_level':1}}
    def feedback(self, days, typ, preference, uid='user01', **kw):
        return {'timestamp':self.t+timedelta(days=days),'user_id':uid,'task_id':'math',
                'occurrence_id':'math1','event_type':typ,
                'data':{'user_preference':preference, **kw}}
    def test_empty(self):
        f=xay_dung_dac_trung([self.decision],self.decision)
        self.assertEqual(f['user_feedback_count_30d'],0)
        self.assertEqual(f['user_feedback_last_action'],'none')
    def test_only_past_same_user_real(self):
        events=[self.decision,
            self.feedback(-3,'SUPPORT_ACCEPTED','accept',final_level=2),
            self.feedback(-2,'SUPPORT_REJECTED','keep',final_level=2),
            self.feedback(-1,'SUPPORT_LESS_REQUESTED','request_less',final_level=2),
            self.feedback(1,'SUPPORT_MORE_REQUESTED','request_more'),
            self.feedback(-1,'SUPPORT_MORE_REQUESTED','request_more',uid='other'),
            self.feedback(-1,'SUPPORT_ACCEPTED','accept',simulation=True),
            self.feedback(-45,'SUPPORT_ACCEPTED','accept')]
        f=xay_dung_dac_trung(events,self.decision)
        self.assertEqual(f['user_feedback_count_30d'],3)
        self.assertEqual(f['user_feedback_keep_count_30d'],1)
        self.assertEqual(f['user_feedback_less_count_30d'],1)
        self.assertEqual(f['user_feedback_more_count_30d'],0)
        self.assertEqual(f['user_feedback_last_action'],'request_less')
        self.assertEqual(f['user_feedback_last_final_level'],2)
        self.assertAlmostEqual(f['user_feedback_accept_rate_30d'],1/3)
    def test_feedback_not_label(self):
        from huan_luyen_pcbm.xay_dung_nhan import xay_dung_nhan
        e=self.feedback(0.0005,'SUPPORT_ACCEPTED','accept')
        y=xay_dung_nhan([self.decision,e],self.decision)
        self.assertIsNone(y['y_recall_success'])
        self.assertEqual(y['y_complete_within_30m'],0)

if __name__=='__main__':unittest.main()
