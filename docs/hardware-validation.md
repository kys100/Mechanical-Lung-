# Hardware validation — pending

No rig is connected in the implementation sandbox. Native fake-clock results
validate software ordering and budgets; an Arduino build validates SDK integration.
Neither establishes physical USB, timing, electrical calibration or delivered flow.
Only perform physical tests under the rig operator's authorized procedure.

Record deployed binary/build/source/core identity, instrument model/configuration,
measurement files and outcome in hardware-validation-results.json. Use statuses
not_run, blocked, pass or fail; a pass requires real evidence paths and instruments.

Required measurements:

1. USB: stop consuming while still connected, resume, unplug during a partial
   record, and verify bounded service, whole record order and watchdog hold.
2. Ownership: restart after H and kill the host immediately; verify timeout hold.
   Check duplicate/stale tokens and manual H/X overrides on the real serial stack.
3. Sensor faults: inject read/timeouts; use a logic analyzer to confirm mux
   ownership, unique scan IDs, read completion ages and recovery wait timing.
4. Timing: measure DAC intervals and watchdog latency under full seven-channel
   failures and saturated USB. Software targets: DAC gaps <=16 ms with <=5 ms I2C
   and <=1 ms other work; watchdog hold by 3010 ms from last accepted heartbeat.
   Report actual measurements independently; don't replace them with harness data.
5. Calibration: inspect H/X and known-delta piston travel, actual Jrk configuration,
   pot conversion and the half-range scale ambiguity. Preserve constants until
   evidence supports an explicitly reviewed correction.
6. Flow: verify gas/model/reference temperature and absolute pressure. Acquire a
   fresh stable breathing recording and evaluate stricter qualification yield,
   sensor phase timing, peaks and replay against independently measured conditions.

Both Wire and Wire1 boot recovery clock their respective buses before begin.
Recovery timers/transactions are bounded in software; hardware faults requiring
power cycling remain possible. No flashing, wiring change or Jrk write has been
performed by this implementation task.
