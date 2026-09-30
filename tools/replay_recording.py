#!/usr/bin/env python3
"""Read-only replay of version-2 recordings; every peak field is compared.

Values are serialized with 12 significant digits. Numeric comparison permits
half the least printed unit plus floating point rounding; strings, statuses,
reason lists, vector lengths and event counts must match exactly.
"""
import argparse
import csv
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recording_schema as schema
from analysis import AnalysisSession
from peak_detection import PeakDetectionConfig


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
    if set(manifest['detector_config']) != set(asdict(PeakDetectionConfig())):
        raise ValueError('incomplete detector configuration')
    if set(manifest['firmware']) != schema.META_KEYS | {'build_id'}:
        raise ValueError('incomplete firmware metadata')
    if set(manifest['flow_reference']) != {'gas_temperature_c', 'absolute_pressure_mbar'}:
        raise ValueError('incomplete flow reference')
    if set(manifest['software_hashes']) not in ({'Data_Logger.txt', 'peak_detection.py'}, set(schema.SOFTWARE_FILES)):
        raise ValueError('incomplete software hashes')
    if any(not re.fullmatch('[0-9a-f]{64}', value) for value in manifest['software_hashes'].values()):
        raise ValueError('invalid software hash')
    if not isinstance(manifest['avg_window'], int) or isinstance(manifest['avg_window'], bool) or manifest['avg_window'] < 1:
        raise ValueError('invalid average window')
    if manifest.get('config_sha256') != schema.config_fingerprint(manifest):
        raise ValueError('configuration fingerprint mismatch')
    analysis = AnalysisSession(manifest['avg_window'],
                               PeakDetectionConfig(**manifest['detector_config']),
                               **manifest['flow_reference'])
    analysis.reset(manifest['start_ack']['millis'], manifest['start_ack']['micros'])
    events = []
    # Only non-row boundaries need explicit injection. Row loss/invalidity
    # transitions are re-derived from wire values by the same live parser.
    boundaries = [b for b in manifest['boundaries'] if b['before_seq'] is None]
    boundary_index = 0
    with open(samples, newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != schema.SAMPLE_COLUMNS:
            raise ValueError('sample columns do not match schema 2')
        for row in reader:
            while boundary_index < len(boundaries) and boundaries[boundary_index]['after_seq'] == analysis.last_seq:
                events.extend(schema.event_record(ev) for ev in analysis.break_continuity(boundaries[boundary_index]['reason']))
                boundary_index += 1
            parsed = schema.parse_wire(row['wire_line'])
            if parsed['protocol'] != 2 or parsed['run_id'] != manifest['run_id'] or parsed['preset'] != manifest['preset']:
                raise ValueError('sample belongs to another session')
            result = analysis.push(parsed)
            sample = result.sample
            # Verify segmentation history and per-sensor timing, not host receipt.
            computed = schema.sample_record(sample, row['wire_line'])
            for key in schema.SAMPLE_COLUMNS:
                if key != 'host_unix' and not cell_equal(computed[key], row[key]):
                    raise ValueError(f'sample {sample.seq} mismatch: {key}')
            events.extend(schema.event_record(ev) for ev in result.events)
    while boundary_index < len(boundaries) and boundaries[boundary_index]['after_seq'] == analysis.last_seq:
        events.extend(schema.event_record(ev) for ev in analysis.break_continuity(boundaries[boundary_index]['reason']))
        boundary_index += 1
    if boundary_index != len(boundaries):
        raise ValueError('unreplayable discontinuity boundary')
    events.extend(schema.event_record(ev) for ev in analysis.finish())
    with open(compare_peaks, newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != schema.PEAK_COLUMNS:
            raise ValueError('peak columns do not match schema 2')
        saved = list(reader)
    if len(events) != len(saved):
        raise ValueError(f'event count differs: replay {len(events)} / saved {len(saved)}')
    for i, (actual, expected) in enumerate(zip(events, saved)):
        for key in schema.PEAK_COLUMNS:
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
