#!/usr/bin/env python3
"""Audit clean transport/app builds and independently receive real UDP packets."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('camera_isolation', ROOT / 'tools/check-camera-isolation.py')
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)
BASE = {'nxrs-hal-common', 'nxrs-transport-api'}
APP = BASE | {'nxrs-applications', 'nxrs-services', 'nxrs-service-event',
              'nxrs-camera', 'nxrs-camera-api', 'nxrs-storage',
              'nxrs-storage-api', 'nxrs-transport', 'nxrs-camera-native',
              'nxrs-storage-native', 'nxrs-transport-native'}


def check_packets(packets):
    assert len(packets) == 2, 'missing or extra datagram'
    assert [p['hex'] for p in packets] == ['007f80ff', b'transport-only'.hex()], 'wrong packet bytes/order'
    peers = [p['peer'] for p in packets]
    assert peers[0] == peers[1], 'unexpected sender change'
    assert len(peers[0]) == 2 and peers[0][0] == '127.0.0.1', 'wrong source address'
    assert isinstance(peers[0][1], int) and 0 < peers[0][1] <= 65535, 'wrong source port'


def execute(executable, out):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(('127.0.0.1', 0))
        receiver.settimeout(5)
        peer = f"127.0.0.1:{receiver.getsockname()[1]}"
        result = subprocess.run([executable, peer], check=True, capture_output=True, text=True, timeout=15)
        assert result.stdout.strip() == 'TRANSPORT_ONLY_PASS'
        packets = []
        for _ in range(2):
            data, source = receiver.recvfrom(65536)
            packets.append({'hex': data.hex(), 'peer': list(source)})
        check_packets(packets)
        receiver.settimeout(0.1)
        try:
            receiver.recvfrom(65536)
        except socket.timeout:
            pass
        else:
            raise AssertionError('unexpected extra datagram')
    (out / 'native-example.log').write_text(result.stdout)
    (out / 'packets.json').write_text(json.dumps(packets, indent=2) + '\n')


def run(out):
    out = out.resolve()
    assert not out.exists(), 'use a fresh output directory'
    out.mkdir(parents=True)
    metadata = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--locked', '--format-version=1', '--no-deps'], cwd=ROOT, text=True))
    names = {p['id']: p['name'] for p in metadata['packages']}
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (out / 'source.txt').write_text(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True))
    cases = [
        ('api-core', 'nxrs-transport-api', ['--lib', '--target', 'thumbv6m-none-eabi'], BASE),
        ('api-wasm', 'nxrs-transport-api', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE),
        ('mock-wasm', 'nxrs-transport-mock', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE | {'nxrs-transport-mock'}),
        ('native-example', 'nxrs-transport-native', ['--example', 'send'], BASE | {'nxrs-transport-native'}),
        ('native-app', 'nxrs-applications', ['--features', 'nxrs-applications/cli,nxrs-camera/native,nxrs-storage/native,nxrs-transport/native', '--bin', 'nxrs'], APP),
    ]
    report = []
    for label, package, flags, expected in cases:
        target = out / (label + '-target')
        assert not target.exists()
        result = subprocess.run(
            ['cargo', 'build', '--locked', '-p', package, *flags, '--message-format=json-render-diagnostics'],
            cwd=ROOT, env=dict(os.environ, CARGO_TARGET_DIR=str(target)), capture_output=True, text=True, timeout=240)
        (out / (label + '.jsonl')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        compiled = EVIDENCE.check(result.stdout, names, expected)
        artifacts = [json.loads(line) for line in result.stdout.splitlines()]
        assert not any(m.get('fresh', False) for m in artifacts if m.get('reason') == 'compiler-artifact'), 'cached evidence'
        if label == 'native-example':
            executables = [m['executable'] for m in artifacts if m.get('reason') == 'compiler-artifact' and m.get('executable')]
            assert len(executables) == 1
            execute(executables[0], out)
        report.append({'case': label, 'compiled_packages': compiled})
        shutil.rmtree(target)
    for label, package, target, diagnostic in [
            ('reject-native-wasm', 'nxrs-transport-native', 'wasm32-unknown-unknown', 'native transport supports'),
            ('reject-nuttx-host', 'nxrs-transport-nuttx', None, 'NuttX std transport requires target_os=nuttx')]:
        directory = out / (label + '-target')
        command = ['cargo', 'check', '--locked', '-p', package, '--lib']
        if target:
            command += ['--target', target]
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, CARGO_TARGET_DIR=str(directory)),
                                capture_output=True, text=True, timeout=240)
        (out / (label + '.stderr')).write_text(result.stderr)
        assert result.returncode != 0 and diagnostic in result.stderr, 'missing explicit provider rejection'
        shutil.rmtree(directory)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: five clean builds, capability-local HAL facades, real UDP and two target rejections')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'target/transport-isolation')
    run(parser.parse_args().out)
