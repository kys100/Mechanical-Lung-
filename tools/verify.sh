#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tools/test_firmware.sh
bash tools/check_firmware.sh
python3 -c "from pathlib import Path; [compile(Path(p).read_text(), p, 'exec') for p in ('Data_Logger.txt', 'peak_detection.py')]"
git diff --check
