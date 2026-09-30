#!/usr/bin/env python3
"""Fresh-process host transcript qualification; never MCU performance evidence."""
import argparse
import json
from pathlib import Path
import subprocess
from analyze import matched
from capture import POSIX
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('executable', type=Path)
p.add_argument('--rust', action='store_true')
a = p.parse_args()
cases = [('c-posix', c) for c in POSIX]
if a.rust:
    cases += [('rust-posix', c) for c in POSIX]
    cases += [(b, c) for b in ['rust-std', 'rust-ao'] for c in ['queue-hot', 'ping-pong']]
rows = []
for repeat in range(2):
    # Reverse order on alternate rounds; each measurement is a fresh process.
    for backend, case in cases if repeat == 0 else reversed(cases):
        args = [backend, case, '10000'] if a.rust else [case, '10000']
        result = subprocess.run([str(a.executable.resolve()), *args], capture_output=True, text=True, timeout=60, check=True)
        rows.append(dict(repeat=repeat, result=matched(result.stdout, backend, case, 10000)))
for args in ([['rust-ao', 'missing', '10'], ['rust-ao', 'queue-hot', '0']] if a.rust else [['missing', '10'], ['queue-hot', '0']]):
    result = subprocess.run([str(a.executable.resolve()), *args], capture_output=True, text=True, timeout=10)
    if result.returncode == 0 or 'RTBENCH {' in result.stdout:
        raise ValueError('invalid CLI accepted')
print(json.dumps(dict(runtime_kind='host', physical_timing_qualified=False, results=rows), indent=2))
