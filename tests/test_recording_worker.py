import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from helpers import link, recording, wire, RID, ROOT


class WorkerTests(unittest.TestCase):
    def block_writer(self, s):
        entered, release = threading.Event(), threading.Event()
        original = s.recording._record_writer
        class Writer:
            def writerow(self, row):
                entered.set()
                if not release.wait(3):
                    raise OSError('test writer timed out')
                original.writerow(row)
        s.recording._record_writer = Writer()
        self.addCleanup(release.set)
        return entered, release

    def test_slow_storage_keeps_transport_live_and_end_is_a_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            entered, release = self.block_writer(s)
            s._heartbeat_enabled = True
            s._handle_data_line(wire(0))
            self.assertTrue(entered.wait(1))
            s._last_heartbeat = 0
            self.assertTrue(s._send_heartbeat())
            self.assertTrue(s.ser.writes[-1].startswith(b'@PING'))
            s._handle_data_line(wire(1))
            s._handle_marker(f'# ENDED,2,{RID},1,host_stop,0')
            self.assertEqual(s.state, 'STOPPING')
            self.assertFalse(s._heartbeat_enabled)
            self.assertFalse(s.worker.done.is_set())
            self.assertFalse(json.loads(Path(paths[2]).read_text())['complete'])
            release.set()
            self.assertTrue(s._ended_event.wait(1))
            self.assertTrue(s.worker.done.is_set())
            with open(paths[0]) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r['seq'] for r in rows], ['0', '1'])
            self.assertTrue(json.loads(Path(paths[2]).read_text())['complete'])
            s.close()

    def test_queue_saturation_stops_ownership_without_waiting_for_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True, recording_capacity=2)
            paths = recording(s, directory)
            entered, release = self.block_writer(s)
            s._heartbeat_enabled = True
            s._handle_data_line(wire(0))
            self.assertTrue(entered.wait(1))
            for i in range(1,4):
                s._handle_data_line(wire(i))
            self.assertEqual(s.state, 'FAULTED')
            self.assertFalse(s._heartbeat_enabled)
            self.assertFalse(s.worker.done.is_set())
            release.set()
            self.assertTrue(s.worker.done.wait(1))
            manifest = json.loads(Path(paths[2]).read_text())
            self.assertEqual(manifest['termination_reason'], 'recording_overflow')
            self.assertFalse(manifest['complete'])
            self.assertEqual(manifest['rows'], 3)
            s.close()

    def test_reader_detects_stall_and_stops_heartbeats(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True, recording_max_latency=.05)
            paths = recording(s, directory)
            entered, release = self.block_writer(s)
            s._heartbeat_enabled = True
            s._handle_data_line(wire(0))
            self.assertTrue(entered.wait(1))
            def read(count):
                time.sleep(.005)
                if s.state == 'FAULTED':
                    s._stop.set()
                return b''
            s.ser.read = read
            reader = threading.Thread(target=s._reader_loop)
            reader.start()
            reader.join(1)
            self.assertFalse(reader.is_alive())
            self.assertEqual(s.state, 'FAULTED')
            self.assertFalse(s._heartbeat_enabled)
            release.set()
            self.assertTrue(s.worker.done.wait(1))
            self.assertEqual(json.loads(Path(paths[2]).read_text())['termination_reason'], 'recording_stalled')
            s.close()

    def test_background_storage_failure_and_no_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            calls = []
            def fail(row):
                calls.append(row)
                raise OSError('disk full')
            s.recording._record_writer.writerow = fail
            s._heartbeat_enabled = True
            s._handle_data_line(wire(0))
            self.assertTrue(s.worker.done.wait(1))
            self.assertEqual(s.state, 'FAULTED')
            self.assertFalse(s._heartbeat_enabled)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(Path(paths[2]).read_text())['termination_reason'], 'storage_fault')
            s.close()

    def test_replay_import_requires_neither_serial_nor_matplotlib(self):
        code = '''import importlib.util, sys
sys.modules['serial'] = None
sys.modules['matplotlib'] = None
spec = importlib.util.spec_from_file_location('replay', 'tools/replay_recording.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert 'serial_link' not in sys.modules
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fault_during_final_publication_is_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            entered, release = threading.Event(), threading.Event()
            original = s.recording._save_manifest
            def save():
                if s.recording.manifest['complete']:
                    entered.set()
                    if not release.wait(2):
                        raise OSError('test publication timed out')
                original()
            s.recording._save_manifest = save
            s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            self.assertTrue(entered.wait(1))
            s._fault('recording_stalled')
            self.assertFalse(s.worker.done.is_set())
            release.set()
            self.assertTrue(s.worker.done.wait(1))
            self.assertFalse(s._ended_event.is_set())
            manifest = json.loads(Path(paths[2]).read_text())
            self.assertFalse(manifest['complete'])
            self.assertEqual(manifest['termination_reason'], 'recording_stalled')
            s.close()

    def test_discard_waits_for_owner_to_close_after_failed_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            entered, release = self.block_writer(s)
            s._handle_data_line(wire(0))
            self.assertTrue(entered.wait(1))
            s.ser.write = lambda data: 0
            self.assertFalse(s.stop_run(discard=True))
            self.assertTrue(all(Path(path).exists() for path in paths))
            release.set()
            s.worker._thread.join(1)
            self.assertFalse(s.worker._thread.is_alive())
            self.assertFalse(any(Path(path).exists() for path in paths))
            s.close()

    def test_session_fault_retains_the_open_partial_excursion(self):
        for reason in ('board_time_reset', 'unexpected_session'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                s = link()
                paths = recording(s, directory)
                for i, flow in enumerate([0] + [10]*12):
                    s._handle_data_line(wire(i, flow))
                if reason == 'board_time_reset':
                    fields = wire(13).split(',')
                    fields[2] = '1'
                    invalid = ','.join(fields)
                else:
                    invalid = wire(13, run_id='fedcba9876543210')
                s._handle_data_line(invalid)
                self.assertEqual(s.state, 'FAULTED')
                with open(paths[1]) as stream:
                    peaks = list(csv.DictReader(stream))
                self.assertEqual(len(peaks), 1)
                self.assertEqual(peaks[0]['excursion_complete'], '0')
                self.assertEqual(json.loads(Path(paths[2]).read_text())['termination_reason'], reason)
                s.close()

    def test_finalizer_exception_is_reported_once_without_retry_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            started = threading.Event()
            s.worker.submit(lambda: started.set())
            self.assertTrue(started.wait(1))
            calls = []
            original = s.recording._save_manifest
            def fail_once():
                calls.append(True)
                if len(calls) == 1:
                    raise ValueError('manifest formatting bug')
                original()
            s.recording._save_manifest = fail_once
            s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            self.assertTrue(s.worker.done.wait(1))
            self.assertEqual(s.state, 'FAULTED')
            self.assertEqual(len(calls), 1)
            self.assertFalse(json.loads(Path(paths[2]).read_text())['complete'])
            self.assertFalse(s._ended_event.is_set())
            s.close()

    def test_manifest_publication_failure_does_not_signal_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            s = link(background_recording=True)
            paths = recording(s, directory)
            started = threading.Event()
            s.worker.submit(lambda: started.set())
            self.assertTrue(started.wait(1))
            def fail():
                raise OSError('manifest disk failure')
            s.recording._save_manifest = fail
            s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            self.assertTrue(s.worker.done.wait(1))
            self.assertEqual(s.state, 'FAULTED')
            self.assertTrue(s.recording.failed)
            self.assertFalse(s._ended_event.is_set())
            self.assertFalse(s.recording.manifest['complete'])
            self.assertEqual(s.recording.manifest['termination_reason'], 'storage_fault')
            self.assertIsNone(s.recording._record_file)
            self.assertIsNone(s.recording._peak_file)
            self.assertFalse(json.loads(Path(paths[2]).read_text())['complete'])
            s.close()
