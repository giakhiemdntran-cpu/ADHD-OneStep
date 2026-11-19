import unittest
from dich_vu.pcbm_human_loop import decide_support

class HumanLoopTests(unittest.TestCase):
    def test_refuse_increase(self):
        d = decide_support(1, 2, 'keep')
        self.assertEqual(d.final_level, 1)
    def test_consent_increase(self):
        d = decide_support(1, 2, 'accept')
        self.assertEqual(d.final_level, 2)
    def test_reduce_not_trusted_even_with_consent(self):
        d = decide_support(1, 0, 'accept')
        self.assertEqual(d.final_level, 1)
    def test_user_requests_less_remains(self):
        d = decide_support(2, 1, 'request_less')
        self.assertEqual(d.final_level, 2)
    def test_user_requests_more(self):
        d = decide_support(1, 0, 'request_more')
        self.assertEqual(d.final_level, 2)
    def test_undecided(self):
        self.assertEqual(decide_support(1, 2, 'undecided').final_level, 1)

if __name__ == '__main__':
    unittest.main()
