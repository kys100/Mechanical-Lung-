import unittest
from peak_detection import interpolate_peak, PeakDetectionConfig, PeakFlowDetector
from test_peak_policy import sample
class Timing(unittest.TestCase):
    def test_actual_time_parabola(self):
        for times in [(-.01,0,.01),(-.008,0,.012)]:
            values=[10-1000*(t-.002)**2 for t in times]
            dt,y,status=interpolate_peak(times,values)
            self.assertAlmostEqual(dt,.002);self.assertAlmostEqual(y,10)
            self.assertEqual(status,'interpolated')
    def test_nonmonotonic_rejected(self):
        self.assertEqual(interpolate_peak((0,0,1),(9,10,9))[2],'nonmonotonic_time')
    def test_nonpositive_time_breaks(self):
        events=[];d=PeakFlowDetector(PeakDetectionConfig(smooth_window=1,min_samples=5),events.append)
        d.push(sample(0,0))
        for i in range(1,10):d.push(sample(i,10))
        d.push(sample(10,10,t_s=.09))
        self.assertFalse(events[0]['excursion_complete'])
    def test_host_micros_wrap_and_age_shift(self):
        import tempfile
        from unittest.mock import patch
        from helpers import link, recording, wire, RID, logger, FakeTimer
        with tempfile.TemporaryDirectory() as directory:
            s=link();recording(s,directory)
            s._reset_analysis_state(4294900,0xffff0000)
            p=wire(0).split(',');p[2]='4294910';p[39]=str((0xffff0000+10000)&0xffffffff);p[5]='1234'
            s._handle_data_line(','.join(p))
            self.assertEqual(s._last_sample.flow_time_us,8766)
            p=wire(1).split(',');p[2]='4294980';p[39]=str((0xffff0000+80000)&0xffffffff)
            s._handle_data_line(','.join(p))
            self.assertEqual(s._last_sample.row_time_us,80000)
            self.assertEqual(s._last_sample.discontinuity_reason,'flow_time_discontinuity')
            s._fault('test_end')
