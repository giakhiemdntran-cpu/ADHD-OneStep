import unittest
from datetime import datetime, timedelta
from huan_luyen_pcbm.xay_dung_nhan import xay_dung_nhan

class TestLabelV5(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2026,1,1,19,0)
    def e(self, typ, mins, data=None, eid=None):
        return {'timestamp':self.t+timedelta(minutes=mins),'user_id':'u1',
                'occurrence_id':'o1','task_id':'task','event_type':typ,
                'data':data or {},'event_id':eid or f'DB{mins}'}
    def reminder(self):
        return self.e('REMINDER_SENT',0,{'reminder_type':'generic'},'DB10')
    def window(self):
        return self.e('ITI_WINDOW_OPENED',0,{},'DB20')
    def test_cue_yes(self):
        d=self.reminder();self.assertEqual(xay_dung_nhan([d,self.e('RECALL_SUCCESS',1)],d)['y_cue_assisted_recall'],1)
    def test_cue_not_independent(self):
        d=self.reminder();self.assertIsNone(xay_dung_nhan([d,self.e('RECALL_SUCCESS',1)],d)['y_independent_task_initiation'])
    def test_completion_unknown(self):
        d=self.reminder();self.assertIsNone(xay_dung_nhan([d],d)['y_complete_within_30m_verified'])
    def test_completion_positive(self):
        d=self.reminder();self.assertEqual(xay_dung_nhan([d,self.e('TASK_COMPLETED',20)],d)['y_complete_within_30m_verified'],1)
    def test_completion_verified_negative(self):
        d=self.reminder();verified=self.e('OBSERVATION_WINDOW_VERIFIED',31,{
            'reminder_event_id':'DB10','continuous_observation':True,
            'verified_no_completion':True,'reviewed_by':'observer','evidence_source':'live log'})
        self.assertEqual(xay_dung_nhan([d,verified],d)['y_complete_within_30m_verified'],0)
    def test_completion_insufficient_negative(self):
        d=self.reminder();close=self.e('OBSERVATION_WINDOW_VERIFIED',31,{'continuous_observation':True})
        self.assertIsNone(xay_dung_nhan([d,close],d)['y_complete_within_30m_verified'])
    def test_iti_positive(self):
        w=self.window();start=self.e('TASK_STARTED',10,{
            'source':'user_action','trigger':'self_initiated','independent_verified':True})
        self.assertEqual(xay_dung_nhan([w,start],w)['y_independent_task_initiation'],1)
    def test_iti_negative(self):
        w=self.window();neg=self.e('ITI_OBSERVATION_VERIFIED',31,{
            'window_event_id':'DB20','continuous_observation':True,'no_unprompted_start':True,
            'reviewed_by':'observer','evidence_source':'live log'})
        self.assertEqual(xay_dung_nhan([w,neg],w)['y_independent_task_initiation'],0)
    def test_iti_prompt_before_close_is_unknown(self):
        w=self.window();r=self.e('REMINDER_SENT',5)
        neg=self.e('ITI_OBSERVATION_VERIFIED',31,{
            'window_event_id':'DB20','continuous_observation':True,'no_unprompted_start':True,
            'reviewed_by':'observer','evidence_source':'live log'})
        self.assertIsNone(xay_dung_nhan([w,r,neg],w)['y_independent_task_initiation'])
    def test_iti_not_verified_unknown(self):
        w=self.window();started=self.e('TASK_STARTED',10,{'source':'user_action'})
        self.assertIsNone(xay_dung_nhan([w,started],w)['y_independent_task_initiation'])
    def test_iti_existing_prompt_unknown(self):
        w=self.window();cue=self.e('REMINDER_SENT',-10)
        self.assertIsNone(xay_dung_nhan([cue,w],w)['y_independent_task_initiation'])

if __name__=='__main__':unittest.main()
