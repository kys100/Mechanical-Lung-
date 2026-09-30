import tempfile
import unittest
from helpers import logger, link
from peak_detection import PeakDetectionConfig
class Baseline(unittest.TestCase):
    def test_config(self):
        for kw in ({'min_samples': True}, {'threshold_frac': float('nan')}, {'warmup_breaths': -1}):
            with self.assertRaises(ValueError): PeakDetectionConfig(**kw)
    def test_wrap_reset(self):
        c=logger.MillisUnwrapper(); c.update(0xfffffff0)
        self.assertEqual(c.update(20), (.036, False))
        self.assertTrue(c.update(10)[1])
    def test_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            a=logger.open_unique_csv_pair(d,'run'); b=logger.open_unique_csv_pair(d,'run')
            self.assertNotEqual(a[0], b[0])
            for f in a[2:]+b[2:]: f.close()
    def test_generation(self):
        s=link(); s._on_run_timeout(100)
        self.assertFalse(s.ser.writes)
