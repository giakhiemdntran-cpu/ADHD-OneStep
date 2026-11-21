import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from dich_vu.pcbm_review_policy import evaluate

class TestReviewPolicy(unittest.TestCase):
    def test_insufficient_history_blocks(self):
        with patch('dich_vu.pcbm_review_policy.history_evidence',return_value={'enough':False,'reason':'insufficient'}):
            self.assertFalse(evaluate('u',2,1,True)['eligible'])
    def test_unvalidated_reduction_blocks(self):
        with patch('dich_vu.pcbm_review_policy.history_evidence',return_value={'enough':True}), patch('dich_vu.pcbm_review_policy.independent_reduction_gate',return_value=(False,'no review')):
            self.assertFalse(evaluate('u',2,1,True)['eligible'])
    def test_user_can_approve_increase(self):
        with patch('dich_vu.pcbm_review_policy.history_evidence',return_value={'enough':True}):
            self.assertTrue(evaluate('u',0,1,True)['eligible'])
    def test_unloaded_models_block(self):
        with patch('dich_vu.pcbm_review_policy.history_evidence',return_value={'enough':True}):
            self.assertFalse(evaluate('u',0,1,False)['eligible'])
if __name__=='__main__': unittest.main()
