import tempfile, unittest
from datetime import date,timedelta
from pathlib import Path
from dich_vu.pcbm_review_store import ReviewStore
from dich_vu.pcbm_human_loop import decide_support

class TestReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ReviewStore(Path(self.tmp.name)/'rev.sqlite3')
        self.today=date(2026,11,17)
    def tearDown(self): self.tmp.cleanup()
    def test_three_days_then_prompt(self):
        for n in [2,1]:
            self.store.observe('u',1,0,(self.today-timedelta(days=n)).isoformat())
        self.assertFalse(self.store.should_offer('u',1,0,self.today))
        self.store.observe('u',1,0,self.today.isoformat())
        self.assertTrue(self.store.should_offer('u',1,0,self.today))
    def test_different_user_isolated(self):
        for n in [2,1,0]: self.store.observe('u',1,2,(self.today-timedelta(days=n)).isoformat())
        self.assertFalse(self.store.should_offer('v',1,2,self.today))
    def test_missing_day_breaks_streak(self):
        for n in [3,1,0]: self.store.observe('u',1,2,(self.today-timedelta(days=n)).isoformat())
        self.assertFalse(self.store.should_offer('u',1,2,self.today))
    def test_demo_is_isolated(self):
        self.store.save_demo_choice('DEMO_HITL_REVIEW',2,'request_more')
        self.assertEqual(self.store.get_demo_choice('DEMO_HITL_REVIEW'),2)
        self.store.reset_demo('DEMO_HITL_REVIEW')
        self.assertEqual(self.store.get_demo_choice('DEMO_HITL_REVIEW'),1)
    def test_reduce_blocked(self):
        d=decide_support(1,0,'accept',independently_validated=False,evidence_of_independence=False)
        self.assertEqual(d.final_level,1)
    def test_refuse_reduce(self):
        self.assertEqual(decide_support(1,0,'keep').final_level,1)
    def test_more_is_user_led(self):
        self.assertEqual(decide_support(1,0,'request_more').final_level,2)

if __name__=='__main__': unittest.main()
