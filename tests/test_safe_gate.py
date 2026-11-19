import unittest
from dich_vu.pcbm_safety_gate import check_gate

class TestSafeGate(unittest.TestCase):
    def test_low_auc_stays_blocked(self):
        r=check_gate({'roc_auc':0.536,'test_rows':250},{'observed_tasks':30,'observation_days':20,'independent_starts':28},independent_validated=True,consent=True)
        self.assertFalse(r.eligible_for_decrease)
    def test_no_external_approval(self):
        r=check_gate({'roc_auc':0.85,'test_rows':250},{'observed_tasks':30,'observation_days':20,'independent_starts':28},consent=True)
        self.assertFalse(r.eligible_for_decrease)
    def test_no_consent(self):
        r=check_gate({'roc_auc':0.85,'test_rows':250},{'observed_tasks':30,'observation_days':20,'independent_starts':28},independent_validated=True)
        self.assertFalse(r.eligible_for_decrease)
    def test_positive_only_when_all_criteria(self):
        r=check_gate({'roc_auc':0.85,'test_rows':250},{'observed_tasks':30,'observation_days':20,'independent_starts':28},independent_validated=True,consent=True)
        self.assertTrue(r.eligible_for_decrease)
    def test_demo_blocked(self):
        r=check_gate({'roc_auc':0.9,'test_rows':250},{'observed_tasks':30,'observation_days':20,'independent_starts':28},independent_validated=True,consent=True,is_demo=True)
        self.assertFalse(r.eligible_for_decrease)

if __name__=='__main__': unittest.main()
