import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import sys, types
sys.modules.setdefault('streamlit', types.ModuleType('streamlit'))
import pcbm_playground_y_kien as fb
class FeedbackPlaygroundTest(unittest.TestCase):
    def test_choose(self):
        self.assertEqual(fb.decide_level(1,0,'keep'),1)
        self.assertEqual(fb.decide_level(1,0,'accept'),0)
        self.assertEqual(fb.decide_level(1,0,'more'),2)
        self.assertEqual(fb.decide_level(1,0,'less'),0)
        self.assertEqual(fb.decide_level(1,0,'later'),1)
    def test_sqlite_is_separate(self):
        with TemporaryDirectory() as folder:
            with patch.object(fb, 'DEMO_DB', Path(folder)/'demo.db'):
                fb.save_demo_feedback('test_U036',1,0,'keep',note='giữ')
                rows=fb.get_demo_feedback('test_U036')
                self.assertEqual(rows[0]['after_level'],1)
                self.assertEqual(len(rows),1)
                fb.reset_demo_feedback('test_U036')
                self.assertEqual(fb.get_demo_feedback('test_U036'),[])
if __name__=='__main__': unittest.main()
