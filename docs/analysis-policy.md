# Analysis and recording policy 2

The host records a sample CSV, peaks CSV and `_session.json`. All three names are
reserved exclusively. Old files are never overwritten. Periodic stream flush
reduces Python buffering; it is not fsync and cannot promise power-loss durability.
The final manifest is atomically replaced only after stream flush/close attempts.
Storage/analysis/format/transport failures retain partial files and disable owned
heartbeats. A failed allocation prevents START. Explicit p discards only the
stopped session's paths. H preserves them. Unexpected reader failures retain a
traceback; normal close drains confirmation before stopping the reader. Peak operations return events. Storage and format errors are classified by the
recorder; analysis errors are classified at its analysis boundary. Failed recording
work is not retried during teardown, and detector statistics remain available.
Transport processes input and heartbeats independently of the bounded recording
worker. Queue overflow or latency above 1.5 seconds marks ownership unhealthy and
stops heartbeats. Accepted rows stay ordered ahead of ENDED finalization. A fault
arriving during final publication is applied before completion is signalled.
An explicit discard is deferred until the recording owner has closed its files.

Each accepted row must match the acknowledged ID and preset. STARTED resets
analysis and plot histories. Reset or another active identity interrupts the
capture; readiness must be negotiated again. A sequence/scan gap, nonpositive or
>15,000-us flow-time increment, changed missed-slot/drop counter, malformed DATA,
or invalid flow closes an open event as partial and clears segmentation history.
The gap limit is configurable and saved. Pressure failure alone preserves flow
segmentation but invalidates pressure quality.

Detection begins disarmed and re-arms only when both raw and trailing-average
magnitude are below the exit threshold. A gap preserves the previous latched
exit level. Sign reversal or phase/cycle transition above baseline is partial.
Warmup uses commanded cycle_id (first three cycles by default), never recovered
fragment count. --avg controls the segmentation trailing mean and live display.
--peak-smooth independently defaults to 9, must be odd, and min_samples must be
at least that window (default 9). Window 1 explicitly disables smoothing.

Only fully supported centered means can be peak or plateau candidates; unsupported
edges and short segments have NaN support sentinels. Interpolation uses three
supported samples at actual flow-completion times, with a concave finite vertex
between adjacent midpoints; otherwise the discrete result includes a reason.
A printed decimal is not measurement accuracy. Peak time is relative to STARTED.
Plateau threshold uses the discrete supported filtered maximum; its exported
reference differs intentionally from the optional interpolated peak.

`peak_sample_ok` requires finite valid flow/all seven pressures and acceptable
ages. `plateau_capture_ok` requires a contiguous plateau, every channel valid and
fresh at every selected point, and no sticky clamp anywhere in the event. Means,
standard deviations and valid fractions are still available diagnostically; age
bounds are not claims of simultaneous acquisition. `qualified_peak` is nullable:
only complete, comparable-target, non-warmup events can be true/false. Missing
reference, warmup and partial events carry reasons; they are not numerical misses.

Pressure/timing failures include any selected plateau point failing that gate.
Main target/qualification/pressure/timing totals include complete evaluable
non-warmup events only. Separate totals report warmup, partial, discarded and
unresolved-reference events. Commanded phase ordinals (2*cycle+phase) provide
missing interior phase counts independently of peaks; first and last phase
partial status is separate so truncated recording boundaries are not invented
misses. Optional --expected-expiration-sign emits one warning per run and counts
mismatches; it never changes signs, phase labels or motion.

## Replay

Raw schema 2 has named Sample fields plus the original wire_line; list-valued
columns are compact JSON. It includes the segmentation mean, all wire acquisition
fields, unwrapped row/flow/pressure times, segment ID and discontinuity reason.
Peak schema 2 serializes deterministic event fields (including pressure vectors
and reasons); exact column arrays are SAMPLE_COLUMNS/PEAK_COLUMNS in recording_schema.py.
Float scalars use 12 significant digits. Manifest boundaries preserve non-row
errors that otherwise disappear from raw CSV. The manifest includes complete
resolved config, firmware metadata, software hashes, flow conditions, start/end
ACK, counts and completion/tail status.

Run `python tools/replay_recording.py --session RUN_session.json --samples RUN.csv
--compare-peaks RUN_peaks.csv` on one shell line. Replay reads raw wire values,
recomputes averages/timestamps/segmentation, injects non-row boundaries, and checks
all deterministic sample and peak fields (host receipt wall time excluded).
Numeric tolerances are half the last significant decimal unit plus rounding;
event counts, flags and reasons are exact. Missing schemas/provenance fail.
`--output NEW.json` uses exclusive creation and is optional; input files remain
untouched. Replay success establishes reproducibility, not physical calibration.
