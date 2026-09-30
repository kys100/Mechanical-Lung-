import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from helpers import logger, link, recording, wire, RID, ROOT
class Provenance(unittest.TestCase):
    def test_three_file_collision(self):
        with tempfile.TemporaryDirectory() as d:
            for suffix in ('.csv','_peaks.csv','_session.json'):
                base='run'+str(len(suffix)); existing=Path(d,base+suffix);existing.write_text('keep')
                paths,files=logger.open_unique_session(d,base)
                self.assertNotEqual(paths[0],str(Path(d,base+'.csv')))
                for f in files:f.close()
                self.assertEqual(existing.read_text(),'keep')
    def test_replay_and_config_drift(self):
        with tempfile.TemporaryDirectory() as d:
            s=link(gas_temperature_c=20,absolute_pressure_mbar=1013)
            s.avg_window=3;s._flow_hist=logger.deque(maxlen=3)
            paths=recording(s,d)
            for i in range(410):
                j=i%205;f=10*math.sin(math.pi*j/200) if j<=200 else 0
                if i==140:s._handle_data_line('DATA2,malformed')
                s._handle_data_line(wire(i,f))
            s._handle_marker(f'# ENDED,2,{RID},409,host_stop,0')
            args=[sys.executable,str(ROOT/'tools/replay_recording.py'),'--session',paths[2],
                  '--samples',paths[0],'--compare-peaks',paths[1]]
            result=subprocess.run(args,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            manifest=json.loads(Path(paths[2]).read_text());manifest['analysis_policy']=99
            Path(paths[2]).write_text(json.dumps(manifest))
            result=subprocess.run(args,text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('analysis_policy',result.stderr)
    def test_preexisting_temporary_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d);tmp=Path(paths[2]+'.tmp');tmp.write_text('keep')
            with self.assertRaises(FileExistsError):s._save_manifest()
            self.assertEqual(tmp.read_text(),'keep');tmp.unlink();s._fault('test_end')
    def test_manifest_failure_retains_incomplete_original(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d)
            with patch.object(logger.os,'replace',side_effect=OSError('disk failure')):
                s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            manifest=json.loads(Path(paths[2]).read_text())
            self.assertFalse(manifest['complete']);self.assertTrue(manifest['tail_truncated'])
    def test_replay_rejects_missing_configuration_and_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d)
            s._handle_marker(f'# ENDED,2,{RID},-1,host_stop,0')
            original=json.loads(Path(paths[2]).read_text())
            args=[sys.executable,str(ROOT/'tools/replay_recording.py'),'--session',paths[2],
                  '--samples',paths[0],'--compare-peaks',paths[1]]
            for group,key in [('detector_config','smooth_window'),('firmware','core'),('software_hashes','Data_Logger.txt')]:
                manifest=json.loads(json.dumps(original));del manifest[group][key]
                Path(paths[2]).write_text(json.dumps(manifest))
                result=subprocess.run(args,text=True,capture_output=True)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn('incomplete',result.stderr)
            manifest=json.loads(json.dumps(original));manifest['avg_window']=11
            Path(paths[2]).write_text(json.dumps(manifest))
            result=subprocess.run(args,text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('fingerprint',result.stderr)
    def test_initial_manifest_failure_prevents_motion(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();from helpers import ready
            ready(s)
            with patch.object(logger,'RECORDINGS_DIR',d),patch.object(logger.os,'replace',side_effect=OSError('disk failure')):
                self.assertFalse(s.begin_timed_run(0,'1'))
            self.assertEqual(s.state,'IDLE');self.assertFalse(s.ser.writes)
            self.assertIsNone(s._record_file);self.assertIsNone(s._peak_file)
    def test_initial_manifest_and_first_close_failure_clean_every_stream(self):
        import contextlib
        import io
        from helpers import ready
        with tempfile.TemporaryDirectory() as d:
            s=link();ready(s)
            allocate=logger.open_unique_session
            owned=[]
            close_attempts=[]
            def reserve(directory,base):
                paths,files=allocate(directory,base)
                owned.extend(files)
                class Stream:
                    def __init__(self,index):self.index=index
                    def __getattr__(self,name):return getattr(files[self.index],name)
                    def close(self):
                        close_attempts.append(self.index)
                        files[self.index].close()
                        if self.index==0:raise OSError('sample close also failed')
                return paths,[Stream(i) for i in range(3)]
            output=io.StringIO()
            with patch.object(logger,'RECORDINGS_DIR',d), \
                    patch.object(logger,'open_unique_session',reserve), \
                    patch.object(s,'_save_manifest',side_effect=OSError('initial manifest failed')), \
                    contextlib.redirect_stdout(output):
                self.assertFalse(s.begin_timed_run(0,'1'))
            self.assertEqual(s.state,'IDLE');self.assertFalse(s.ser.writes)
            self.assertFalse(s._heartbeat_enabled);self.assertFalse(s._record_started)
            for field in ('_record_file','_peak_file','_record_writer','_peak_writer',
                          '_record_path','_peak_path','_manifest_path',
                          '_record_expected_preset','_detector','manifest'):
                self.assertIsNone(getattr(s,field),field)
            self.assertTrue(all(stream.closed for stream in owned))
            self.assertEqual(close_attempts,[2,0,1,2])
            self.assertIn('initial manifest failed',output.getvalue())
            self.assertIn('sample close also failed',output.getvalue())
            self.assertIn('partial allocation files retained',output.getvalue())
