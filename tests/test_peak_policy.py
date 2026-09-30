import math
import unittest
from helpers import logger
from peak_detection import PeakDetectionConfig, PeakFlowDetector, centred_moving_average

def sample(i, value, **changes):
    base=dict(seq=i,ms=i*10,t_s=i*.01,host_unix=0,flow_raw=value,flow_avg=value,
              flow_ok=True,flow_age_us=100,pa=[20.0]*7,temp=25,pok=[True]*7,
              pa_age_us=[100]*7,cmd_dac=1450,feedback_dac=1450,cmd_pct=0,fdbk_pct=0,
              target_flow_slm=0,target_peak_slm=10,phase=0,preset=0,clamped=False,
              run_id='0123456789abcdef',scan_id=i,row_us=i*10000,cycle_id=3,
              scan_start_us=i*10000-500,missed_slots_total=0,tx_dropped_total=0,
              row_time_us=i*10000,flow_time_us=i*10000,pa_time_us=[i*10000]*7,
              segment_id=0,discontinuity_reason='',target_reference_resolved=True,target_peak_local_lmin=10)
    base.update(changes)
    return logger.Sample(**base)

def detect(values, config=None, modify=None):
    events=[];d=PeakFlowDetector(config or PeakDetectionConfig())
    for i,v in enumerate([0]+values+[0]):
        s=sample(i,v)
        if modify:s=modify(s)
        events.extend(d.push(s))
    return d,events

class Policy(unittest.TestCase):
    def test_even_and_short_windows(self):
        with self.assertRaises(ValueError):PeakDetectionConfig(smooth_window=8)
        with self.assertRaises(ValueError):PeakDetectionConfig(smooth_window=11)
        for n in range(5,9):
            d,ev=detect([10]*n);self.assertFalse(ev);self.assertEqual(d.discarded,1)
        d,ev=detect([10]*9);self.assertEqual(len(ev),1)
        self.assertEqual(ev[0]['interpolation_status'],'unsupported_neighbours')
    def test_supported_edges(self):
        sm=centred_moving_average([10]+[9]*16+[10],9)
        self.assertTrue(math.isnan(sm[0]));self.assertTrue(math.isnan(sm[-1]))
        d,ev=detect([10]+[9]*16+[10]);self.assertNotIn(ev[0]['sample'].seq,(1,18))
    def test_plateau_reference(self):
        cfg=PeakDetectionConfig(smooth_window=1,min_samples=5)
        d,ev=detect([4,10,9,4,4],cfg)
        self.assertEqual(ev[0]['plateau_reference_flow_slm'],10)
        self.assertAlmostEqual(ev[0]['flow_peak_slm'],10.4464285714)
    def test_pressure_clamp_disjoint(self):
        cfg=PeakDetectionConfig(smooth_window=1,min_samples=5)
        for modify in [lambda s:s._replace(pok=[s.seq==5]*7),
                       lambda s:s._replace(clamped=s.seq==2),
                       lambda s:s._replace(pa_age_us=[30000]*7)]:
            d,ev=detect([10]*10,cfg,modify)
            self.assertFalse(ev[0]['qualified_peak'])
        d,ev=detect([10,4,4,10,4],cfg)
        self.assertFalse(ev[0]['plateau_contiguous']);self.assertFalse(ev[0]['qualified_peak'])
    def test_populations(self):
        cfg=PeakDetectionConfig(smooth_window=1,min_samples=5)
        d,ev=detect([10]*10,cfg,lambda s:s._replace(cycle_id=1))
        self.assertEqual(d.warmup_peaks,1);self.assertEqual(d.target_passes,0)
        self.assertIsNone(ev[0]['qualified_peak'])
        d,ev=detect([10]*10,cfg,lambda s:s._replace(target_reference_resolved=False))
        self.assertIsNone(ev[0]['target_met']);self.assertEqual(d.target_misses,0)
    def test_plateau_failure_counts_outside_peak(self):
        cfg=PeakDetectionConfig(smooth_window=1,min_samples=5)
        d,ev=detect([10]*10,cfg,lambda s:s._replace(pok=[s.seq!=3]*7))
        self.assertTrue(ev[0]['peak_sample_ok']);self.assertFalse(ev[0]['qualified_peak'])
        self.assertEqual(d.pressure_incomplete,1)
        d,ev=detect([10]*10,cfg,lambda s:s._replace(pa_age_us=[30000 if s.seq==3 else 100]*7))
        self.assertEqual(d.timing_failures,1)
