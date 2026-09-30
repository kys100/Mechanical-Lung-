import csv
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from helpers import logger, link, RID, ROOT, FakeTimer

class Release(unittest.TestCase):
    def test_no_unconditional_skip_or_expected_failure(self):
        for path in (ROOT/'tests').glob('test_*.py'):
            text=path.read_text()
            self.assertIsNone(re.search(r'@(?:unittest\.)?(?:expectedFailure|skip|skipIf|skipUnless)\b',text),str(path))
    def test_hardware_status_is_honest(self):
        data=json.loads((ROOT/'docs/hardware-validation-results.json').read_text())
        self.assertEqual(data['schema_version'],1)
        self.assertEqual(len(data['checks']),6)
        for check in data['checks']:
            self.assertIn(check['status'],('not_run','blocked','pass','fail'))
            if check['status']=='pass':
                self.assertTrue(check['instruments']);self.assertTrue(check['evidence_paths'])
                self.assertTrue(data['deployed_build_id']);self.assertTrue(data['deployed_core'])
                for path in check['evidence_paths']:self.assertTrue((ROOT/path).is_file())
        if any(c['status'] in ('not_run','blocked') for c in data['checks']):
            self.assertNotEqual(data['overall_status'],'pass')
    def test_actual_firmware_session_to_host_and_replay(self):
        with tempfile.TemporaryDirectory() as build:
            binary=str(Path(build,'firmware'))
            compiled=subprocess.run(['g++','-std=c++17','-I'+str(ROOT/'tests/firmware'),'-I'+str(ROOT),
                                     str(ROOT/'tests/firmware/test_mech_lung.cpp'),'-o',binary],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            emitted=subprocess.run([binary,'emit_session'],capture_output=True,text=True)
            self.assertEqual(emitted.returncode,0,emitted.stderr)
            prefix,tail=emitted.stdout.split('# STARTED',1)
            tail='# STARTED'+tail
            for lose_row in (False,True):
                with tempfile.TemporaryDirectory() as d:
                    s=link(gas_temperature_c=20,absolute_pressure_mbar=1013)
                    s.feed_bytes(prefix.encode())
                    self.assertEqual(s.protocol_version,2);self.assertIsNotNone(s.metadata)
                    s.run_id=RID;s.mode='P0';s.state='STARTING'
                    with patch.object(logger,'RECORDINGS_DIR',d):paths=s.start_recording(0)
                    session=tail
                    if lose_row:
                        rows=session.splitlines()
                        rows=[('DATA2,malformed' if r.startswith('DATA2,140,') else r) for r in rows]
                        session='\n'.join(rows)+'\n'
                    with patch.object(logger.threading,'Timer',FakeTimer):
                        for offset in range(0,len(session),73):s.feed_bytes(session[offset:offset+73].encode())
                    self.assertEqual(s.state,'IDLE')
                    self.assertEqual(s.manifest['complete'],not lose_row)
                    with open(paths[1]) as f:peaks=list(csv.DictReader(f))
                    self.assertTrue(peaks)
                    if lose_row:self.assertEqual(peaks[0]['excursion_complete'],'0')
                    import sys
                    replay=subprocess.run([sys.executable,str(ROOT/'tools/replay_recording.py'),'--session',paths[2],
                                           '--samples',paths[0],'--compare-peaks',paths[1]],capture_output=True,text=True)
                    self.assertEqual(replay.returncode,0,replay.stderr)
