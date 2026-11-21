import sys, unittest, types
sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime
from pcbm_thu_thap_bang_chung import _thoi_gian_dia_phuong, _so_giay_da_qua

class TestDatetime(unittest.TestCase):
    def test_local_naive(self):
        self.assertEqual(_thoi_gian_dia_phuong('2026-11-21T12:00:00'), datetime(2026,11,21,12))
    def test_aware_utc(self):
        self.assertEqual(_thoi_gian_dia_phuong('2026-11-21T05:00:00+00:00'), datetime(2026,11,21,12))
    def test_z_suffix(self):
        self.assertEqual(_so_giay_da_qua(datetime(2026,11,21,12,30), '2026-11-21T05:00:00Z'), 1800)
    def test_vietnam_aware(self):
        self.assertEqual(_so_giay_da_qua(datetime(2026,11,21,12,30), '2026-11-21T12:00:00+07:00'), 1800)

if __name__ == '__main__': unittest.main()
