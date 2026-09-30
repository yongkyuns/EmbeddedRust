#!/usr/bin/env python3
"""Run direct std UDP on native or fresh NuttX kernels; require clean exit."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('nuttx_runner', ROOT.parent / 'run.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
EXPECTED = dict(messages=16, joined_workers=1, nonblocking=True, timeout=True,
                cloned_owner=True, independent_owner=True, empty_datagram=True, rebind=True)
PACKETS = [f'RUSTCAM_UDP_PACKET {n} 007f80ff' for n in range(16)]


def verify(text, status, mode):
    lines = text.replace('\r', '').splitlines()
    assert lines.count('RUSTCAM_UDP_ENTERED') == 1, 'missing/duplicate Rust entry'
    assert not any(word in text for word in ('PANIC', 'panic:', 'panicked at', 'Assertion failed', 'RUSTCAM_UDP_ERROR'))
    reports = [json.loads(line.removeprefix('RUSTCAM_UDP_REPORT '))
               for line in lines if line.startswith('RUSTCAM_UDP_REPORT ')]
    packets = [line for line in lines if line.startswith('RUSTCAM_UDP_PACKET ')]
    if mode == 'pass':
        assert reports == [EXPECTED] and packets == PACKETS, 'incomplete/wrong UDP result'
        assert 'RUSTCAM_UDP_INJECTED_FAILURE' not in text
        expected = '0'
    else:
        assert mode == 'fail' and not reports and not packets
        assert lines.count('RUSTCAM_UDP_INJECTED_FAILURE') == 1
        expected = '1'
    values = re.findall(r'^RUSTCAM_STATUS_([0-9]+)\s*$', status.replace('\r', ''), re.M)
    assert values == [expected], f'wrong exit status: {values}'


def self_test():
    good = '\n'.join(['RUSTCAM_UDP_ENTERED', *PACKETS, 'RUSTCAM_UDP_REPORT ' + json.dumps(EXPECTED)])
    fail = 'RUSTCAM_UDP_ENTERED\nRUSTCAM_UDP_INJECTED_FAILURE'
    verify(good, 'RUSTCAM_STATUS_0\n', 'pass')
    verify(fail, 'RUSTCAM_STATUS_1\n', 'fail')
    bad = [(good, 'RUSTCAM_STATUS_1', 'pass'), (fail, 'RUSTCAM_STATUS_0', 'fail'),
           (good + '\nPANIC', 'RUSTCAM_STATUS_0', 'pass'),
           (good + '\nRUSTCAM_UDP_ENTERED', 'RUSTCAM_STATUS_0', 'pass'),
           (good.replace(PACKETS[0], ''), 'RUSTCAM_STATUS_0', 'pass'),
           (good.replace('007f80ff', '00000000'), 'RUSTCAM_STATUS_0', 'pass'),
           (good.replace('"cloned_owner": true', '"cloned_owner": false'), 'RUSTCAM_STATUS_0', 'pass'),
           (good.replace('"empty_datagram": true', '"empty_datagram": false'), 'RUSTCAM_STATUS_0', 'pass'),
           (good.replace('"rebind": true', '"rebind": false'), 'RUSTCAM_STATUS_0', 'pass'),
           (good + '\nRUSTCAM_UDP_REPORT ' + json.dumps(EXPECTED), 'RUSTCAM_STATUS_0', 'pass'),
           (good, 'RUSTCAM_STATUS_1', 'fail')]
    for args in bad:
        try:
            verify(*args)
        except (AssertionError, ValueError):
            continue
        raise AssertionError('accepted invalid UDP transcript')
    print('PASS: eleven UDP transcript rejection controls')


def run(args):
    cases = [('pass', 'rust_std pass')] * 3 + [('fail', 'rust_std fail')]
    if args.native:
        args.output.mkdir(parents=True, exist_ok=True)
        for index, (mode, _) in enumerate(cases):
            result = subprocess.run([str(args.native.resolve()), mode], capture_output=True, text=True, timeout=30)
            (args.output / f'native-{index}-{mode}.log').write_text(result.stdout + result.stderr)
            assert result.returncode == (0 if mode == 'pass' else 7), 'wrong native exit code'
            verify(result.stdout + result.stderr, 'RUSTCAM_STATUS_' + ('0' if result.returncode == 0 else '1'), mode)
        print('PASS: native UDP and deliberate exit 7')
    else:
        # Require socket and baseline ABI evidence for this exact image/config.
        out = args.image.resolve().parents[1]
        abi = json.loads((out / 'socket-abi-report.json').read_text())
        assert abi['socket_abi_compatible'] and not abi['errors'], 'socket ABI not qualified'
        assert hashlib.sha256(args.image.read_bytes()).hexdigest() == abi['image_sha256'], 'changed image'
        assert hashlib.sha256((out / 'resolved.config').read_bytes()).hexdigest() == abi['config_sha256'], 'changed configuration'
        RUNNER.run_cases(args.image, args.output, cases, verify)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--native', type=Path)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--output', type=Path, default=Path('target/nuttx-udp'))
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif bool(args.native) == bool(args.image):
        parser.error('select exactly one of --native or --image')
    else:
        run(args)
