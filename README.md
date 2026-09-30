# Mechanical lung logger and firmware

UNO R4 WiFi firmware (`MechLung.ino`), Python logger (`Data_Logger.txt`) and peak
analysis (`peak_detection.py`). Firmware and logger implement protocol 2 as a pair.
Python 3.9+ is supported; audited dependencies are pinned in requirements-dev.txt.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python Data_Logger.txt --port /dev/ttyACM0
```

The logger's three Matplotlib plots accept 1–4 (timed preset), s (owned demo),
H (stop and keep), p (stop and discard), X (stop then calibration hold), m (firmware
monitor), ? (renegotiate after fault), and q (close). A timed run requires matching STARTED/ENDED and complete
metadata. Failed stops are reported unconfirmed and disable heartbeats; recording
continues through the ordered tail. Recording allocation failure prevents motion.
Legacy DATA can be displayed but cannot start a new timed recording.

Measured flow is standard L/min; geometric targets are local L/min. Add measured
`--gas-temperature-c 20 --absolute-pressure-mbar 1013` **only when those describe
the run**. Without conditions, peaks remain available but target scoring is null.
`--avg` affects segmentation; `--peak-smooth` independently defaults to 9 and must
be odd. `--peak-min-samples` must be >= smoothing window. See the analysis policy
for changed qualification, warmup populations, timing and partial-event behavior.

## Verification

Install Arduino CLI 1.5.1 and `arduino-cli core install arduino:renesas_uno@1.6.0`.
The build script rejects another installed core version and uses the UNO R4 WiFi
FQBN. It creates a matching sketch folder/build tree in a temporary directory,
passes a SHA256 over the sketch and acquisition/telemetry headers as MECH_BUILD_ID and verified core as MECH_CORE_ID,
and deletes build artifacts afterward.
The source ID is not a deployed binary signature. Builds without explicitly
supplied identities, including ordinary IDE builds, report both as unknown.

```bash
PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tools/test_firmware.sh
ARDUINO_CLI=arduino-cli bash tools/check_firmware.sh
bash tools/verify.sh
```

Native checks include the real sketch with fake Arduino/Wire/USB APIs; each
scenario runs in a fresh process. They assert transport order/capacity, owned
watchdog, frame bounds, one I2C transaction per pass, scan/phase/CRC/geometry and
injected timing budgets. Builds use temporary paths, no serial port or flashing.
The complete gate also checks Python syntax, patch whitespace and absence of
expected-failure/skip markers. There is no separate lint/typecheck migration.

## Recording and replay

Each run exclusively creates samples, peaks and a session manifest in recordings/.
Replay is read-only unless an optional new output path is explicitly requested:

```bash
python tools/replay_recording.py --session RUN_session.json --samples RUN.csv --compare-peaks RUN_peaks.csv
```

- [Protocol and acquisition](docs/protocol-v2.md)
- [Analysis, schemas and replay policy](docs/analysis-policy.md)
- [Flow reference and unresolved calibration](docs/flow-reference.md)
- [Physical validation procedure](docs/hardware-validation.md)
- [Physical validation status](docs/hardware-validation-results.json)

**Physical validation is blocked without a rig.** Software tests/builds do not
establish calibrated volume/position, physical USB behavior or sensor timing.
The inherited geometry/calibration/motion waveform remains unchanged. Firmware
holds centre before USB diagnostics and both I2C buses initialize.

Completed run IDs are retained without eviction for 64 owned sessions per boot.
At that limit, new START commands are rejected until a deliberate board reset;
this makes delayed command replay fail closed without unbounded memory.

## Implementation boundaries

- `analysis.py` owns timestamps, smoothing, and continuity for live capture and replay.
- `peak_detection.py` returns typed peak events; it performs no storage callbacks.
- `recording.py` owns CSV streams, event persistence, and atomic manifest publication.
- `serial_link.py` owns transport and run control; `recording_worker.py` processes a
  bounded FIFO of recording operations (256 waiting operations, 1.5-second maximum
  operation/queue latency). Overflow or a stalled worker faults ownership and disables
  heartbeats. An ENDED barrier closes all accepted work before reporting completion.
- `plot_buffer.py` owns display snapshots. `Data_Logger.txt` is the UI entry point.
- `acquisition.h` owns the named scan stages and captured `ScanSnapshot`;
  `telemetry.h` formats completed snapshots without mutating sensor state.

Replay imports only analysis/schema modules; it requires neither Matplotlib nor
pyserial. New manifests hash every runtime Python module. Replay also accepts
historical schema-2 manifests containing the original two software hashes.
