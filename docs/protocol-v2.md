# Mechanical lung protocol 2

Build both firmware and logger together. UNO R4 WiFi core `arduino:renesas_uno@1.6.0`
is the inspected target. A legacy 37-field `DATA` row remains displayable, but a
new timed recording requires protocol 2 and the complete metadata handshake.

## Commands and ownership

ASCII lines, at most 63 bytes before newline:

- `@START,<run_id>,<mode>\n`: mode P0, P1, P2, P3 or DEMO.
- `@PING,<run_id>\n`: heartbeat for exactly the active owned run.
- `@STOP,<run_id>\n`: stop acquisition and command centre immediately.

IDs are exactly 16 lowercase hexadecimal characters. They correlate sessions;
they are not authentication. START reserves STARTED and ENDED queue capacity
before motion. Duplicate active START does not reset motion or extend the lease.
The board remembers **64 completed IDs without eviction** and rejects new starts
when this storage is exhausted; a deliberate board reset is required. A delayed
START for any completed ID is rejected. Duplicate STOP for the most recently ended
ID retransmits the original marker. Another active ID cannot replace a run.

The incomplete-frame deadline is 250 ms. Malformed, overflowed and timed-out
frames are discarded through newline; their digits are never legacy commands.
Receive processing is limited to 32 bytes per pass. Plain 1–4, s, H/h/0, X/x, m,
? and ! remain available to Serial Monitor. Manual motion/hold commands terminate
an owned session first. `manual_override` does not prove the board remains at
centre: the operator may immediately request another mode. Bare ! cannot extend
an owned session. A legacy restart within the most recent !'s three-second lease
re-arms the watchdog; a run without host presence is autonomous.

## Markers and handshake

- `# BOOT,2` interrupts a recording and clears readiness.
- `# PROTOCOL,2`
- `# META_BEGIN,2,<build_id>`
- `# META,2,<key>,<value>` repeated once for each required key.
- `# META_END,2,<build_id>`
- `# READY_QUERY`
- `# STARTED,2,<run_id>,<mode>,<start_ms>,<start_us>`
- `# ENDED,2,<run_id>,<final_enqueued_seq>,<reason>,<tx_dropped_total>`

`?` streams capability/metadata/readiness in that order over multiple loop passes.
Required metadata keys: core, tidal_ml, bore_mm, stroke_mm, dac_centre,
dac_half_range, dac_corr_offset, dac_corr_gain, pot_raw_centre, pot_dac_per_adc,
calibration_target, slot_us, sfm_scale, flow_reference. Keys/values are ASCII
alphanumeric tokens plus `.`, `_`, `+`, `-`; commas/newlines are forbidden.
Missing/duplicate keys and mismatched build IDs prevent readiness. The build
script supplies the source SHA256 as MECH_BUILD_ID and supplies MECH_CORE_ID only
after verifying installed core 1.6.0. Unverified builds (including direct IDE
builds) report `unknown` for both identities unless explicitly supplied; source
identity does not prove a flashed binary identity. Constants
are formatted from the values actually compiled into the sketch.

ENDED reason is host_stop, watchdog, manual_override or transport_fault; final
sequence is -1 when no data row was enqueued. ENDED follows all retained rows,
including the partially transmitting row. No additional run row is generated
after hold. The host accepts matching tail rows while STOPPING; a missing marker,
sequence mismatch or transport loss leaves an incomplete recording. Start and
stop confirmation deadlines are two seconds. Heartbeats are serialized with and
disabled before STOP. Stop sends at most two attempts; no hold success is reported
without the matching marker.

## DATA2 (44 fields)

DATA2 preserves the 36 original values in order:

`seq, millis, flow_slm, flow_ok, flow_age_us, Psens1_pa..Psens7_pa,
psens_temp_c_avg, Psens1_ok..Psens7_ok, Psens1_age_us..Psens7_age_us,
cmd_dac, feedback_dac, cmd_pct, fdbk_pct, target_flow_slm, target_peak_slm,
phase, preset, clamped`

Then appends:

`run_id, scan_id, row_us, cycle_id, scan_start_us, missed_slots_total,
tx_dropped_total`

The historical target field names encode **local L/min**, while flow_slm is
standard L/min. Phase 0 is expiration, phase 1 inspiration; demo/idle phase is -1.
Preset -2 means demo, -1 idle, 0–3 presets. Counters and board clocks are uint32;
all flags are exactly 0 or 1. Invalid ages are -1; retained last-good values have
false validity. Floating fields must be finite. Each row describes one scan:
row_us is closure time, scan_start_us is its start, sensor ages are relative to
closure. A scan spanning a commanded phase transition has invalid sensor flags.
Read timestamps represent read completion, not the internal conversion instant.

One 10,000-us slot coordinates DAC, scan allocation and row generation. Late
slots are skipped arithmetically and counted, never replayed as duplicate scans.
Each runtime pass performs at most one I2C transaction; mux selection and action
are separate states. An incomplete scan closes at the next slot with unacquired
channels invalid. First mux channel rotates each slot to prevent starvation.
Recovery waits begin at transaction completion.

## Bounded transport

Eight fixed 640-byte records use about 5.2 KiB; telemetry/diagnostics may occupy at
most six. STARTED and ENDED have reserved capacity. The sole writer sends at most
min(USB capacity, remaining record, 64) once per pass. No synchronous prints or
flush loops remain. Whole new telemetry rows are dropped if full; partial records
are retained without interleaving. `tx_dropped_total` counts **data rows only,
per motion session**; diagnostic loss does not imply missing acquisition.
The single-writer capacity contract was checked against core 1.6.0. Physical USB
stall, reset and disconnect behavior still require the checks in hardware-validation.md.

The host readiness query sends a newline before `?` to discard any incomplete
frame left by a previous short write. Fault teardown invalidates capability and
metadata; a delayed READY marker alone cannot make a faulted connection runnable.

An explicit H/X override is still attempted after an unconfirmed protocol stop.
The host prefixes it with newline to end any partial frame, leaves the session
faulted and does not claim confirmation. The UI ? key renegotiates readiness
through the same resynchronization path; it is refused during an active run.
Firmware ERROR records, including completed-ID exhaustion, are shown to the user.
