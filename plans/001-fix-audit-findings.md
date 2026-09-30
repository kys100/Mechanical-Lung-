# Plan 001: Make motion control, acquisition, and peak qualification auditable

> **Executor instructions:** This document preserves the implementation specification. Software execution is complete through `e17d7ed`; see the status and evidence in `plans/README.md`. Required physical validation remains blocked. Read the entire plan before further changes and preserve its verification gates. Do not mark a hardware-dependent stage DONE based on simulated tests. No audit report or prior conversation is required to follow this document.
>
> **Drift check — run first from repository root:**
> ```bash
> git status --short
> git diff --stat 976bd8a58cb3400d102cf829f8c747d2042a12aa..HEAD -- Data_Logger.txt peak_detection.py MechLung.ino tests tools docs requirements-dev.txt README.md .gitignore plans
> git diff -- Data_Logger.txt peak_detection.py MechLung.ino
> ```
> Compare changed symbols against the excerpts below. Expected changes from completed stages in this same plan are allowed when their gates and status entries agree. For unrelated changes, conflicting protocol work, or unexplained excerpt mismatches, STOP and reconcile the plan before editing. Preserve unrelated user work.

## Status

- **Priority:** P1 overall; stage priorities appear in the index.
- **Effort:** L — multiple independently reviewable changes, not one large patch.
- **Risk:** HIGH — changes cross host threading, firmware scheduling, protocol, files, and analysis semantics.
- **Depends on:** none; Stage 1 establishes repository-owned verification.
- **Category:** bug, tests, performance, measurement integrity, DX, docs.
- **Planned at:** commit `976bd8a` / `976bd8a58cb3400d102cf829f8c747d2042a12aa`, 2026-09-30.
- **Selection:** user requested a plan for the preceding complete audit, including F01–F15 and A01–A07. This is the skill's `plan <description>` workflow; no new broad audit or second finding-selection round is needed.

- **Execution:** software DONE at `e17d7edecc9f34595b65852d63bc6b712d0ddb42`; overall BLOCKED on physical rig validation only.
- **Verification:** 63 final Python checks; 21 native scenarios plus an explicit-core metadata check; actual pinned UNO R4 build. Final host checks rerun; unchanged native/build results reused from `806d2bb` after input comparison. See the index for exact commands and evidence.
- **Review:** CodeRabbit found four issues in its first implementation pass; all were fixed. Full second pass and final incremental pass each found zero issues. Manual review revisions and regression checks also completed.
- **Publication authorization:** the user explicitly requested implementation and pushing code. Only the assigned task branch is permitted; physical deployment is outside this execution.

## Why this matters

The present logger can report a complete or qualified peak across missing acquisition, mix sessions, and stop recording without confirming that motion stopped. Firmware watchdog protection can disappear on restart or fail to execute while synchronous USB output blocks. Fixing the individual detector symptoms without defining session identity, continuity, and timing would leave the underlying failures intact. This plan first builds evidence and bounded control, then corrects acquisition and analysis, and finally records enough provenance to reproduce the result.

## Current state

### Repository and deployment

Only three application files are tracked at the planned revision. There is one commit, `976bd8a Add files via upload`; no established commit-message convention, repository tests, requirements file, CI, linter/typechecker configuration, README, CONTRIBUTING, ADR, PRD, CONTEXT, DESIGN, or PRODUCT document was found. An ignored `.agents/skills/improve/` directory supplies the advisor workflow and must remain untouched. No knowledge-base facts were available.

- `Data_Logger.txt`: Python CLI, pyserial reader thread, three Matplotlib windows, timed runs, two CSV writers; loads `peak_detection.py` normally despite its own `.txt` extension.
- `peak_detection.py`: frozen validated config dataclass, centered average, stateful excursion detector, callback event dictionaries.
- `MechLung.ino`: Arduino UNO R4 WiFi, native USB CDC, A0 position command, A1 diagnostic feedback, SFM3000 on Wire, seven SDP811 channels on Wire1 through PCA9548.
- Current rates: DAC/scan/log nominally 100 Hz; host heartbeat every 0.5 s; firmware host timeout 3 s; Wire transaction timeout 5 ms.
- Current schemas: `DATA` has 37 fields including its marker; sample CSV 38 columns; peaks CSV 81 columns. Mechanical phase 0 = expiration, 1 = inspiration; electrical flow sign remains separate.

### Relevant source excerpts and conventions

Read each whole owning function before modifying it; line numbers identify this revision, not future offsets.

**Host command failure — `Data_Logger.txt:345–372`:**
```python
with self._serial_write_lock:
    self.ser.write(ch.encode("ascii"))
    self.ser.flush()
# exception path:
self.connection_error = str(e)
self.connected = False
return False
```
The reader continues on `_stop`, not `connected`, and can send more heartbeats. At `850–861`, timeout clears the timer, calls `send_command("H")` without inspecting its result, closes files, and prints that hold occurred.

**Host continuity — `Data_Logger.txt:447–470`:**
```python
if board_reset:
    self._flow_hist.clear()
    self._flow_sum = 0.0
# ...
if self._last_seq is not None and seq > self._last_seq + 1:
    seq_gap = seq - self._last_seq - 1
    self.dropped_rows += seq_gap
# ...
if flow_ok:
    self._flow_hist.append(flow_slm)
    self._flow_sum += flow_slm
else:
    self._flow_hist.clear()
    self._flow_sum = 0.0
```
Sequence gaps do not interrupt detection. `float()` accepts NaN/inf. `_record_sample_allowed_locked()` at `560–575` returns true for every preset after its first match; `start_recording()` does not clear live averaging. Row writing and `detector.push()` share an `except (OSError, ValueError)` at `511–534`.

**Detector — `peak_detection.py:144–158`:**
```python
if not sample.flow_ok:
    if self._sign != 0:
        self._close(complete=False)
    return
flow = sample.flow_avg
if self._sign == 0:
    threshold = self.config.opening_threshold(sample.target_peak_slm)
    if flow >= threshold:
        self._open(sample, 1, threshold)
```
It reopens immediately after a gap. `centred_moving_average()` at `85–103` keeps raw edges, returns raw short inputs, and reduces even windows after the length check. `_close()` selects the maximum over all entries; plateau `cut` at `194` precedes parabolic refinement at `204`. Qualification at `287` only combines target pass, peak-sample pressure flags, and peak-sample ages.

**Watchdog — `MechLung.ino:1022–1027`:**
```cpp
static void goIdleHold() {
  current_preset = -1;
  host_watchdog_armed = false;
  resetPositionFeedback();
  holdCentre();
```
Neither motion starter at `975` / `1001` re-arms it. Only `!` does so at `1069`. The watchdog runs at the beginning of `loop()`.

**Scheduling — `MechLung.ino:1268–1323`:**
```cpp
last_dac_us = now_us;
// ...
last_sensor_us = now_us;
sfm3000Service(now_us);
last_ok_count = readAllPsens(now_us);
// ...
last_log_us += LOG_INTERVAL_US;
if ((uint32_t)(now_us - last_log_us) >= LOG_INTERVAL_US) last_log_us = now_us;
const uint32_t row_us = micros();
```
Logging keeps phase while DAC/sensor gates reset to now. `readAllPsens()` at `631` visits all channels synchronously. Recovery can add a second timed-out mux transaction per channel. All serial output is currently synchronous.

**Measurement model — `MechLung.ino:819–822`, `904–926`:**
```cpp
const float Q_mls = q_Lmin[i] * 1000.0f / 60.0f;
const float t_insp_s = (V_TIDAL_ML * PI) / (2.0f * Q_mls);
// ... commandedFlowSlm() returns the geometric volume derivative.
```
Geometric flow is local L/min. The SFM reports standard L/min at 293.15 K and 1013 mbar. No conversion exists. `DAC_HALF_RANGE=1526`, centre, pot calibration and the 4095/4002 correction have unresolved physical calibration notes; do not guess replacements.

Match Python's existing four-space indentation, snake_case names, config dataclass validation and explicit file locks. Match firmware's two-space indentation, static helpers, fixed-size data, unsigned timer arithmetic, and the sole `writeActuatorDac()` path to A0. Example state synchronization: `_cancel_run_timer_locked()` (`Data_Logger.txt:813`) documents ownership and increments a generation token. Preserve that property. Keep `_run_lock` before `_record_lock` whenever both are held; do not hold either while waiting for reader acknowledgements.

### Behaviors already correct: preserve them

Exclusive recording creation must never truncate an existing session. Pressure CRC polynomial 0x31/init 0xFF and live scale conversion are correct. SFM address 0x40, SDP811 address 0x26, start/stop commands, phase naming, 700 mL geometry and half-sine timing are internally consistent. With 2:1 expiration:inspiration duration, expiration peak is half the named preset peak. Feedback remains telemetry-only; Jrk owns its configured travel control. Do not restore the removed firmware travel clamp or add feedback correction to the DAC waveform.

## Commands you will need

Run from repository root unless stated otherwise. Distinguish historical commands from new gates; the repository currently has **no** unittest suite or verification scripts.

### Previously verified in the audit; evidence reused for planning

- Python 3.9.25, pyserial 3.5, Matplotlib 3.9.4; isolated environment at `/tmp/mech-audit/venv` in the audit sandbox.
- Native GCC 11.5.0 harness executed the unchanged sketch with fake Arduino/Wire/clock APIs.
- `/tmp/mech-audit/arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi --warnings all --build-path /tmp/mech-audit/arduino-build /tmp/mech-audit/sketch/MechLung` succeeded using CLI 1.5.1 / core `arduino:renesas_uno@1.6.0`. Sketch was copied unchanged to a matching directory. Flash 74,220 bytes, globals 9,452 bytes; warnings in core only.
- Source SHA256s: logger `d321cd72e45c5cde23c0c4a4de26c400b22fdaa6fe2865b2dc6aacfba2f43c4a`; detector `65487074667309879289f971622530723550fafae51420d1bd54193be843e4c8`; firmware `1cbf91dfd0f24a3fd38a7f63072e2a388bb314f06b68bc80c5348eab7af63c43`.
- Scratch evidence is optional at `/home/vercel-sandbox/workspace/output/audit/evidence/`. It is **not** a dependency of this plan. Its assertions prove the old defects; do not copy them as passing acceptance criteria.

### Gates to establish in Stage 1 (proposed commands, not yet available)

| Purpose | Command | Expected result |
|---|---|---|
| Python test dependencies | `python3 -m pip install -r requirements-dev.txt` in the executor's chosen virtual environment | Pinned compatible pyserial/Matplotlib import; no hardware required. |
| All Python checks | `PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -m unittest discover -s tests -p 'test_*.py' -v` | Exit 0; no unexpected successes, failures or real serial access. |
| Targeted Python checks | `PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -m unittest discover -s tests -p 'test_control.py' -v` | Exit 0 for named module; analogous filenames below. |
| Native firmware checks | `bash tools/test_firmware.sh` | Exit 0, all named C++ assertions passed; executable built under mktemp directory and removed. |
| Real UNO R4 build | `ARDUINO_CLI=arduino-cli bash tools/check_firmware.sh` | Exit 0 for pinned core 1.6.0; build/matching sketch directory created under mktemp and removed. |
| Syntax | `python3 -c "from pathlib import Path; [compile(Path(p).read_text(), p, 'exec') for p in ('Data_Logger.txt', 'peak_detection.py')]"` | Exit 0, no bytecode files. |
| Patch hygiene | `git diff --check` | Exit 0. |
| Release software gate | `bash tools/verify.sh` | Runs the whole Python suite, native harness, real build, syntax/hygiene and rejects temporary expected-failure markers; exit 0. |

Set `ARDUINO_CLI=/tmp/mech-audit/arduino-cli` in this sandbox if that verified executable still exists. Else install a checksum-verified official CLI in the executor's environment and use `arduino-cli core install arduino:renesas_uno@1.6.0`. Do not silently compile another board/core. There is no configured lint/typecheck/security-audit command to claim as passed; do not add a wholesale formatting/tooling migration.

## Scope

**Application edits allowed to the future executor:** `Data_Logger.txt`, `peak_detection.py`, `MechLung.ino`.

**Support files allowed to create:**

- `tests/__init__.py`, `tests/helpers.py`, `tests/test_baseline.py`, `tests/test_control.py`, `tests/test_protocol.py`, `tests/test_continuity.py`, `tests/test_peak_policy.py`, `tests/test_timing.py`, `tests/test_provenance.py`, `tests/test_reporting.py`, `tests/test_flow_reference.py`, `tests/test_release.py`.
- `tests/firmware/Wire.h`, `tests/firmware/test_mech_lung.cpp`, `tests/fixtures/` containing synthetic fixtures only.
- `tools/test_firmware.sh`, `tools/check_firmware.sh`, `tools/verify.sh`, `tools/replay_recording.py`.
- `requirements-dev.txt`, `README.md`, narrowly scoped `.gitignore` entries for Python caches/virtual environments and test outputs if needed.
- `docs/protocol-v2.md`, `docs/analysis-policy.md`, `docs/flow-reference.md`, `docs/hardware-validation.md`, `docs/hardware-validation-results.json`.
- This plan and its index for status/evidence updates.

**Out of scope:** `.agents/`, other repositories, external Arduino core edits/vendor forks, Jrk configuration writes, wiring changes, guessed calibration constants, redesigned motion profiles, a new UI framework, network services, dependency migrations unrelated to these fixes, modifying existing recordings, deployment/flashing without a separately authorized hardware test. No physical hardware exists in the current planning sandbox.

## Git workflow

The initial advisor pass wrote only plans. The user subsequently authorized execution, commits and publication. Implementation was divided into reviewable commits in an isolated executor worktree, with final integration and verification by the reviewer. Use the assigned workspace branch `coderabbit/audit-logger-peak-detector-firmware/51736d42` if publishing is authorized; do not push another ref. No established commit convention was found; descriptive messages such as `Fix watchdog ownership on host restart` are sufficient. No issue/PR publication is part of this plan.

## Steps

### Stage 1 — Establish repeatable software verification (P1; M; low fix risk)

1. Create unittest helpers which load `Data_Logger.txt` with `importlib.machinery.SourceFileLoader`, import `peak_detection` normally, force Agg, supply fake serial, and prevent background reader startup when testing methods directly. Use fake monotonic clocks/timers and barriers for concurrency tests rather than real sleeps. Use TemporaryDirectory for every recording.
2. Start with positive baseline tests: config rejection of bool/nonfinite/invalid counts, uint32 millis wrap versus reset, exclusive filename collisions, 37/38/81 schema counts, correct phase labels, normal complete/partial event behavior, no partial target scoring, and timeout generation rejection.
3. Create a native C++ harness that **includes the actual .ino**, not a separately translated algorithm. Stub the Arduino/Wire APIs, USB capacity, serial byte input/output, ADC and microsecond clock. Record timestamps of every A0 write, every I2C transaction, and every completed serial frame. Every test resets globals and any static-local state (prefer fresh process per case if necessary). Do not count output text alone as an assertion.
4. Verify geometry: 700 mL displacement, preset-1 +5/-10 L/min maxima, phase 0/1, CRC(0xBEEF)=0x92, micros deadline wrap, sticky clamp reset and diagnostic-only feedback. Create build scripts with `set -euo pipefail`, temporary directories and cleanup traps.
5. Pin the audited Python direct test dependencies; no pytest is necessary. Document Python 3.9 compatibility and the verified Arduino toolchain. Initial expected-failure regression tests may assert the desired behavior for known bugs, but list each and remove its marker in the fixing stage. Release tooling must reject remaining `expectedFailure`, unconditional skip or xfail markers in these tests.

**Verify:** baseline unittest discovery and `bash tools/test_firmware.sh` → all baseline assertions pass; any known expected failures are named and documented. `ARDUINO_CLI=arduino-cli bash tools/check_firmware.sh` → actual UNO R4 build succeeds. No serial port is opened. Hardware tests are not implied.

### Stage 2 — Bound USB output and prioritize the control loop (P1; L; high fix risk)

**Covers F03 and prepares F08.** In the tested Renesas core, `_SerialUSB::write` loops indefinitely while transmit space stays zero; the loop-based watchdog cannot run while inside it. Simply disabling the monitor or putting a timer around `Serial.print` does not fix this.

1. Inspect the pinned core's `availableForWrite()`/`write()` implementation and confirm there is one application writer. Implement a fixed-capacity firmware TX queue and a single output service. Format each complete record into a bounded static buffer; detect `snprintf` truncation before enqueueing. Use no dynamic `String` growth. Document capacity and SRAM cost; target total globals under 24 KiB, leaving at least 8 KiB for stack/runtime.
2. All DATA, banner, monitor, recovery and command output must go through this service, including setup diagnostics. Issue centre hold before any potentially serviced diagnostic output during startup. Preserve the existing 2-second settling intent.
3. Each service call writes at most `min(availableForWrite(), remaining_record_bytes, 64)` bytes once, then returns. Zero capacity means no write and immediate return. No `flush()` loop, busy wait, or direct `Serial.print` remains. Confirm the pinned core cannot block for this write size under the single-writer contract; if it cannot be established, STOP F03 implementation and report the unresolved dependency rather than claiming it fixed.
4. Keep record byte order and forbid interleaving partial records. Reserve queue capacity for start/end/error markers. Drop only whole not-yet-started telemetry records under congestion, count drops, and never block DAC/watchdog service to wait for an acknowledgement to transmit. A partially sent record must finish or the transport must be explicitly abandoned; do not insert a marker into its middle. Firmware holds motion immediately even if its confirmation cannot be delivered.
5. Put host timeout/DAC deadline checks ahead of bounded RX, TX and sensor work. Bound RX work per pass too (e.g. 32 input bytes); an always-nonempty serial queue must not starve the tick.

**Verify:** `bash tools/test_firmware.sh` → named tests `tx_zero_capacity`, `tx_partial_capacity`, `tx_disconnect`, `tx_overflow`, `tx_record_order`, `rx_flood_budget` pass. Hold USB capacity at zero for over 3 simulated seconds during a host-owned run: no write call with insufficient capacity, watchdog still commands hold. No DATA record is partially dropped. Real build passes; record SRAM use. Physical USB completion remains a Stage 11 gate.

### Stage 3 — Make host-owned starts and stops explicit and acknowledged (P1; L; high fix risk)

**Covers F01/F02 and the control half of F06/F14.** Add a small versioned protocol, preserving plain Serial Monitor commands. Keep the grammar below in `docs/protocol-v2.md` and tests; do not independently invent host and firmware variants.

#### Proposed protocol contract

- `?` still responds with `# READY_QUERY`; new firmware also advertises `# PROTOCOL,2`. A new logger may display legacy DATA but must refuse a timed host-controlled run if v2 capability was not received. Do not send framed commands to legacy firmware, whose single-byte parser could interpret digits inside them as motion commands.
- Commands are ASCII lines: `@START,<run_id>,<mode>\n`, `@PING,<run_id>\n`, `@STOP,<run_id>\n`. `run_id` is exactly 16 lowercase hex characters generated fresh per host motion session; it is a correlation ID, not authentication. `mode` is `P0`, `P1`, `P2`, `P3` or `DEMO` (preset index is zero-based).
- Start acknowledgement: `# STARTED,2,<run_id>,<mode>,<start_ms>,<start_us>`. Stop acknowledgement: `# ENDED,2,<run_id>,<final_enqueued_seq>,<reason>,<tx_dropped_total>`. Use `-1` if no data row was enqueued. Reason vocabulary: `host_stop`, `watchdog`, `manual_override`, `transport_fault`.
- Reject active-session replacement by another framed START until stopping completes; duplicate START for the same active ID is idempotent and must not reset phase, seq, watchdog or recording. A completed ID cannot restart motion. Repeated STOP for the most recently ended ID resends the same final marker without changing it. Stale PING never refreshes the active session.
- A matching START reserves acknowledgement capacity and establishes run identity, host ownership and heartbeat deadline **before** changing motion state. If the control marker cannot be reserved, remain in hold. Re-acknowledgements must not move ahead of already queued session DATA.
- Firmware parser uses a fixed buffer (64 bytes is enough for these commands); `@` begins framed parsing only outside a frame. Oversize, malformed and timed-out frames are discarded **as whole frames**, never reinterpreted as legacy command bytes. Choose and document a 250 ms incomplete-frame timeout; discard through newline after overflow. Parser timeout does not suspend the watchdog.

#### Implement lifecycle and failure handling

1. Keep autonomous Serial Monitor runs when no recent host owns them. For legacy `!` compatibility, preserve last-host-seen time across hold; a restart within the 3-second presence lease re-arms watchdog before motion. Passing `!H1` then losing the host must hold after the deadline. Plain `1` with no host presence remains autonomous. Bare `!` must not extend a v2 session owned by a different run ID.
2. Route logger preset and demo starts through framed START after capability negotiation. Keep all frame bytes under the serial-write lock, validate complete write counts, and treat short writes/timeouts as transport failures. Do not rely on a potentially unbounded host `flush()` to prove delivery.
3. Introduce explicit states `IDLE`, `STARTING`, `RUNNING`, `STOPPING`, `FAULTED` and generation/run-ID guards. Start deadline is bounded (2 s); run timer starts when STARTED is received. Stop attempts share a bounded 2-second confirmation deadline; at most two matching STOP sends, with fake-clock tests. No new run may begin in STOPPING or FAULTED without a fresh connection/handshake.
4. On STOP request, disable future heartbeats for that run **before** sending STOP. Serialize that change with heartbeat writes so none can slip through afterward. On start failure, write failure, or unconfirmed stop, terminate heartbeat service and report `stop unconfirmed`; do not print that the actuator returned to hold. At most one already completed in-flight heartbeat may determine the firmware's remaining 3-second lease; a new one must not be generated.
5. Wait for acknowledgements without holding `_run_lock` or `_record_lock`; the reader needs both to advance state. Keep the reader alive during stop/drain, including close(). Timer callbacks, keyboard handlers and disconnect cleanup must converge on this same lifecycle. A stale callback must not stop a later generation.
6. Manual H/X/demo override: end the current host session first. H commands immediate hold; X remains the fixed calibration command after the old run is finalized; demo is a fresh owned session. Preserve `p` deletion intent and `H` preservation intent without deleting files before the session state is resolved.

**Verify:** targeted `test_control.py`, `test_protocol.py`, native firmware tests and real build → all pass. Required cases: `!H1`; autonomous legacy start; v2 start then immediate host loss; duplicate/stale tokens; short write; H/STOP timeout with later usable serial; concurrent heartbeat/stop; stale timer generation; bounded partial frames; teardown with normal close. No confirmation message without matching ENDED; no heartbeat after stop/fault transition; no motion on malformed frames.

### Stage 4 — Establish recording identity and drain the final rows (P1; M; medium fix risk)

**Covers F06/F14 and provenance prerequisites.**

1. Introduce the **explicit new marker `DATA2`**, not an undocumented length change to DATA. Preserve the existing 36 value positions and append seven fields in this exact order: `run_id, scan_id, row_us, cycle_id, scan_start_us, missed_slots_total, tx_dropped_total`. Width is **44 fields including DATA2**. Step 5 defines acquisition identity; initial Stage 4 tests may use synthetic values. Document which existing target values are geometric local-flow targets rather than standard flow (Stage 9).
2. Keep legacy 37-field DATA parsing for display/import diagnostics. Do not accept it into a newly created v2 timed recording or infer run identity from preset alone. Unknown marker/version/width is rejected explicitly. Update Sample construction, CSV headers/writers and plot tuple handling together; named-header tests must check field meanings, not just counts.
3. Allocate the recording before START as today, but enable row acceptance only after matching STARTED. Clear recorder averaging, seq/time state and detector at that boundary. Do not let pre-command, previous-preset or previous-same-preset queued rows refill recording state. Validate run ID and requested preset on **every** accepted row.
4. On detected reset, unexpected active run ID/preset, or a fresh boot/capability sequence during recording: mark the current session interrupted, close its detector as partial, stop its owned lifecycle, and require a fresh handshake. Never splice subsequent motion into the file.
5. On timeout/hold, firmware commands hold immediately, prevents new session acquisition, preserves already enqueued whole DATA2 rows, and appends ENDED behind them. `final_enqueued_seq` includes any partially transmitting row that is retained; dropped telemetry is reflected separately. Reserve marker capacity so congestion cannot discard this barrier.
6. Logger keeps writing matching rows in STOPPING until matching ENDED is parsed. Validate the final sequence and loss counters before finalizing. Missing rows make capture incomplete even if hold is confirmed. Deadline/EOF without ENDED marks `tail_truncated=true`, flushes the open event as partial, and retains faulted files unless the user explicitly chose `p`.
7. Keep motion state and recording state distinct. If recording allocation fails and the existing explicitly warned motion-only behavior is retained, display `[RUN; NOT RECORDING]`; it must not claim a recorded acquisition or create a fake replay manifest. Record this intentional behavior in README.

**Verify:** targeted `test_protocol.py` and `test_control.py`, plus native tests → PASS for stale same-preset backlog, reset, unexpected preset, zero-row session, valid tail after STOP, missing end marker, duplicate end marker, and final-sequence mismatch. No post-END row enters the file. Synthetic DATA2 round-trips all 44 positions; legacy DATA remains 37. Real build and all Python tests pass.

### Stage 5 — Coordinate acquisition and budget I2C recovery (P1; L; high fix risk)

**Covers F07/F08; implements DATA2 acquisition fields.**

1. Replace three drifting independent gates with a 10,000 µs acquisition-slot deadline shared by DAC update, scan identity and telemetry. Maintain actual elapsed time separately for waveform phase advancement. If late by multiple slots, advance the deadline arithmetically and count missed slots; do not replay a burst of updates/rows from one scan. Preserve wrap-safe subtraction; comparisons apply only within their documented half-range.
2. Each slot allocates one `scan_id`. Start with an immutable command/phase/cycle snapshot. `cycle_id` counts commanded full cycles from session start and advances even if acquisition is missed; increment correctly if elapsed time spans multiple cycles. It drives warmup independently of detected peaks.
3. Turn pressure scanning and sensor recovery into an incremental state machine. A loop pass may perform **at most one** potentially blocking I2C transaction, then returns through watchdog/DAC checks. Preserve mux channel ownership between SELECT and READ/STOP/START states; never read a different selected channel. No helper may hide a second transaction. Runtime retry waits start at command completion using a fresh micros value.
4. If the next slot becomes due before a scan finishes, close the old scan as incomplete, invalidate channels not acquired in that scan, emit at most its one row, then start the current slot. Never copy a previous scan's `ok=true` into the new row. Retained last-good numbers may be transmitted only beside invalid flags/ages. Use fixed snapshots so late recovery work cannot modify a queued row.
5. Define `row_us` as acquisition snapshot closure, not eventual USB transmission time; calculate ages against that same reference. `scan_start_us` is the start of this scan. Record command/phase at scan start; if scan spans a phase transition, analysis must flag the mixed timing instead of silently changing phase metadata. `seq` identifies generated session rows; gaps/counters distinguish dropped TX and missed slots from sensor failures.
6. Process control/DAC checks between every I2C transaction and bounded RX/TX service. With 5 ms injected timeout and <=1 ms synthetic non-I2C work between checks, the test target is no DAC gap exceeding 16 ms, no 70 ms monolithic stall, and watchdog hold by 3010 ms since the last accepted heartbeat. These are software-budget tests, not promised physical timing.

**Verify:** `bash tools/test_firmware.sh` → no duplicate scan ID among emitted rows; no mixed-scan validity; no catch-up row burst; deadlines work across micros wrap; full-channel failure meets stated bounds; recovery delays are measured after completion; single transaction per pass; every channel eventually gets retry service. Healthy synthetic cadence has one scan/row per slot and zero missed-slot count. Saturated TX does not change DAC cadence. Real build passes. Run `test_protocol.py` to verify counters/IDs survive host parsing.

### Stage 6 — Make discontinuities and numeric validity first-class detector inputs (P1; M; medium fix risk)

**Covers F04/F05/F06/F13 and the integrity part of A05.**

1. Factor numeric/schema validation in `Data_Logger.txt` before mutating clocks, histories, plot buffers or detector state. Require finite float values, exact 0/1 flags, valid phase/preset/run ID domains, uint32 wire counters, DAC count range, and ages of -1 only for invalid/unavailable values. Avoid imposing an unverified physical feedback range. For invalid sensor values the documented sentinels must be accepted only with invalid flags; they never enter arithmetic as valid.
2. Handle partial serial lines incrementally with a bounded receive buffer (at least maximum protocol frame size); `readline` timeout must not turn a valid split record into two unrelated lines. On overflow/rejected DATA candidate, record a discontinuity once, discard through newline, then resume. Never log rejected input as valid.
3. Add one explicit detector `break_continuity(reason)` transition, used for invalid flow, missing/repeated/out-of-order seq or scan ID, excessive elapsed time, malformed data, session reset, and unexpected phase/run changes. Compare uint32 progression modulo wrap; do not treat genuine wrap as reset. Counter changes expose firmware-skipped slots even when seq is adjacent.
4. Use a documented `max_sample_gap_us=15000` for nominal 100 Hz flow-completion spacing, configurable and saved in metadata. This is an analysis continuity threshold, separate from the 20 ms age allowance. Nonpositive flow time increments are discontinuities. Pressure failure by itself does not split valid flow; it invalidates pressure qualification.
5. A break closes any existing excursion as partial, clears segmentation averaging, and disarms detection. Initial recording state is also disarmed. Re-arm only on a valid finite sample with **both raw magnitude and segmentation-average magnitude below the exit level**. Latch the pre-gap exit level during a broken excursion; use the configured opening threshold × exit fraction at a fresh session. A sign reversal without an observed low-flow baseline closes partial, does not manufacture a complete next event, and waits for baseline. Partial events never advance completed-phase bookkeeping.
6. On ordinary baseline crossing, close complete and allow later threshold crossing to open. Limit event completion to one consistent commanded phase/cycle; an unexpected metadata transition above baseline is partial. Source-of-truth warmup is the commanded cycle ID (first three cycles by default), not the number of recovered fragments. Legacy data without reliable cycle identity is not eligible for v2 qualification.
7. Keep raw recording and invalidity metadata. The run need not end on a single dropped sensor read, but no resulting fragment may be promoted into a complete/evaluable event until continuity is re-established.

**Verify:** targeted `test_continuity.py` → PASS for 10 slm/2 s half-sine at 100 Hz with one dropped sample at index 140: first fragment partial, resumed falling fragment never scored complete; the next baseline-separated full breath is accepted. Also test rising-edge gap, 100 missing seq rows, time-only gap, malformed row, repeated scan, wrap, reset, stale averaging after demo, initial above-threshold recording, and NaN/inf followed by finite samples. Neither a zero-flow synthetic event nor a cross-gap qualified peak is emitted. All unchanged positive geometry/control tests remain green.

### Stage 7 — Use consistent smoothing, timestamps and pressure qualification (P2; L; medium fix risk)

**Covers F09/F10/F11 and A02/A04/A05.** Implement the following policy explicitly; do not leave the executor to choose statistical semantics.

1. Reject even smoothing windows with an actionable validation error; allow window 1 explicitly as unsmoothed analysis. Set default `min_samples=9` to match default `smooth_window=9`, and require `min_samples >= smooth_window`. Do not silently normalize a CLI request. `--peak-smooth` gets an independent default of 9; document that `--avg` still controls segmentation, so it is not solely a display option.
2. For window >1, only points with a complete centered window are candidates for peak and plateau. Raw edges must never compete with them. Keep `centred_moving_average` import compatibility if practical, but give unsupported points an explicit support mask or documented sentinel; all consumers must obey it. Segments shorter than the effective window are discarded with a reason. Three-point interpolation requires three supported neighbours; otherwise return the discrete supported peak with an explicit interpolation-unavailable reason.
3. Unwrap DATA2 `row_us` per session, cross-check with millis and boot/session state, and derive `flow_time_us = unwrapped_row_us - flow_age_us`; similarly derive each pressure timestamp. Do not unwrap raw micros alone across long idle periods; reset at STARTED. Read completion is the timestamp definition, not the exact internal conversion instant.
4. Fit the parabola to three **actual flow timestamps**, using times relative to the centre to avoid numerical cancellation. Require distinct increasing times, negative curvature, a finite vertex inside the selected sample's adjacent midpoint interval, and three supported same-segment values. Otherwise fall back to discrete maximum. Store time origin, nearest sample ID, offset and interpolation status. Do not imply 10 µs measurement accuracy from decimal formatting.
5. Define plateau relative to the **discrete supported filtered maximum**, calculated before any optional interpolation. Export `plateau_reference_flow_slm` alongside interpolated peak, and document their different roles. This resolves the current hidden mismatch without inventing samples that reach the refined vertex. Enumerate all supported indices above threshold so disconnected groups remain observable; no unsupported/raw fallback. A disconnected or empty plateau is unqualified.
6. Split quality fields into `peak_sample_ok`, `plateau_capture_ok`, `qualified_peak`, plus deterministic reason codes. Peak sample requires finite valid flow/all seven pressures and acceptable ages. Plateau capture requires contiguous seq/scan/time support, every channel valid/finite/fresh at **every selected plateau point** (default coverage 1.0), and no session clamp at any point in the event. Keep valid-subset means/std/ok fractions for diagnostics but never label them a qualified common capture if subsets differ. Preserve age/skew as diagnostics; an age pass is not a simultaneity claim.
7. `qualified_peak` is true only for complete, continuous, target-evaluable, non-warmup events passing target tolerance and both capture gates. Partial/no-comparable-target events have null eligibility with reasons, not a numerical MISS. Compute target diagnostic error for warmup where possible but put warmup totals in their own population. Missingness/timing counters must label whether they include partial or warmup events.
8. Keep electrical sign separate from phase. Add optional `--expected-expiration-sign` (`positive`/`negative`, default unset); warn at most once per run with a mismatch count, based on complete consistent-phase events. Do not automatically flip sensor values or infer hose orientation. Do not change DAC motion based on this warning.

**Verify:** targeted `test_peak_policy.py`, `test_timing.py` and `test_reporting.py` → PASS. Cases: window1; rejected even window; lengths 5–8 under default; window9 with exactly one supported point; unsupported 10-slm edge over 9-slm interior; analytic equal/unequal-time parabolas; nonmonotonic time rejection; scan-age time shift; micros wrap; `[4,10,9,4,4]` with window1 reports plateau reference10 independently of interpolated10.4464; 10% pressure coverage/clamp/disjoint plateau never qualifies; complete warmup counted separately; partial bad pressures do not pollute main acceptance totals; configured reverse orientation warns without relabeling phase. Run all Python tests.

### Stage 8 — Persist enough evidence for deterministic replay (P2; M; medium fix risk)

**Covers F12 and preserves the new policy's meaning.**

1. Extend exclusive allocation from two related files to sample CSV, peaks CSV and `<base>_session.json`. Reserve all three with collision handling; never overwrite existing files. Write a versioned initial manifest before enabling recording. Finalize by atomic replacement of a task-owned temporary manifest within the recordings directory. Disk failure leaves an explicitly incomplete manifest/file set; do not fabricate completion.
2. Manifest must contain protocol/CSV/analysis schema versions, run ID/mode/preset, exact resolved detector/averaging/quality configuration, expected sign policy, software hashes, firmware build ID and actual geometry/calibration constants, core version, flow-reference policy, time origins, start/end acknowledgement state, missing/invalid/TX-overrun counts, termination reason and tail status. Avoid secrets, raw environment dumps and private host paths.
3. Firmware supplies build/calibration metadata through bounded `# META_BEGIN,2,<build_id>`, repeated `# META,2,<key>,<value>`, and `# META_END,2,<build_id>` records, followed by `# READY_QUERY`, in response to the ready query. Keys/values use documented ASCII tokens with no embedded commas/newlines; required keys cover every manifest firmware field listed above. The firmware streams this response through the Stage 2 TX state machine over multiple passes instead of trying to enqueue the entire response at once. The logger rejects missing/duplicate required keys or mismatched BEGIN/END IDs and does not enable a v2 recording before the complete metadata response. Do not substitute the logger checkout's .ino hash for proof of the firmware actually flashed. Emit a deterministic firmware build identifier and named compiled constants; if the actual binary identity cannot be obtained, mark it unknown instead of guessing. Document how the build tool supplies the ID. These records must precede recording readiness.
4. Raw sample CSV includes the parsed wire values, segmentation `flow_avg`, acquisition/session/cycle fields, unwrapped and per-sensor times, and discontinuity reason/segment ID. Record non-row discontinuity boundaries so a malformed serial line can be reproduced even if it has no corresponding accepted CSV row. Store complete boundary events in the manifest (after_seq, before_seq, reason) or typed raw-file records with a specified schema. Pick the manifest event list for this implementation.
5. Use versioned new column names/semantics; preserve old files untouched. `csv.DictReader` consumers should validate schema instead of assuming original counts. Write a read-only `tools/replay_recording.py` entry point with `--session`, `--samples`, `--compare-peaks` that reconstructs the detector using saved settings, segment boundaries and raw rows; `flow_avg` is verified against deterministic recomputation from the recording boundary. Replay output goes only to an explicitly requested new path.
6. Compare the deterministic analysis fields with parsed saved peak values using per-column serialization tolerances (half the printed decimal unit); exclude host receipt wall time from analytic equality. State explicitly which fields are compared, fail on event-count/reason/status differences, and fail if configuration/provenance needed for replay is missing.

**Verify:** targeted `test_provenance.py` → PASS for filename collisions in any of three paths, no overwrite, initial/final manifest failure, abnormal close, nondefault averaging/settings, gap boundary events, variable sensor age, and exact event matching within recorded precision. Tests invoke the replay CLI as a subprocess against temporary files. Same settings replay identically; changing a policy version/config produces an explicit mismatch. No output is written to an old sample/peaks file. Run all software gates relevant so far.

### Stage 9 — Separate standard flow from geometric targets without guessing calibration (P2; M software + hardware evidence; high scientific risk)

**Covers F15 and calibration/percentage parts of A07.**

1. Preserve the current geometry, DAC centre/scale/pot constants and waveform. Rename/document the v2 target's unit as geometric **local L/min**; measured SFM flow remains **standard L/min**. Retain raw geometric values and expose the comparison reference explicitly. Do not silently apply a fixed 1.7%, 3.3% or 2.4% correction.
2. Add optional measured run conditions `--gas-temperature-c` and `--absolute-pressure-mbar`; require both together, finite, temperature above absolute zero, pressure positive. Use a separately tested pure conversion `Q_standard = Q_local * (P_local / 1013.0) * (293.15 / (T_c + 273.15))`. The default is **reference unresolved**, not invented ambient conditions. SFM scaling remains air/N2=140 unless verified hardware/gas configuration says otherwise. Update positive scoring fixture factories to supply explicit 20 C / 1013 mbar conditions; tests for unresolved conditions must continue asserting null eligibility rather than weakening the new policy.
3. Without comparable reference conditions, retain measured peaks and geometric targets but set `target_met`/target qualification to null with `flow_reference_unresolved`. Segmentation may use the nominal geometric target magnitude as a documented threshold heuristic; record that basis. With supplied conditions, segmentation and target comparison use the resolved standard target. Save inputs and conversion assumptions in the manifest.
4. Pressure-chip average temperature is not automatically gas temperature. Treat humidity/composition/leakage/compliance and actual piston motion as measurement limitations, not additional guessed correction terms. Document that supplied conditions are per run and cannot represent fast varying conditions without further instrumentation.
5. Record `DAC_HALF_RANGE` scale interpretation and the half-stroke percentage convention in `docs/flow-reference.md`. Preserve current numeric output until calibration evidence exists; label it normalized to the configured half-stroke count scale rather than measured percent of full stroke. Do not change the inherited constants in this implementation.
6. Specify a rig measurement worksheet: current Jrk scaling export/version, known commanded deltas, measured piston displacement, H/X pot pairs, gas temperature/absolute pressure instrument identity and uncertainty. Numeric recalibration is a separate decision after measurements; unresolved fields remain explicitly unresolved in the release report.

**Verify:** targeted `test_flow_reference.py` → PASS: identity at 20 C/1013 mbar; ratios 293.15/298.15 and 293.15/303.15 at 25/30 C; pressure proportionality; negative signed flow symmetry; rejected invalid/missing condition pairs; no-condition event is unscored, not MISS; supplied-condition replay matches. Native geometry/DAC golden tests remain unchanged. Physical accuracy remains a Stage 11 gate, not a passed unit test.

### Stage 10 — Finish integrity, diagnostic and documentation repairs (P2/P3; M; medium fix risk)

**Covers A01/A03/A04/A05/A06/A07 not already closed.**

1. Read the SFM third CRC byte in `sfm3000ReadRaw`, validate using the documented SFM CRC parameters (poly0x31; verify its initialization in the sensor application note before sharing SDP helper), and reject short/corrupt words while retaining last-good value with invalid flag/age. Update both boot discard and recovery reads consistently. Two-byte reads were protocol-permitted; document this as strengthened integrity, not a corrected address/command. Do not imply command retries recover lockups that require power cycling.
2. Separate parsing, detector, CSV-formatting and filesystem error boundaries. Actual OSError gets storage classification; unexpected detector exceptions retain traceback/type and enter a defined analysis-fault teardown. Never label a detector ValueError as file I/O. Prevent repeated failing detector flush during teardown; close each resource best-effort and stop host heartbeat if the owned acquisition cannot continue under its declared policy. Preserve raw partial files and fault metadata unless the user requested abort/discard.
3. `_stop`-requested normal close suppresses expected read/write-close errors; genuine unexpected loss remains reported. Reader, timer and UI shutdown converge without deadlocks or post-close writes. Test failures in both CSV streams and manifest updates.
4. Plot invalid history as gaps/clearly invalid samples; autoscale only finite valid points and handle an empty valid window. Keep last-good numeric telemetry stored, but do not paint a false continuous measurement. Surface motion active with recording absent in the plot status.
5. Summary populations: complete evaluable non-warmup; warmup; partial; discarded; target-reference-unresolved; missing commanded phases. Derive expected phases from commanded cycle/session interval rather than detected-event count. Report partial first/last phases separately; do not invent misses for intentionally truncated boundaries. Per-population pressure/timing/clamp/continuity reasons remain queryable.
6. Correct millis comment, centered-average documentation, R15/one-scan claims, Wire1 recovery header, recovery transaction claim, SDP `0x361E` temperature-compensation comment, local/standard flow labels, actual `python Data_Logger.txt` usage, nonexistent historical test reference, normal-port-reset assumption, and overstrong “true flow peak” timing claim. Replace the “at most one second power-loss” statement with an accurate buffer/durability policy; periodic flush is not fsync. Document settings that now intentionally fail validation or produce unscored results.

**Verify:** targeted `test_reporting.py`, native CRC tests, all Python tests and real build → PASS. CRC corruption makes flow invalid and triggers continuity handling; good words keep old scale; detector/storage errors have distinct labels; normal close prints no connection-lost warning; invalid plots have no nonfinite axis limits; all summary counts match fixture event populations. `git diff --check` passes. Verify docs examples with `python3 Data_Logger.txt --help` under Agg (no serial connection).

### Stage 11 — Complete integrated regression and record hardware limits (P1 release gate; M plus rig time; high validation risk)

1. Add `test_release.py` end-to-end scenarios combining the actual parser, session lifecycle, saved files and detector. Use the native firmware output as a fixture source so field semantics are not independently duplicated. Test normal recording, dropped flow, lost/partial serial records, warmup, stale session, full TX, timeout, manual override and reset. Validate matching control markers, loss counts, partial status and replay.
2. Release tests must reject all temporary expected-failure/skip markers, unresolved default schema versions and rows falsely qualified across gaps. Update the README stage statuses with observed command output summaries, not intended results. Run CodeRabbit on the actual implementation diff if available/required; review errors are recorded as blocked, never as zero findings.
3. Prepare `docs/hardware-validation-results.json` with explicit entries and status `not_run`, `pass`, `fail`, or `blocked`, evidence paths, deployed core/build identity and measurement instruments. `test_release.py` validates the schema and rejects a claimed hardware pass without evidence; it must not treat `not_run` as a physical pass.
4. On an authorized physical rig, perform the documented checks: stop consuming USB while connected; unplug during active output; kill host immediately after restart; inject/read sensor failures; compare actual DAC tick intervals and watchdog response against the Stage 5 budgets; confirm scan IDs/times with a logic analyzer; inspect H/X and known-delta calibration; verify flow reference conditions. Acquire a fresh stable breathing recording to check qualified-peak yield after stricter filtering. Keep fault tests within the rig operator's established procedure.
5. With no rig, complete software gates and record **BLOCKED — hardware verification unavailable** for this stage's physical portion. Do not claim resolved physical USB behavior or calibrated flow/position. This is the expected current-sandbox limitation, not permission to omit the software work.

**Verify:** `bash tools/verify.sh` → exit 0, complete suite with no temporary expected failures/skips, native and actual Arduino build pass. `git diff --check` → exit 0. Hardware results schema test passes independently of hardware outcomes; hardware closure requires recorded measurements and pass entries, otherwise the index retains BLOCKED hardware status.

## Test plan: required regression inventory

Use new `tests/test_baseline.py` / `tests/helpers.py` as the structural pattern; no pre-existing repository test file exists. Keep fixtures synthetic and fake clocks deterministic. These cases define acceptance, not just suggested examples:

| Owning test | Required invariant |
|---|---|
| `test_control.py` | No heartbeat after unconfirmed stop; no hold-success claim without ACK; generation/lock correctness; owned restarts protected. |
| `test_protocol.py` | Explicit v1/v2 distinction, 44-field DATA2 map, start/end ordering, framed parser bounds, stale-run rejection, final-tail accounting. |
| `test_continuity.py` | No complete/qualified event across missing/invalid/reset data; baseline re-arm; finite arithmetic recovers; no stale-average zero peak. |
| `test_peak_policy.py` | Only fully supported smoothing candidates; coherent plateau reference; sparse/stale/disjoint/clamped captures fail qualification. |
| `test_timing.py` | Correct wrap-aware flow timestamps; actual-time parabola; invalid/reused/nonmonotonic acquisition excluded. |
| `test_provenance.py` | Exclusive three-file allocation, interruption metadata, configuration capture, gap event persistence, deterministic replay. |
| `test_flow_reference.py` | Explicit local/standard conversion or unscored result; unchanged physical calibration constants. |
| `test_reporting.py` | Accurate populations, fault classification, normal close, masked invalid plots and configurable orientation warning. |
| Native harness | Real .ino executes bounded TX/RX/I2C work, watchdog, common schedule, mux ownership, CRC, geometry and wrap cases. |
| `test_release.py` | Cross-component scenarios, no temporary failing/skip markers, recorded hardware status cannot be mistaken for pass. |

## Done criteria

- [x] Every F01–F15/A01–A07 row in the index maps to an implemented/tested stage or an explicit hardware-blocked item.
- [x] `bash tools/verify.sh` exits 0 with no unexpected/expected failures or skipped software regression cases.
- [x] Native harness includes the real sketch and enforces timing/ordering/CRC invariants; it is not a duplicate firmware implementation.
- [x] Actual UNO R4 WiFi build uses the pinned documented core and fits the stated RAM budget.
- [x] New and legacy protocol/schema tests pass; firmware and logger are released as a compatible pair, with explicit legacy restrictions.
- [x] Fresh synthetic recording plus manifest reproduces all deterministic peak fields, statuses, counts and reasons.
- [x] Calibration constants/geometry/motion-profile invariants remain unchanged unless a separately approved evidence-based calibration change supersedes this plan.
- [x] No source/support edits outside the Scope list; unrelated recordings and user changes remain untouched.
- [x] `git diff --check` exits 0; plan index contains exact executed gate commands/outcomes and truthful software/hardware statuses.
- [x] Physical checks are either supported by measurements or clearly BLOCKED; overall plan is not marked fully DONE while required hardware work remains outstanding.

## STOP conditions

Stop the dependent stage and report, while preserving completed independent work, if:

- Baseline source has unexplained drift, protocol/CSV consumers outside this checkout impose incompatible requirements, or implementation requires an out-of-scope file.
- The tested Arduino core's write/capacity contract cannot support bounded chunks without a core patch. Do not vendor a patched core or rely on elapsed-time checks outside a blocking call.
- Native transaction budgeting cannot preserve mux ownership/fairness or RAM exceeds 24 KiB globals. Revisit the design before hiding failures with longer timeouts.
- Two reasonable attempts at a stage's verification still fail; do not weaken tests or skip the failing cases to proceed.
- Fixing a quality failure appears to require changing DAC calibration, geometry, feedback control or gas assumptions without measurements. Keep numeric settings unchanged and mark the measurement task blocked.
- The actual deployed core, sensor model or standard reference differs from the verified documentation. Reconcile that device contract before applying conversion/CRC changes.
- An acknowledgement wait needs a lock held by the reader, or heartbeat cancellation races with a new generation. Correct the state/lock design before proceeding.
- Hardware access or authorization is absent for physical tests. Finish and report software gates; leave physical checks blocked.

## Maintenance notes

Protocol, firmware queueing, acquisition snapshots, parser, Sample structure, CSV schemas and replay must change together. Version every analysis-policy change that can alter event count, time, target scoring or qualification. New sensor channels and rates invalidate both schema and scheduling-budget assumptions. New averaging settings must not depend on unrecorded history. Review stop paths before performance optimizations, and preserve the difference between commanded hold, confirmed firmware hold, and measured physical position.

The following are deliberately not new roadmap work: a web UI, cloud upload, plugin architecture, feedback-control redesign, automatic hose correction and an Arduino core migration. The prior audit supplies no requirement for them. Power-cycle hardware recovery and numeric recalibration need physical design evidence; the software should expose unresolved faults rather than claim universal recovery.
