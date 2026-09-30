import contextlib
import io
import tempfile
import threading
import unittest
from unittest.mock import patch
from helpers import logger, link, recording, ready, wire, RID, FakeTimer

class CallbackEvent:
    def __init__(self, callback=None, result=False):
        self.callback = callback
        self.result = result
        self.calls = []
    def wait(self, timeout):
        self.calls.append(timeout)
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        return self.result
    def set(self):
        self.result = True

class Control(unittest.TestCase):
    def test_legacy_refused(self):
        s=link();s._handle_marker('# READY_QUERY')
        self.assertFalse(s.begin_timed_run(0,'1'));self.assertFalse(s.ser.writes)
    def test_real_start_handler_ack(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();ready(s)
            original=s.ser.write
            def write(data):
                result=original(data)
                if data.startswith(b'@START'):
                    # Deliver ACK on a reader thread after the write lock releases.
                    def ack():
                        s._handle_marker(f'# STARTED,2,{s.run_id},P0,1000,1000000')
                    reader=threading.Thread(target=ack)
                    reader.start()
                return result
            s.ser.write=write
            with patch.object(logger,'RECORDINGS_DIR',d),patch.object(logger.threading,'Timer',FakeTimer):
                self.assertTrue(s.begin_timed_run(0,'1'))
            self.assertEqual(s.state,'RUNNING')
            s._fault('test_end')
    def test_short_write_disables_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._heartbeat_enabled=True
            s.ser.write=lambda data:len(data)-1
            self.assertFalse(s.stop_run())
            self.assertEqual(s.state,'FAULTED');self.assertFalse(s._heartbeat_enabled)
            s.ser.write=lambda data:self.fail('heartbeat after fault')
            self.assertTrue(s._send_heartbeat())
    def test_timeout_no_success_message_or_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._heartbeat_enabled=True
            s._ended_event=CallbackEvent()
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertFalse(s.stop_run())
            self.assertNotIn('hold confirmed',output.getvalue())
            self.assertEqual(len(s.ser.writes),2)
            s._last_heartbeat=-10;s._send_heartbeat();self.assertEqual(len(s.ser.writes),2)
    def test_tail_ack_and_stale_generation(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            old=s._run_generation
            def ack():
                s._handle_data_line(wire())
                s._handle_marker(f'# ENDED,2,{RID},0,host_stop,0')
            event=CallbackEvent(ack);s._ended_event=event
            self.assertTrue(s.stop_run());self.assertTrue(s.manifest['complete'])
            s._on_run_timeout(old);self.assertEqual(s.state,'IDLE')
    def test_stale_stopper_cannot_fault_new_run(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            def new_run():
                s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
                s.run_id='fedcba9876543210';s.state='RUNNING';s._heartbeat_enabled=True
            s._ended_event=CallbackEvent(new_run,False)
            s.stop_run()
            self.assertEqual(s.state,'RUNNING');self.assertTrue(s._heartbeat_enabled)
            self.assertEqual(len(s.ser.writes),1)
    def test_normal_close_quiet(self):
        s=link();output=io.StringIO()
        with contextlib.redirect_stdout(output):s.close()
        self.assertNotIn('connection lost',output.getvalue())
    def test_stop_deadline_includes_writes(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            clock=[100.0]
            def write(data):
                clock[0]+=min(.8,s.ser.write_timeout)
                s.ser.writes.append(data)
                return len(data)
            class DeadlineEvent:
                def wait(self, duration):
                    clock[0]+=duration
                    return False
            s.ser.write=write;s._ended_event=DeadlineEvent()
            with patch.object(logger.time,'monotonic',lambda:clock[0]):
                self.assertFalse(s.stop_run())
            self.assertLessEqual(clock[0],102.000001)
