import serial_link as transport
import recording_schema as schema
import recording as storage
import importlib.machinery
import importlib.util
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('logger', str(ROOT / 'Data_Logger.txt'))
spec = importlib.util.spec_from_loader(loader.name, loader)
logger = importlib.util.module_from_spec(spec)
loader.exec_module(logger)
class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.writes = []
        self.is_open = True
        self.write_timeout = kwargs.get('write_timeout', 1.0)
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def flush(self): pass
    def close(self): self.is_open = False
    def readline(self): return b''

def link(**kwargs):
    kwargs.setdefault('avg_window', 1)
    kwargs.setdefault('start_reader', False)
    kwargs.setdefault('background_recording', False)
    return transport.SerialLink('fake', 115200, serial_instance=FakeSerial(), **kwargs)

RID = '0123456789abcdef'
def wire(seq=0, flow=0, phase=0, preset=0, run_id=RID, flow_ok=1,
         scan_id=None, row_us=None, cycle_id=3, age=100, **overrides):
    p = ['DATA2', str(seq), str((1000000+seq*10000)//1000), str(flow), str(flow_ok), str(age if flow_ok else -1)]
    p += ['20']*7 + ['25'] + ['1']*7 + ['100']*7
    p += ['1450','1450','0','0','0','10',str(phase),str(preset),'0']
    p += [run_id,str(seq+1 if scan_id is None else scan_id),str(1000000+seq*10000 if row_us is None else row_us),str(cycle_id),str(1000000+seq*10000-500), '0','0']
    for index, value in overrides.items(): p[int(index)] = str(value)
    return ','.join(p)

def ready(s):
    s._handle_marker('# PROTOCOL,2')
    s._handle_marker('# META_BEGIN,2,test')
    for key in sorted(schema.META_KEYS):
        s._handle_marker(f'# META,2,{key},test')
    s._handle_marker('# META_END,2,test')
    s._handle_marker('# READY_QUERY')

class FakeTimer:
    def __init__(self,*args,**kwargs): self.daemon=False
    def start(self): pass
    def cancel(self): pass

def recording(s, directory):
    ready(s)
    s.run_id=RID; s.mode='P0'; s.state='STARTING'
    with patch.object(storage, 'RECORDINGS_DIR', directory):
        paths=s.start_recording(0)
    with patch.object(transport.threading, 'Timer', FakeTimer):
        s._handle_marker(f'# STARTED,2,{RID},P0,1000,1000000')
    return paths
