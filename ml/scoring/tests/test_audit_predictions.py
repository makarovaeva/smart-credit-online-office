import unittest
from audit_predictions import wilson_interval, calibration_bins
import numpy as np


class AuditTests(unittest.TestCase):
    def test_wilson_bounds_and_invalid_counts(self):
        low, high = wilson_interval(5, 20)
        self.assertTrue(0 <= low < .25 < high <= 1)
        with self.assertRaises(ValueError):
            wilson_interval(2, 1)

    def test_tied_scores_are_not_split_across_bins(self):
        y = np.array([0,1,0,1,0,0,1,0,0,1])
        p = np.array([.1,.1,.1,.1,.2,.2,.3,.3,.3,.3])
        result = calibration_bins(y,p,'test',n_bins=5)
        self.assertEqual(result.n.sum(),10)
        self.assertLessEqual(len(result),5)
        self.assertTrue((result.wilson_low <= result.observed_frequency).all())
        self.assertTrue((result.wilson_high >= result.observed_frequency).all())


if __name__ == '__main__':
    unittest.main()
