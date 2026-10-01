#!/usr/bin/env python3
"""Real ESP32-S3/NuttX USERLED path; instrumented hardware lower half only."""
import argparse
import importlib.util
from pathlib import Path
import re

COMMON = Path(__file__).resolve().parents[1] / 'run.py'
spec = importlib.util.spec_from_file_location('nuttx_std_runner', COMMON)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
REPORT = 'NXRS_USERLED_REPORT rounds=32 controls=128 rejects=64 failed_query=1'


def verify(text, status, mode):
    lines = text.replace('\r', '').splitlines()
    assert lines.count('NXRS_USERLED_MAIN') == 1, 'wrong main entry count'
    assert not any(x in text for x in ('PANIC', 'panic:', 'panicked at', 'Assertion failed')), 'target failure'
    reports = [x for x in lines if x.startswith('NXRS_USERLED_REPORT ')]
    if mode == 'pass':
        assert reports == [REPORT], 'wrong/missing/duplicate hardware-path witness'
        assert 'NXRS_USERLED_INJECTED_FAILURE' not in text
        expected = '0'
    else:
        assert mode == 'fail'
        assert reports == []
        assert lines.count('NXRS_USERLED_INJECTED_FAILURE') == 1
        expected = '1'
    assert re.findall(r'^NXRS_STATUS_([0-9]+)\s*$', status.replace('\r', ''), re.M) == [expected]


def self_test():
    good = 'NXRS_USERLED_MAIN\n' + REPORT
    bad = 'NXRS_USERLED_MAIN\nNXRS_USERLED_INJECTED_FAILURE'
    verify(good, 'NXRS_STATUS_0', 'pass')
    verify(bad, 'NXRS_STATUS_1', 'fail')
    controls = [(good.replace('128', '127'), 'NXRS_STATUS_0', 'pass'),
                (good + '\n' + REPORT, 'NXRS_STATUS_0', 'pass'),
                (good.replace('NXRS_USERLED_MAIN', ''), 'NXRS_STATUS_0', 'pass'),
                (good + '\npanicked at', 'NXRS_STATUS_0', 'pass'),
                (good, 'NXRS_STATUS_1', 'pass'),
                (bad, 'NXRS_STATUS_0', 'fail'),
                (good, 'NXRS_STATUS_1', 'fail')]
    for values in controls:
        try:
            verify(*values)
        except AssertionError:
            continue
        raise AssertionError('oracle accepted invalid transcript')
    print(f'PASS: {len(controls)} USERLED transcript rejection controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('target/nuttx-esp32s3-std'))
    args = parser.parse_args()
    self_test()
    if not args.self_test:
        image = args.output / 'nuttx/nuttx'
        flash = args.output / 'nuttx/nuttx.merged.bin'
        assert image.is_file() and flash.is_file(), 'final target image missing'
        cases = [(mode, 'rust_std ' + mode) for mode in ['pass', 'pass', 'pass', 'fail']]
        runner.run_cases(image, args.output, cases, verify, esp32_image=flash)
