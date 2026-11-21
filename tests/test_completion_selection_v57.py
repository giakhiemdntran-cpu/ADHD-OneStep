import unittest
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from huan_luyen_pcbm.huan_luyen_tu_csdl import _chon_nguong_tu_qua_khu, _ung_vien

class CompletionThresholdTests(unittest.TestCase):
    def test_small_sample_falls_back_safely(self):
        X = pd.DataFrame({"x": [0.,1.]*10})
        y = pd.Series([0,1]*10)
        model = _ung_vien(["x"], X)["LogisticRegression"]
        self.assertEqual(_chon_nguong_tu_qua_khu(model,X,y),0.5)

    def test_large_sample_keeps_threshold_in_valid_range(self):
        rng=np.random.default_rng(7)
        X=pd.DataFrame({"x":rng.normal(size=240)})
        y=pd.Series((X.x+rng.normal(scale=0.8,size=240)>0).astype(int))
        model=_ung_vien(["x"],X)["LogisticRegression"]
        threshold=_chon_nguong_tu_qua_khu(model,X,y)
        self.assertGreaterEqual(threshold,0.15)
        self.assertLessEqual(threshold,0.85)

    def test_four_v4_candidates_preserved(self):
        X=pd.DataFrame({"x": [0.,1.]})
        names=set(_ung_vien(["x"],X))
        self.assertEqual(names,{"DummyPrior","LogisticRegression","RandomForestClassifier","GradientBoostingClassifier"})

if __name__=="__main__": unittest.main()
