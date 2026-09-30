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
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def flush(self): pass
    def close(self): self.is_open = False
    def readline(self): return b''

def link(**kwargs):
    with patch.object(logger.serial, 'Serial', FakeSerial), patch.object(logger.threading.Thread, 'start'):
        return logger.SerialLink('fake', 115200, 1, **kwargs)
