# Audit repair implementation plan

Generated with the **improve** skill on 2026-09-30 against `976bd8a58cb3400d102cf829f8c747d2042a12aa`.

Read [Plan 001: Make motion control, acquisition, and peak qualification auditable](001-fix-audit-findings.md) before implementation. It is a single self-contained handoff covering the requested previous audit, organized into eleven stage-sized changes. The software repairs have been implemented and independently verified through `e17d7edecc9f34595b65852d63bc6b712d0ddb42`. Required physical validation remains blocked because no rig is available.

The user selected the already-audited issues, so this follows the skill's `plan <description>` variant. The initial planning phase needed no additional selection question or broad re-audit. The user subsequently authorized plan publication, implementation, and code publication.

## Execution order and status

| Plan | Title | Priority | Effort | Depends on | Status |
|---|---|---|---|---|---|
| 001 | Motion control, acquisition and peak qualification repairs | P1 | L | — | BLOCKED — software DONE; physical validation unavailable |

Status values: TODO, IN PROGRESS, DONE, BLOCKED (with reason), REJECTED (with rationale). Update a stage only after its verification gates produce observed results. Overall DONE requires both software and required physical validation; software completion with no rig must leave the physical portion explicitly BLOCKED.

| Stage | Work package | Priority | Effort | Fix risk | Depends on | Status |
|---|---|---|---|---|---|---|
| 1 | Repository-owned Python/native/Arduino verification | P1 | M | LOW | — | DONE |
| 2 | Bounded USB/RX output and control-loop priority | P1 | L | HIGH | 1 | DONE |
| 3 | Watchdog ownership and acknowledged starts/stops | P1 | L | HIGH | 1, 2 | DONE |
| 4 | Recording identity and final-row drain barrier | P1 | M | MED | 3 | DONE |
| 5 | Common acquisition schedule and bounded I2C work | P1 | L | HIGH | 2, 4 | DONE |
| 6 | Continuity breaks, numeric validation and baseline re-arm | P1 | M | MED | 4, 5 | DONE |
| 7 | Supported smoothing, measurement timestamps and qualification | P2 | L | MED | 5, 6 | DONE |
| 8 | Session manifest, schema versions and deterministic replay | P2 | M | MED | 3–7 | DONE |
| 9 | Explicit flow reference and calibration boundaries | P2 | M + rig evidence | HIGH | 7, 8 | Software DONE; physical BLOCKED (no rig) |
| 10 | CRC, fault handling, summaries, plots and documentation | P2/P3 | M | MED | 3–9 | DONE |
| 11 | Integrated regression and physical validation | P1 release gate | M + rig time | HIGH | 1–10 | Software DONE; physical BLOCKED (no rig) |

Effort: S = hours, M = roughly a day, L = multiple days; estimates include tests and are planning ranges, not delivery commitments. Several stages touch the same functions: do not execute them concurrently in the same checkout. Dependency ordering takes precedence over ranking individual defects by severity.

## Vetted findings and coverage

The IDs preserve the previous audit's mapping. Confidence is HIGH for code/reproduced behavior; MED identifies a trigger or physical effect that still needs hardware evidence. Fix risk is the chance that the repair changes other behavior, not severity of the original problem.

| Finding | Category | Impact | Effort | Fix risk | Confidence | Evidence at planned revision | Stage |
|---|---|---|---|---|---|---|---|
| Verification baseline absent | tests/DX | Unblocks every repair; no tracked tests or build commands | M | LOW | HIGH | Tracked inventory: only three application files | 1 |
| F01: watchdog disarmed across hold/restart | correctness/control | HIGH: host loss can leave motion autonomous | M | HIGH | HIGH | `MechLung.ino:975,1022,1069`; `Data_Logger.txt:359,825` | 3 |
| F02: failed stop with continuing heartbeats | correctness/control | HIGH: fallback suppressed after host timer ends | M | HIGH | HIGH | `Data_Logger.txt:345,380,850,884` | 3 |
| F04/F05: serial/flow gaps produce complete events | correctness/data | Medium–High: fabricated completion and qualification | M | MED | HIGH | `Data_Logger.txt:453,466,531`; `peak_detection.py:144,152,185` | 6 |
| F06: reset/session/average state contamination | correctness/data | MED: merges recordings or creates a zero-flow peak | M | MED | HIGH | `Data_Logger.txt:447,560,650,825` | 4, 6 |
| F09: raw edges compete with smoothed candidates | correctness/analysis | MED: noise-dependent peak bias | M | MED | HIGH | `peak_detection.py:85,182,189` | 7 |
| F13: nonfinite serial values poison averages | correctness/input | MED: persistent invalid analysis after malformed input | S | MED | HIGH | `Data_Logger.txt:424,459,953` | 6 |
| F03: blocking USB prevents watchdog execution | performance/control | HIGH conditional risk | L | HIGH | HIGH for core control flow; MED for physical trigger | `MechLung.ino:1254,1325,1361`; Renesas 1.6.0 SerialUSB write loop | 2, 11 |
| F07: sensor/log schedules drift | correctness/timing | MED: repeated scans appear fresh | L | HIGH | HIGH | `MechLung.ino:1268,1290,1318` | 5 |
| F08: transaction timeouts accumulate per scan | performance/timing | MED: DAC command held through multiple ticks | L | HIGH | HIGH for simulated control flow | `MechLung.ino:557,575,631,1290` | 5, 11 |
| F14: closing before queued tail arrives | correctness/storage | MED: completed final phase becomes partial or absent | M | MED | HIGH | `Data_Logger.txt:502,741,850,874` | 4 |
| F10: qualification omits plateau/clamp integrity | analysis policy | MED: VALID can describe incomplete capture | M | MED | HIGH; stricter policy is a specified change | `peak_detection.py:216,230,278,287`; `Data_Logger.txt:613` | 7 |
| F11: row time used as flow-measurement time | correctness/timing | MED: biased timestamps and overstated alignment | L | MED | HIGH | `MechLung.ino:389,650,1322`; `peak_detection.py:196` | 5, 7 |
| F12: files omit analysis provenance | reproducibility | MED: peaks cannot be regenerated reliably | M | MED | HIGH | `Data_Logger.txt:691,702,1020,1069` | 8 |
| F15: geometric target versus standard flow | measurement model | MED: condition-dependent target bias | M + measurement | HIGH | HIGH for reference mismatch; MED for rig magnitude | `MechLung.ino:799,819,904` | 9, 11 |
| A01: flow CRC unused; recovery limitations | integrity | Improved flow error detection; no universal recovery claim | S | MED | HIGH | `MechLung.ino:374,335` | 10 |
| A02: plateau cutoff precedes refined peak | analysis policy | LOW–MED: plateau reference differs silently | S | MED | HIGH | `peak_detection.py:194,204,216` | 7 |
| A03: detector exceptions misclassified | reliability | MED: misleading failure and fragile teardown | M | MED | HIGH | `Data_Logger.txt:511,533,757,773` | 10 |
| A04: mixed summary populations/missing phases | reporting | LOW–MED: acceptance statistics are ambiguous | S/M | MED | HIGH | `peak_detection.py:255,267,284,289`; `Data_Logger.txt:791` | 7, 10 |
| A05: no orientation warning; mixed event phase | diagnostics | LOW–MED: hose/phase inconsistency unreported | S | LOW | HIGH | `peak_detection.py:140,247`; `Data_Logger.txt:583` | 6, 7 |
| A06: shutdown/display/durability claims | diagnostics/docs | LOW–MED: false disconnect or measurement continuity | S/M | LOW | HIGH for paths; close race timing unmeasured | `Data_Logger.txt:368,387,526,844,917,1214,1263` | 4, 10 |
| A07: incorrect or stale comments/calibration labels | docs/measurement | LOW plus calibration uncertainty | S + measurement | LOW/HIGH for numeric calibration | `Data_Logger.txt:69,86,167,1092`; `MechLung.ino:28,170,456,572,904,1297` | 9, 10 |

## Dependency and policy notes

- Fix verification first. Synthetic prior reproductions asserted buggy behavior; convert them to desired-behavior regression tests instead of treating their old assertions as acceptance tests.
- Bounded TX must precede acknowledgements; otherwise a stopped actuator may still be trapped trying to print its confirmation, and start acknowledgements can themselves block.
- Session IDs plus ordered end markers precede recording correctness. Resetting averages alone does not exclude previously queued rows from the same preset.
- Acquisition identity/time precedes reliable continuity and timing qualification. A missing serial row and a firmware-skipped slot are different loss sources.
- Manifest/replay follows stabilized protocol and detector policy. The final flow-reference stage extends that manifest and its tests.
- Policy choices are deliberate: reject even windows; independent default peak smoothing; strict complete pressure coverage for qualification; warmup separately reported; no target PASS/MISS when volume references cannot be compared. Document these compatibility changes rather than silently altering existing CSV semantics.
- Physical tests remain separate from the real firmware **compile**, which was already verified in the previous audit. Compilation cannot prove USB/actuator timing or calibration.

## Considered and rejected, or explicitly deferred

- **Another broad audit or product roadmap:** not needed; the user selected repairs from the completed audit. No new product-direction options are part of this request.
- **SFM two-byte read is a protocol violation:** rejected. Manufacturer documentation permits it; CRC is an integrity enhancement.
- **Add the old software travel clamp or feedback-driven DAC correction:** rejected. Existing design intentionally delegates configured travel/control to Jrk and records feedback diagnostically.
- **Apply a fixed 2.4% DAC correction or use pressure-chip temperature as gas temperature:** rejected without measurements. Stage 9 preserves numeric calibration and marks physical evidence unresolved.
- **Equal consecutive flow values prove a repeated scan:** rejected; quantization can repeat a valid reading. Use scan IDs/timestamps.
- **Advance only the sensor deadline:** insufficient; it can leave command/log alignment unresolved. Stage 5 coordinates the whole acquisition slot.
- **Require only min_samples >= smooth_window:** insufficient for interpolation with fully smoothed neighbours. Stage 7 tests supported neighbours separately.
- **Always permit rising-edge resumed fragments as complete:** rejected. Correct peak amplitude does not establish observed excursion onset.
- **Automatically reverse signs based on firmware phase:** rejected. Preserve independent electrical sign and configurable diagnostics.
- **Immediate guessed Arduino-core upgrade/vendor patch:** deferred. Validate the pinned contract first; an unprovable bounded-write implementation is a STOP condition.
- **Physical power-cycle recovery circuit or automatic recalibration:** deferred outside application edits. Expose persistent failure and require rig evidence.
- **Treat inability to record as a new silent defect:** rejected; existing code explicitly warns before motion-only operation. The plan keeps motion/recording state visible and truthful instead of broadening this into an unrelated product change.

## Historical planning validation and limits

Source hashes and revision match the previous audit; its software findings/build results remain applicable. Current recon reread the affected functions, the improve skill/template/playbook, audit evidence and validation record. No application tests/builds were rerun for these planning-only changes; no dependencies were installed in this turn. Plan verification commands are clearly labeled as future gates where the required files do not yet exist.

The planning-only phase did not implement or publish code or run a new CodeRabbit review. Its earlier source-audit review attempts were skipped/error. The subsequent execution and successful implementation reviews are recorded below. Physical USB, timing, position-calibration and standard-flow accuracy questions still require a rig.

## Execution evidence (2026-09-30)

**Software: DONE. Overall plan: BLOCKED only on required physical validation.**
The user authorized implementation and publication after approving the plan.
One executor used an isolated worktree; the reviewer read the full implementation,
all tests and final revision diffs, then independently checked the gates. Source
commit: `e17d7edecc9f34595b65852d63bc6b712d0ddb42`. Publication is restricted to
`coderabbit/audit-logger-peak-detector-firmware/51736d42`; a second remote branch
is not permitted by this workspace.

### Observed verification

Commands ran from the repository/worktree root with Python 3.9.25, pyserial 3.5,
Matplotlib 3.9.4, GCC 11.5.0, Arduino CLI 1.5.1 and core
`arduino:renesas_uno@1.6.0`.

| Check | Command / evidence | Result |
|---|---|---|
| Full software gate at `806d2bb` | `PATH=/tmp/mech-audit/venv/bin:$PATH ARDUINO_CLI=/tmp/mech-audit/arduino-cli bash tools/verify.sh` | PASS, independently rerun: 61 Python tests, 21 native scenarios plus explicit-core metadata check, real Arduino build, syntax and whitespace |
| Final host/integration suite at `e17d7ed` | `PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg /tmp/mech-audit/venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v` | PASS, independently rerun: 63 tests; no skipped or expected-failure cases |
| Final native/build coverage | Compared `git diff --name-only 806d2bb..e17d7ed`; only logger and two Python tests changed | PASS reused: native source, harness, scripts, dependencies and toolchain identical |
| UNO R4 memory | Actual `arduino:renesas_uno:unor4wifi` compile | 72,388 bytes flash; 16,776 globals; 15,992 remaining, below 24 KiB global limit; warnings in core only |
| Syntax and CLI | Python `compile()` for both modules; `PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg /tmp/mech-audit/venv/bin/python Data_Logger.txt --help` | PASS at final source |
| Full patch hygiene | `git diff --check 7fc74b7..HEAD` | PASS |
| Calibration/model preservation | Compared 14 declarations and seven entire geometry/waveform function bodies to `976bd8a`, ignoring comments/whitespace | PASS; no calibration or waveform changes |
| Reproduction from files | Actual-sketch output through split-frame host input, recording, detector and replay CLI; normal and malformed/lost-row sessions | PASS in integration suite |
| Physical measurements | Six entries in [hardware results](../docs/hardware-validation-results.json) | BLOCKED; no rig, instrument evidence, flashing or Jrk changes |

The `/tmp/mech-audit` tool locations are sandbox-specific. The root README gives
portable setup commands and tool overrides.

### Reviews and resolved findings

- CodeRabbit first implementation pass completed with **four findings**: one
  major safety-override path issue and three minor recovery-count, timeout-setter
  and help-text issues. All four were resolved and covered by checks.
- Its second pass reviewed the full implementation and reported **zero findings**.
- A final incremental pass reviewed the last logger/cleanup regressions and
  reported **zero findings**. No authorization/network blocker affected these
  implementation reviews.
- Manual review also repaired partial-record formatting, session/generation
  races, deadline accounting, manifest completion ordering, stale handshakes,
  per-session loss counts, sensor-specific CRC vectors, full uint32 final sequence
  output, continuity-callback error classification, core identity, recovery
  display state and compound allocation cleanup failures. The initially failing
  gap/storage-error reproduction now passes without escaping or misclassification.

### Implementation choices and remaining limits

- Logger and firmware use protocol 2 together. Legacy DATA is display-only for
  the new logger; recording allocation failure prevents START.
- Completed run IDs are retained without eviction for **64 owned sessions per
  boot**. Exhaustion rejects new starts until a deliberate board reset, rather
  than allowing a delayed completed ID to restart motion.
- Build and core identities are supplied by the verified build script. Unverified
  direct builds report `unknown`; source hashes do not attest a deployed binary.
- Target scoring requires supplied measured gas temperature and absolute pressure.
  Without them, peaks remain recorded and targets are unscored.
- Physical USB behavior, timing, calibration and qualification yield remain
  unverified. Keep the overall plan BLOCKED until actual rig evidence closes
  [the hardware procedure](../docs/hardware-validation.md).
