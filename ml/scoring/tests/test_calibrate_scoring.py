"""Minimal regression tests for probability calibration, no real credit labels."""
from pathlib import Path
import importlib.util
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibrate_scoring import (
    apply_calibrator, brier_gain_bootstrap, calibrate_experiment,
    fit_calibrator, four_way_split, metrics, reliability_points, wilson_interval,
)
from train_scoring import LABEL, extract_features, simulate_demo_labels

# Shared standalone synthetic generator is owned by the sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'synthetic_data'))
_synthetic_entry_file = Path(__file__).resolve().parents[2] / 'synthetic_data' / 'main.py'
spec_synth = importlib.util.spec_from_file_location('synthetic_generator_entry_for_calibration_tests', _synthetic_entry_file)
synthetic_entry = importlib.util.module_from_spec(spec_synth)
spec_synth.loader.exec_module(synthetic_entry)
run_pipeline = synthetic_entry.run_pipeline


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sample = run_pipeline(count=260, seed=52)
        cls.features = extract_features(sample['profiles_compliance'],sample['applications_generated'])
        lbl = simulate_demo_labels(cls.features, seed=1042)
        cls.frame = cls.features.merge(lbl[['application_id',LABEL]],on='application_id')

    def test_four_way_splits_are_disjoint_and_cover_all_rows(self):
        partitions=four_way_split(self.frame,seed=52)
        self.assertEqual(set(partitions),{'train','val','calibration','test'})
        all_idx=np.concatenate(list(partitions.values()))
        self.assertEqual(len(all_idx),len(np.unique(all_idx)))
        self.assertEqual(len(all_idx),len(self.frame))
        ids=[set(self.frame.iloc[ix].borrower_id) for ix in partitions.values()]
        self.assertFalse(any(ids[i]&ids[j] for i in range(4) for j in range(i+1,4)))
        for ix in partitions.values():
            self.assertEqual(len(np.unique(self.frame.iloc[ix][LABEL])),2)

    def test_platt_and_isotonic_probabilities_bounded(self):
        p=np.array([0.01,0.02,0.06,0.10,0.20,0.3,0.5,0.7])
        y=np.array([0,0,0,0,1,1,0,1])
        for method in ['platt','isotonic']:
            calibrator=fit_calibrator(method,p,y)
            predictions=apply_calibrator(method,calibrator,p)
            self.assertTrue(((predictions>0)&(predictions<1)).all())
            self.assertTrue((np.diff(predictions)>=-1e-9).all())

    def test_isotonic_handles_constant_probabilities(self):
        p=np.ones(30)*0.2
        y=np.array([0]*20+[1]*10)
        model=fit_calibrator('isotonic',p,y)
        out=apply_calibrator('isotonic',model,p)
        self.assertAlmostEqual(out.mean(),1/3,places=5)
        bins=reliability_points(y,p,n_bins=8)
        self.assertEqual(len(bins),1)

    def test_wilson_interval_contains_sample_fraction(self):
        low,high=wilson_interval(np.array([5,0,10]),np.array([10,10,10]))
        self.assertTrue((low<=np.array([0.5,0.0,1.0])).all())
        self.assertTrue((high+1e-12>=np.array([0.5,0.0,1.0])).all())

    def test_brier_gain_positive_for_better_predictions(self):
        y=np.array([0,0,1,1]); raw=np.array([.4,.5,.5,.6]); improved=np.array([.1,.1,.9,.9])
        gain,ci=brier_gain_bootstrap(y,raw,improved,np.array(['a','b','c','d']),seed=42,n_boot=100)
        self.assertGreater(gain,0)
        self.assertGreater(ci[0],0)
        self.assertGreater(metrics(y,raw)['brier'],metrics(y,improved)['brier'])

    def test_one_model_end_to_end(self):
        results,table,parts=calibrate_experiment(self.frame,seed=52,models=('logistic',))
        self.assertEqual(set(table.calibration),{'raw','platt','isotonic'})
        self.assertEqual(len(results['logistic']['test_predictions']['raw']),len(parts['test']))

if __name__=='__main__':
    unittest.main()
