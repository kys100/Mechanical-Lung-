import math
import tempfile
import unittest
from helpers import link, recording, wire, RID, logger
from peak_detection import PeakFlowDetector, PeakDetectionConfig
class Continuity(unittest.TestCase):
    def test_dropped_falling_fragment_and_next_breath(self):
        with tempfile.TemporaryDirectory() as d:
            s=link(gas_temperature_c=20,absolute_pressure_mbar=1013);recording(s,d)
            events=[];s._detector=PeakFlowDetector(s.peak_config,events.append)
            for i in range(410):
                j=i%205
                f=10*math.sin(math.pi*j/200) if j<=200 else 0
                s._handle_data_line(wire(i,f,flow_ok=0 if i==140 else 1))
            self.assertEqual(len(events),2)
            self.assertFalse(events[0]['excursion_complete'])
            self.assertTrue(events[1]['excursion_complete'])
            self.assertTrue(events[1]['qualified_peak'])
            s._fault('test_end')
    def test_missing_seq_time_and_initial_high(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);events=[];s._detector=PeakFlowDetector(s.peak_config,events.append)
            for i in range(25):s._handle_data_line(wire(i,10))
            self.assertFalse(events);self.assertFalse(s._detector._buf)
            s._handle_data_line(wire(25,0))
            for i in range(26,50):s._handle_data_line(wire(i,10))
            s._handle_data_line(wire(150,8));s._handle_data_line(wire(151,0))
            self.assertEqual(len(events),1);self.assertFalse(events[0]['excursion_complete'])
            self.assertEqual(s._run_dropped_rows,100)
            s._fault('test_end')
    def test_nan_recovery_and_average_reset(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            s._handle_data_line(wire(0,10));s._handle_data_line(wire(1,float('nan')))
            s._handle_data_line(wire(2,0));self.assertEqual(s._last_sample.flow_avg,0)
            self.assertEqual(s._run_bad_lines,1)
            s._fault('test_end')
