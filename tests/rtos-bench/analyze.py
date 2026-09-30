#!/usr/bin/env python3
"""Validate benchmark transcripts and refuse unqualified physical comparisons."""
import argparse
import json
from pathlib import Path
import re

CASES = {'semaphore-hot', 'heap128', 'queue-hot', 'yield-alone', 'semaphore-handoff', 'ping-pong'}
BACKENDS = {'c-posix', 'rust-posix', 'rust-std', 'rust-ao'}

def matched(text, backend, case, count):
    if re.search(r'RTBENCH FAIL|TM_PORT FAIL|ERROR:|panicked|Assertion failed', text):
        raise ValueError('failure text in transcript')
    rows = [json.loads(line[len('RTBENCH '):]) for line in text.splitlines() if line.startswith('RTBENCH ')]
    if len(rows) != 1:
        raise ValueError('expected exactly one complete RTBENCH result')
    row = rows[0]
    for key, expected in dict(schema=1, backend=backend, case=case, iterations=count, capacity=8, valid=True).items():
        if row.get(key) != expected or (key in ['schema', 'iterations', 'capacity'] and type(row.get(key)) is not int):
            raise ValueError(f'unexpected {key}')
    if type(row['valid']) is not bool or backend not in BACKENDS or case not in CASES:
        raise ValueError('invalid result identity')
    for key in ['elapsed_ns', 'clock_resolution_ns']:
        if type(row.get(key)) is not int or row[key] <= 0:
            raise ValueError(f'invalid {key}')
    for key in ['policy', 'priority']:
        if type(row.get(key)) is not int or row[key] < 0:
            raise ValueError(f'missing actual scheduling {key}')
    if case == 'ping-pong':
        if backend not in ['rust-std', 'rust-ao'] or row.get('receiver_parked_verified') is not False:
            raise ValueError('unsupported blocked-receiver claim')
        if row.get('instrumentation') != 'round-trip-sampled':
            raise ValueError('wrong timing boundary')
        for key in ['p50_upper_ns', 'p99_upper_ns', 'max_ns', 'worker_stack_requested', 'worker_policy', 'worker_priority']:
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError(f'invalid {key}')
        if row['p50_upper_ns'] > row['p99_upper_ns']:
            raise ValueError('unordered percentile bounds')
    elif row.get('instrumentation') != 'interval-only':
        raise ValueError('unexpected sampling overhead')
    if 'heap_supported' in row:
        if type(row['heap_supported']) is not bool:
            raise ValueError('invalid heap_supported')
        heap_fields = [
            'heap_used_before', 'heap_used_setup', 'heap_used_active', 'heap_used_after',
            'heap_peak_before', 'heap_peak_after',
            'heap_largest_free_before', 'heap_largest_free_after',
        ]
        for key in heap_fields:
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError(f'invalid {key}')
        if row['heap_supported'] and row['heap_peak_after'] < row['heap_peak_before']:
            raise ValueError('heap peak moved backwards')
    if count < 1 or count > 10000000:
        raise ValueError('invalid operation count')
    return row

def thread_metric(text, seconds=30):
    if 'TM_PORT FAIL' in text or 'panicked' in text or 'Assertion failed' in text:
        raise ValueError('port/kernel failure')
    rows, pending = [], None
    for line in text.splitlines():
        title = re.search(r'\*\*\*\* Thread-Metric (.+?) Test \*\*\*\* Relative Time:\s*(\d+)', line)
        if title:
            if pending is not None:
                raise ValueError('incomplete preceding window')
            pending = dict(test=title[1], relative_seconds=int(title[2]), valid=True, errors=[])
        elif 'ERROR:' in line:
            if pending is None: raise ValueError('unattributed benchmark error')
            pending['valid'] = False
            pending['errors'].append(line.strip())
        elif total := re.search(r'Time Period Total:\s*(\d+)', line):
            if pending is None: raise ValueError('counter without window identity')
            pending['count'] = int(total[1])
            if pending['count'] == 0:
                pending['valid'] = False; pending['errors'].append('zero progress')
            rows.append(pending); pending = None
    if pending is not None or len(rows) != 2:
        raise ValueError('exactly two complete windows required')
    if [r['relative_seconds'] for r in rows] != [seconds, 2 * seconds]:
        raise ValueError('unexpected window duration/order')
    if rows[0]['test'] != rows[1]['test']:
        raise ValueError('mixed tests')
    return dict(schema=1, suite='thread-metric', window_seconds=seconds,
                reference_duration=seconds == 30, windows=rows,
                valid=all(r['valid'] for r in rows), report_exact_reproduction=False)

def compare(left, right):
    """Caller supplies captured provenance, not a MHz-scaled inferred platform."""
    a, b = left['environment'], right['environment']
    required = ['runtime_kind', 'board', 'clock_hz', 'kernel_revision', 'kernel_config_sha256',
                'build_profile', 'measurement_session']
    for key in required:
        if a.get(key) in [None, '', 'unknown', 'unmeasured'] or a.get(key) != b.get(key):
            raise ValueError(f'unmatched/unknown environment: {key}')
    if a['runtime_kind'] != 'physical':
        raise ValueError('host/QEMU results qualify behavior, not MCU comparative performance')
    x, y = left['result'], right['result']
    # Revalidate imported JSON through the same transcript contract.
    for r in [x, y]: matched('RTBENCH ' + json.dumps(r), r['backend'], r['case'], r['iterations'])
    for key in ['case', 'iterations', 'capacity', 'policy', 'priority', 'instrumentation',
                'worker_policy', 'worker_priority', 'worker_stack_requested']:
        if x.get(key) != y.get(key): raise ValueError(f'unmatched experiment: {key}')
    # Nominal resolution is not accuracy, but under-resolved measurements
    # cannot support comparative physical latency claims. Preserve raw results.
    for r in [x, y]:
        if r['elapsed_ns'] < 100 * r['clock_resolution_ns']:
            raise ValueError('measurement interval is under-resolved')
        if r['case'] == 'ping-pong' and r['p50_upper_ns'] < 10 * r['clock_resolution_ns']:
            raise ValueError('round-trip distribution is under-resolved')
    pair = {x['backend'], y['backend']}
    if len(pair) != 2:
        raise ValueError('implementation comparison requires distinct backends')
    if pair == {'c-posix', 'rust-posix'}: meaning = 'caller-loop-and-bindings (shared C shim)'
    elif pair == {'rust-std', 'rust-ao'}: meaning = 'same-channel owner/wrapper comparison'
    elif x['case'] == 'queue-hot': meaning = 'different transport implementations; NOT language overhead'
    else: raise ValueError('no matched semantics for these backends')
    result = dict(meaning=meaning, left=x['backend'], right=y['backend'],
                  right_over_left_throughput=x['elapsed_ns'] / y['elapsed_ns'],
                  pure_context_switch_latency=False, hard_realtime_bound=False)
    if x.get('heap_supported') is True and y.get('heap_supported') is True:
        left_setup = x['heap_used_setup'] - x['heap_used_before']
        right_setup = y['heap_used_setup'] - y['heap_used_before']
        left_retained = x['heap_used_after'] - x['heap_used_before']
        right_retained = y['heap_used_after'] - y['heap_used_before']
        result.update(
            left_heap_setup_delta_bytes=left_setup,
            right_heap_setup_delta_bytes=right_setup,
            right_minus_left_heap_setup_bytes=right_setup - left_setup,
            left_heap_retained_delta_bytes=left_retained,
            right_heap_retained_delta_bytes=right_retained,
            right_minus_left_heap_retained_bytes=right_retained - left_retained,
        )
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['thread-metric', 'compare'])
    p.add_argument('files', type=Path, nargs='+')
    p.add_argument('--window-seconds', type=int, default=30)
    a = p.parse_args()
    if a.mode == 'compare':
        if len(a.files) != 2: p.error('compare needs two provenance/result JSON files')
        result = compare(*(json.loads(f.read_text()) for f in a.files))
    else:
        if len(a.files) != 1: p.error('thread-metric needs one complete transcript')
        result = thread_metric(a.files[0].read_text(), a.window_seconds)
    print(json.dumps(result, indent=2))
    if result.get('valid') is False: raise SystemExit(1)
if __name__ == '__main__': main()
