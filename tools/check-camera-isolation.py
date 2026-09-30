#!/usr/bin/env python3
"""Build selected camera packages in empty target directories and audit artifacts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = {'rustcam-hal-common', 'rustcam-camera-api'}


def packages(text, names):
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert records and records[-1].get('reason') == 'build-finished'
    assert records[-1]['success'], 'Cargo build failed'
    artifacts = [record for record in records if record.get('reason') == 'compiler-artifact']
    assert artifacts, 'no compiler-artifact evidence'
    return {names[record['package_id']] for record in artifacts}


def check(text, names, expected):
    actual = packages(text, names)
    assert actual == expected, f'wrong compiled dependency set: {actual} != {expected}'
    return sorted(actual)


def self_test():
    names = {'api': 'rustcam-camera-api', 'error': 'rustcam-hal-common', 'bad': 'rustcam-native-backend'}
    def fixture(ids, success=True):
        return '\n'.join(json.dumps(r) for r in [
            *({'reason': 'compiler-artifact', 'package_id': i} for i in ids),
            {'reason': 'build-finished', 'success': success}])
    check(fixture(['api', 'error']), names, BASE)
    for text in [fixture(['api']), fixture(['api', 'error', 'bad']),
                 fixture(['api', 'error'], False), fixture([]), '']:
        try:
            check(text, names, BASE)
        except (AssertionError, KeyError):
            pass
        else:
            raise AssertionError('accepted incomplete or contaminated build evidence')
    print('PASS: five build-evidence rejection controls')


def run(out):
    out = out.resolve()
    assert not out.exists(), 'use a fresh output directory, not cached build evidence'
    out.mkdir(parents=True)
    metadata = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--locked', '--format-version=1', '--no-deps'], cwd=ROOT, text=True))
    names = {p['id']: p['name'] for p in metadata['packages']}
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (out / 'source.txt').write_text(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True))
    source = out / 'source.raw'
    source.write_bytes(bytes([7] * 4 + [9] * 4))
    cases = [
        ('api-core', 'rustcam-camera-api', ['--lib', '--target', 'thumbv6m-none-eabi'], BASE),
        ('api-wasm', 'rustcam-camera-api', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE),
        ('mock-wasm', 'rustcam-camera-mock', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE | {'rustcam-camera-mock'}),
        ('nuttx-core', 'rustcam-camera-nuttx', ['--lib', '--target', 'thumbv6m-none-eabi'], BASE | {'rustcam-camera-nuttx', 'rustcam-nuttx-support'}),
        ('native-example', 'rustcam-camera-native', ['--example', 'replay'], BASE | {'rustcam-camera-native'}),
        ('app-library', 'rustcam-applications', ['--lib', '--no-default-features'], BASE | {'rustcam-applications', 'rustcam-services', 'rustcam-camera', 'rustcam-storage', 'rustcam-storage-api', 'rustcam-transport', 'rustcam-transport-api'}),
    ]
    report = []
    for label, package, flags, expected in cases:
        target = out / (label + '-target')
        assert not target.exists()
        env = dict(os.environ, CARGO_TARGET_DIR=str(target))
        command = ['cargo', 'build', '--locked', '-p', package, *flags, '--message-format=json-render-diagnostics']
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
        (out / (label + '.jsonl')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        compiled = check(result.stdout, names, expected)
        if label == 'native-example':
            records = [json.loads(line) for line in result.stdout.splitlines()]
            executables = [m['executable'] for m in records if m.get('reason') == 'compiler-artifact' and m.get('executable')]
            assert len(executables) == 1
            execution = subprocess.run([executables[0], str(source)], check=True, capture_output=True, text=True, timeout=15)
            assert execution.stdout.strip() == 'CAMERA_ONLY_PASS'
            (out / 'native-example.log').write_text(execution.stdout)
        report.append({'case': label, 'compiled_packages': compiled})
        shutil.rmtree(target)
    for label, package, target, diagnostic in [
            ('reject-native-wasm', 'rustcam-camera-native', 'wasm32-unknown-unknown', 'native camera replay supports'),
            ('reject-nuttx-host', 'rustcam-camera-nuttx', None, 'NuttX descriptor support requires')]:
        directory = out / (label + '-target')
        command = ['cargo', 'check', '--locked', '-p', package, '--lib']
        if target:
            command += ['--target', target]
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, CARGO_TARGET_DIR=str(directory)), capture_output=True, text=True, timeout=240)
        (out / (label + '.stderr')).write_text(result.stderr)
        assert result.returncode != 0 and diagnostic in result.stderr, 'missing explicit provider rejection'
        shutil.rmtree(directory)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: six isolated builds, native replay execution and two unsupported-target rejections')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--out', type=Path, default=ROOT / 'target/camera-isolation')
    args = parser.parse_args()
    self_test() if args.self_test else run(args.out)
