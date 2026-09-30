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
    def test_heartbeat_stop_write_order(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._heartbeat_enabled=True;s._last_heartbeat=-10
            entered=threading.Event();release=threading.Event();original=s.ser.write
            def write(data):
                if data.startswith(b'@PING'):
                    entered.set();self.assertTrue(release.wait(1))
                return original(data)
            s.ser.write=write
            heartbeat=threading.Thread(target=s._send_heartbeat);heartbeat.start()
            self.assertTrue(entered.wait(1))
            def ack():s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            s._ended_event=CallbackEvent(ack)
            stopper=threading.Thread(target=s.stop_run);stopper.start()
            release.set();heartbeat.join(1);stopper.join(1)
            self.assertFalse(stopper.is_alive());self.assertFalse(heartbeat.is_alive())
            self.assertEqual([x.split(b',')[0] for x in s.ser.writes],[b'@PING',b'@STOP'])
            s._last_heartbeat=-10;s._send_heartbeat();self.assertEqual(len(s.ser.writes),2)
    def test_fault_requires_new_metadata_handshake(self):
        s=link();ready(s);s._fault('test_fault')
        s._handle_marker('# READY_QUERY')
        self.assertEqual(s.state,'FAULTED');self.assertIsNone(s.metadata)
        self.assertFalse(s._ready_event.is_set())
        ready(s);self.assertEqual(s.state,'IDLE')
    def test_ready_query_resynchronizes_partial_frame(self):
        s=link();s.wait_until_ready(0)
        self.assertEqual(s.ser.writes,[b'\n?'])
    def test_safety_override_sent_after_unconfirmed_stop(self):
        for command in ('H','X'):
            with self.subTest(command=command),tempfile.TemporaryDirectory() as d:
                s=link();recording(s,d);s._heartbeat_enabled=True
                original=s.ser.write
                def fail_stop(data):
                    if data.startswith(b'@STOP'):
                        original(data[:7])
                        return 7
                    return original(data)
                s.ser.write=fail_stop
                output=io.StringIO()
                with contextlib.redirect_stdout(output):self.assertFalse(s.send_command(command))
                self.assertEqual(s.ser.writes[-1],('\n'+command).encode())
                self.assertEqual(s.state,'FAULTED');self.assertFalse(s._heartbeat_enabled)
                self.assertNotIn('hold confirmed',output.getvalue())
    def test_timeout_property_failure_is_guarded(self):
        from helpers import FakeSerial
        for restore in (False,True):
            with self.subTest(restore=restore),tempfile.TemporaryDirectory() as d:
                s=link();recording(s,d);s._heartbeat_enabled=True
                class TimeoutFaultSerial(FakeSerial):
                    @property
                    def write_timeout(self):return self._timeout
                    @write_timeout.setter
                    def write_timeout(self,value):
                        self.assignments=getattr(self,'assignments',0)+1
                        if self.assignments==(3 if restore else 2):
                            raise logger.serial.SerialException('timeout property failed')
                        self._timeout=value
                s.ser=TimeoutFaultSerial()
                self.assertFalse(s.stop_run())
                self.assertEqual(s.state,'FAULTED');self.assertFalse(s._heartbeat_enabled)
                self.assertIn('timeout property failed',s.connection_error)
    def test_timeout_is_restored_and_ui_query_renegotiates(self):
        s=link();s.ser.write_timeout=.7
        with s._serial_write_lock:self.assertTrue(s._write_bytes_locked(b'm',timeout=.2))
        self.assertEqual(s.ser.write_timeout,.7)
        ready(s);s._fault('test_fault')
        self.assertTrue(s.send_command('?'))
        self.assertEqual(s.ser.writes[-1],b'\n?');self.assertIsNone(s.metadata)
        s.state='RUNNING';writes=len(s.ser.writes)
        self.assertFalse(s.send_command('?'));self.assertEqual(len(s.ser.writes),writes)
    def test_generic_command_short_write_faults_active_capture(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._heartbeat_enabled=True
            s.ser.write=lambda data:0
            self.assertFalse(s.send_command('m'))
            self.assertEqual(s.state,'FAULTED')
            self.assertEqual(s.manifest['termination_reason'],'transport_fault')
            self.assertIsNone(s._record_file);self.assertFalse(s._heartbeat_enabled)
    def test_complete_fresh_handshake_restores_connection_status(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d)
            original_write=s.ser.write
            s.ser.write=lambda data:0
            self.assertFalse(s.send_command('m'))
            self.assertEqual(s.state,'FAULTED')
            self.assertFalse(s.connected);self.assertIsNotNone(s.connection_error)
            s.ser.write=original_write
            self.assertTrue(s.send_command('?'))
            self.assertEqual(s.ser.writes[-1],b'\n?')
            s._handle_marker('# READY_QUERY')
            self.assertEqual(s.state,'FAULTED');self.assertFalse(s.connected)
            s._handle_marker('# PROTOCOL,2')
            s._handle_marker('# META_BEGIN,2,reconnected')
            for key in sorted(logger.META_KEYS):
                s._handle_marker(f'# META,2,{key},test')
            s._handle_marker('# READY_QUERY')
            self.assertEqual(s.state,'FAULTED');self.assertFalse(s.connected)
            s._handle_marker('# META_END,2,reconnected')
            self.assertEqual(s.state,'FAULTED');self.assertFalse(s.connected)
            s._handle_marker('# READY_QUERY')
            self.assertEqual(s.state,'IDLE');self.assertTrue(s.connected)
            self.assertIsNone(s.connection_error);self.assertTrue(s._ready_event.is_set())
