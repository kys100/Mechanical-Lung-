import serial_link as transport
import recording as storage
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
        s=link();s.plots.append(sample(1,10,flow_ok=False,pok=[False]*7))
        self.assertTrue(logger.math.isnan(s.plots.flow_raw[-1]))
        self.assertTrue(logger.math.isnan(s.plots.psens_pa[0][-1]))
        fig,ax=logger.plt.subplots();logger.autoscale(ax,[float('nan'),float('inf')])
        self.assertTrue(all(logger.math.isfinite(v) for v in ax.get_ylim()))
        logger.plt.close(fig)
    def test_start_clears_old_plot_time(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();s.plots.append(sample(100,10))
            recording(s,d);self.assertFalse(s.plots.t)
            s._fault('test_end')
    def test_analysis_error_classification(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            s.recording.analysis.detector.push=lambda sample:(_ for _ in ()).throw(ValueError('detector bug'))
            output=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):
                s._handle_data_line(wire())
            self.assertEqual(s.state,'FAULTED');self.assertIn('analysis_fault',output.getvalue())
            self.assertNotIn('file I/O',output.getvalue())
    def test_storage_failure_manifest_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d)
            original=s.recording._record_file
            class BrokenFlush:
                def flush(self):raise OSError('disk full')
                def close(self):original.close()
            s.recording._record_file=BrokenFlush()
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
            self.assertEqual(s.recording.orientation_mismatches,2)
            self.assertEqual(output.getvalue().count('disagrees'),1)
            self.assertEqual(s.recording._phase_summary()['missing_interior'],3)
            s._fault('test_end')
    def test_each_csv_stream_failure_is_storage_fault(self):
        for stream in ('samples','peaks'):
            with tempfile.TemporaryDirectory() as d:
                s=link(peak_config=PeakDetectionConfig(smooth_window=1,min_samples=5))
                recording(s,d)
                class BrokenWriter:
                    def writerow(self, row):raise OSError('disk full')
                if stream=='samples':s.recording._record_writer=BrokenWriter()
                else:s.recording._peak_writer=BrokenWriter()
                for i,f in enumerate([0]+[10]*10+[0]):
                    s._handle_data_line(wire(i,f))
                    if s.state=='FAULTED':break
                self.assertEqual(s.state,'FAULTED')
                self.assertEqual(s.recording.manifest['termination_reason'],'storage_fault')
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
                    self.assertEqual(s.recording.manifest['termination_reason'],'transport_fault')
    def test_gap_event_fault_classification_and_single_teardown(self):
        # Exercise returned events from an open excursion through each
        # continuity boundary, including the malformed-line path.
        import threading
        for boundary in ('flow', 'sequence', 'malformed'):
            for category in ('storage_fault', 'format_fault', 'analysis_fault'):
                with self.subTest(boundary=boundary, category=category), tempfile.TemporaryDirectory() as d:
                    s=link();recording(s,d);s._heartbeat_enabled=True
                    for i,flow in enumerate([0]+[10]*12):s._handle_data_line(wire(i,flow))
                    calls=[]
                    detector=s.recording.analysis.detector
                    flush_calls=[]
                    original_flush=detector.flush
                    def flush():
                        flush_calls.append(True)
                        return original_flush()
                    detector.flush=flush
                    def fail(*args):
                        calls.append(True)
                        if category=='storage_fault':raise OSError('peak disk error')
                        raise ValueError('peak operation error')
                    if category=='analysis_fault':detector.break_continuity=fail
                    else:s.recording._peak_writer.writerow=fail
                    line={'flow':wire(13,8,flow_ok=0),
                          'sequence':wire(20,8),
                          'malformed':'DATA2,malformed'}[boundary]
                    output,error=io.StringIO(),io.StringIO()
                    escaped=[]
                    def process():
                        try:s._handle_data_line(line)
                        except BaseException as exc:escaped.append(exc)
                    # A daemon worker with a bounded join makes accidental
                    # record/run-lock recursion an explicit test failure.
                    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                        worker=threading.Thread(target=process,daemon=True)
                        worker.start();worker.join(1)
                    self.assertFalse(worker.is_alive(),'teardown deadlocked')
                    self.assertFalse(escaped,repr(escaped))
                    self.assertEqual(s.state,'FAULTED')
                    self.assertEqual(s.recording.manifest['termination_reason'],category)
                    self.assertFalse(s._heartbeat_enabled)
                    self.assertEqual(len(calls),1)
                    self.assertFalse(flush_calls,'failed recording work was flushed again')
                    self.assertNotIn('board_time_reset',output.getvalue())
                    if category!='storage_fault':self.assertIn('Traceback',error.getvalue())
    def test_firmware_error_visible(self):
        s=link();output=io.StringIO()
        with contextlib.redirect_stdout(output):
            s._handle_marker('# ERROR,2,completed_id_capacity_reset_required')
        self.assertIn('completed_id_capacity_reset_required',output.getvalue())
    def test_start_ack_manifest_failure_is_storage_fault(self):
        from helpers import ready, FakeTimer
        with tempfile.TemporaryDirectory() as d:
            s=link();ready(s);s.run_id=RID;s.mode='P0';s.state='STARTING'
            with patch.object(storage,'RECORDINGS_DIR',d):s.start_recording(0)
            original=s.recording._save_manifest
            calls=[]
            def save():
                calls.append(True)
                if len(calls)==1:raise OSError('ack manifest storage failure')
                return original()
            s.recording._save_manifest=save
            with patch.object(transport.threading,'Timer',FakeTimer):
                s._handle_marker(f'# STARTED,2,{RID},P0,1000,1000000')
            self.assertEqual(s.state,'FAULTED')
            self.assertEqual(s.recording.manifest['termination_reason'],'storage_fault')
            self.assertIsNone(s.recording._record_file)
