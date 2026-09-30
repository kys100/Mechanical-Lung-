import tempfile
import unittest
from helpers import logger, link, ready, recording, wire, RID
class Protocol(unittest.TestCase):
    def test_schema_and_validation(self):
        line=wire(); self.assertEqual(len(line.split(',')),44)
        w=logger.parse_wire(line); self.assertEqual(w['scan_id'],1)
        self.assertEqual(w['row_us'],1000000); self.assertEqual(w['run_id'],RID)
        legacy=','.join(['DATA']+line.split(',')[1:37]); self.assertEqual(logger.parse_wire(legacy)['protocol'],1)
        for index,value in [(3,'nan'),(6,'inf'),(4,2),(28,5000),(37,'bad'),(5,-2)]:
            p=line.split(',');p[index]=str(value)
            with self.assertRaises(ValueError):logger.parse_wire(','.join(p))
    def test_metadata_duplicate_rejected(self):
        s=link(); ready(s);self.assertIsNotNone(s.metadata)
        s.wait_until_ready(0)
        s._handle_marker('# META_BEGIN,2,test')
        for _ in range(2):s._handle_marker('# META,2,core,test')
        s._handle_marker('# META_END,2,test');self.assertIsNone(s.metadata)
    def test_tail_and_split_frames(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();paths=recording(s,d)
            line=(wire()+'\n').encode();s.feed_bytes(line[:16]);self.assertEqual(s._rows_written,0)
            s.feed_bytes(line[16:]);self.assertEqual(s._rows_written,1)
            s.state='STOPPING';s.feed_bytes((wire(1)+'\n').encode())
            s._handle_marker(f'# ENDED,2,{RID},1,host_stop,0')
            self.assertEqual(s._rows_written,2);self.assertTrue(s.manifest['complete'])
            s._handle_data_line(wire(2));self.assertEqual(s._rows_written,2)
    def test_stale_session_and_final_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._handle_data_line(wire(run_id='fedcba9876543210'))
            self.assertEqual(s.state,'FAULTED');self.assertEqual(s._rows_written,0)
            self.assertTrue(s.manifest['tail_truncated'])
    def test_unknown_schema_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            s=link();recording(s,d);s._handle_data_line('DATA3,0')
            self.assertEqual(s.manifest['boundaries'][-1]['reason'],'malformed_data')
            s._fault('test_end')
