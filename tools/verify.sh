#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tools/test_firmware.sh
bash tools/check_firmware.sh
python3 -c "from pathlib import Path; [compile(p.read_text(), str(p), 'exec') for p in [Path('Data_Logger.txt'), *Path('.').glob('*.py'), *Path('tools').glob('*.py')]]"
git diff --check
