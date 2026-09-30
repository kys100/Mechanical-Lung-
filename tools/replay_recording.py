#!/usr/bin/env python3
"""Read-only replay of version-2 recordings; every peak field is compared.

Values are serialized with 12 significant digits. Numeric comparison permits
half the least printed unit plus floating point rounding; strings, statuses,
reason lists, vector lengths and event counts must match exactly.
"""
import argparse
import contextlib
import csv
import importlib.machinery
import importlib.util
import io
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('replay_logger', str(ROOT/'Data_Logger.txt'))
spec = importlib.util.spec_from_loader(loader.name, loader)
logger = importlib.util.module_from_spec(spec)
loader.exec_module(logger)

class OfflineSerial:
    def write(self, data):
        raise RuntimeError('replay must never send serial data')
    def close(self):
        pass


def numeric_equal(a, b):
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if not math.isfinite(a) or not math.isfinite(b):
        return a == b
    # CSV uses %.12g: half a unit at its final significant digit.
    scale = max(abs(a), abs(b))
    tolerance = 0 if scale == 0 else 0.5001 * 10**(math.floor(math.log10(scale))-11)
    return abs(a-b) <= max(tolerance, 1e-15)


def cell_equal(actual, saved):
    actual = str(actual)
    if actual == saved:
        return True
    try:
        a, b = json.loads(actual), json.loads(saved)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(cell_equal(x, str(y)) for x, y in zip(a, b))
    except (ValueError, TypeError):
        pass
    try:
        return numeric_equal(float(actual), float(saved))
    except ValueError:
        return False


def replay(session, samples, compare_peaks):
    manifest = json.loads(Path(session).read_text())
    for key in ('protocol_version', 'sample_schema', 'peak_schema', 'analysis_policy'):
        if manifest.get(key) != 2:
            raise ValueError(f'unsupported or missing {key}')
    required = ('start_ack', 'run_id', 'mode', 'preset', 'detector_config', 'avg_window',
                'flow_reference', 'boundaries', 'software_hashes', 'firmware', 'expected_expiration_sign')
    if any(key not in manifest for key in required) or not manifest['start_ack'] or not manifest['firmware']:
        raise ValueError('missing replay provenance')
    link = logger.SerialLink(None, 115200, manifest['avg_window'],
                             peak_config=logger.PeakDetectionConfig(**manifest['detector_config']),
                             expected_expiration_sign=manifest['expected_expiration_sign'],
                             serial_instance=OfflineSerial(), start_reader=False,
                             **manifest['flow_reference'])
    link.run_id = manifest['run_id']
    link.mode = manifest['mode']
    link.state = 'RUNNING'
    link._record_started = True
    link._record_expected_preset = manifest['preset']
    link._reset_analysis_state(manifest['start_ack']['millis'], manifest['start_ack']['micros'])
    events = []
    detector = logger.PeakFlowDetector(link.peak_config, lambda ev: events.append(logger.event_record(ev)))
    link._detector = detector
    # Only non-row boundaries need explicit injection. Row loss/invalidity
    # transitions are re-derived from wire values by the same live parser.
    boundaries = [b for b in manifest['boundaries'] if b['before_seq'] is None]
    boundary_index = 0
    with open(samples, newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != logger.SAMPLE_COLUMNS:
            raise ValueError('sample columns do not match schema 2')
        for row in reader:
            while boundary_index < len(boundaries) and boundaries[boundary_index]['after_seq'] == link._last_seq:
                link._break_locked(boundaries[boundary_index]['reason'])
                boundary_index += 1
            parsed = logger.parse_wire(row['wire_line'])
            if parsed['protocol'] != 2 or parsed['run_id'] != link.run_id or parsed['preset'] != manifest['preset']:
                raise ValueError('sample belongs to another session')
            sample = link._sample_from_wire(parsed, True)
            # Verify segmentation history and per-sensor timing, not host receipt.
            computed = logger.sample_record(sample, row['wire_line'])
            for key in logger.SAMPLE_COLUMNS:
                if key != 'host_unix' and not cell_equal(computed[key], row[key]):
                    raise ValueError(f'sample {sample.seq} mismatch: {key}')
            detector.push(sample)
    while boundary_index < len(boundaries) and boundaries[boundary_index]['after_seq'] == link._last_seq:
        link._break_locked(boundaries[boundary_index]['reason'])
        boundary_index += 1
    if boundary_index != len(boundaries):
        raise ValueError('unreplayable discontinuity boundary')
    detector.flush()
    with open(compare_peaks, newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != logger.PEAK_COLUMNS:
            raise ValueError('peak columns do not match schema 2')
        saved = list(reader)
    if len(events) != len(saved):
        raise ValueError(f'event count differs: replay {len(events)} / saved {len(saved)}')
    for i, (actual, expected) in enumerate(zip(events, saved)):
        for key in logger.PEAK_COLUMNS:
            if not cell_equal(actual[key], expected[key]):
                raise ValueError(f'peak {i+1} mismatch: {key}')
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--samples', required=True)
    parser.add_argument('--compare-peaks', required=True)
    parser.add_argument('--output', help='Optional new JSON path; exclusive creation')
    args = parser.parse_args()
    try:
        events = replay(args.session, args.samples, args.compare_peaks)
        if args.output:
            with open(args.output, 'x') as stream:
                json.dump(events, stream, indent=2)
        print(f'PASS replay: {len(events)} events, all deterministic fields match')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Replay failed: {exc}\n')

if __name__ == '__main__':
    main()
