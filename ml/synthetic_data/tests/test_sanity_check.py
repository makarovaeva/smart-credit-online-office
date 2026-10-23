import unittest
from sanity_check import audit, longest_negative_streak


class SanityCheckTests(unittest.TestCase):
    def test_streak(self):
        self.assertEqual(longest_negative_streak([2, -1, -1, 4, -3, -4, -5]), 3)

    def test_empty_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            audit([])
