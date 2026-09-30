import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from helpers import link, recording, wire, RID, logger
from test_peak_policy import sample
from peak_detection import PeakDetectionConfig

class Reporting(unittest.TestCase):
    def test_invalid_plot_gaps_and_axes(self):
        s=link();s._plot_sample(sample(1,10,flow_ok=False,pok=[False]*7))
        self.assertTrue(logger.math.isnan(s.flow_raw[-1]))
        self.assertTrue(logger.math.isnan(s.psens_pa[0][-1]))
        fig,ax=logger.plt.subplots();logger.autoscale(ax,[float('nan'),float('inf')])
        self.assertTrue(all(logger.math.isfinite(v) for v in ax.get_ylim()))
        logger.plt.close(fig)
    def test_start_clears_old_plot_time(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();s._plot_sample(sample(100,10))
            recording(s,d);self.assertFalse(s.t)
            s._fault('test_end')
    def test_analysis_error_classification(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            s._detector.push=lambda sample:(_ for _ in ()).throw(ValueError('detector bug'))
            output=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):
                s._handle_data_line(wire())
            self.assertEqual(s.state,'FAULTED');self.assertIn('analysis_fault',output.getvalue())
            self.assertNotIn('file I/O',output.getvalue())
    def test_storage_failure_manifest_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d)
            original=s._record_file
            class BrokenFlush:
                def flush(self):raise OSError('disk full')
                def close(self):original.close()
            s._record_file=BrokenFlush()
            s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            manifest=json.loads(Path(paths[2]).read_text())
            self.assertFalse(manifest['complete']);self.assertEqual(manifest['termination_reason'],'storage_fault')
    def test_phase_population_and_orientation(self):
        cfg=PeakDetectionConfig(smooth_window=1,min_samples=5)
        with tempfile.TemporaryDirectory() as d:
            s=link(peak_config=cfg,gas_temperature_c=20,absolute_pressure_mbar=1013,
                   expected_expiration_sign='negative')
            recording(s,d)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                for i,f in enumerate([0]+[10]*10+[0]):s._handle_data_line(wire(i,f))
                for i,f in enumerate([0]+[10]*10+[0],12):s._handle_data_line(wire(i,f,cycle_id=5))
            self.assertEqual(s.orientation_mismatches,2)
            self.assertEqual(output.getvalue().count('disagrees'),1)
            self.assertEqual(s._phase_summary()['missing_interior'],3)
            s._fault('test_end')
    def test_each_csv_stream_failure_is_storage_fault(self):
        for stream in ('samples','peaks'):
            with tempfile.TemporaryDirectory() as d:
                s=link(peak_config=PeakDetectionConfig(smooth_window=1,min_samples=5))
                recording(s,d)
                class BrokenWriter:
                    def writerow(self, row):raise OSError('disk full')
                if stream=='samples':s._record_writer=BrokenWriter()
                else:s._peak_writer=BrokenWriter()
                for i,f in enumerate([0]+[10]*10+[0]):
                    s._handle_data_line(wire(i,f))
                    if s.state=='FAULTED':break
                self.assertEqual(s.state,'FAULTED')
                self.assertEqual(s.manifest['termination_reason'],'storage_fault')
    def test_reader_loss_and_requested_close(self):
        for normal in (False,True):
            with tempfile.TemporaryDirectory() as d:
                s=link();recording(s,d)
                def read(count):
                    if normal:s._stop.set()
                    raise OSError('port closed')
                s.ser.read=read
                output=io.StringIO()
                with contextlib.redirect_stdout(output):s._reader_loop()
                if normal:
                    self.assertNotIn('transport_fault',output.getvalue())
                    s._fault('test_cleanup')
                else:
                    self.assertEqual(s.state,'FAULTED')
                    self.assertEqual(s.manifest['termination_reason'],'transport_fault')
