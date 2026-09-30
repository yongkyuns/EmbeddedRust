#!/usr/bin/env python3
"""Check selected storage packages and decode real output independently of Rust."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('camera_isolation', ROOT / 'tools/check-camera-isolation.py')
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)
BASE = {'rustcam-hal-common', 'rustcam-camera-api', 'rustcam-storage-api'}


def check_records(directory):
    paths = sorted(directory.iterdir())
    assert [p.name for p in paths] == [f'{i:020}.rcam' for i in (1, 2)], 'unexpected output files'
    for sequence, value, path in zip((1, 2), (7, 9), paths):
        raw = path.read_bytes()
        # Independent wire oracle: do not reuse the Rust encoder or decoder.
        header = (b'RCAMREC1' + (2).to_bytes(2, 'little') * 2 + bytes(4)
                  + sequence.to_bytes(8, 'little') + (sequence * 10).to_bytes(8, 'little')
                  + (4).to_bytes(8, 'little'))
        assert raw == header + bytes([value]) * 4, f'wrong committed record: {path}'


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
        ('api-core', 'rustcam-storage-api', ['--lib', '--target', 'thumbv6m-none-eabi'], BASE),
        ('api-wasm', 'rustcam-storage-api', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE),
        ('mock-wasm', 'rustcam-storage-mock', ['--lib', '--target', 'wasm32-unknown-unknown'], BASE | {'rustcam-storage-mock'}),
        ('nuttx-core', 'rustcam-storage-nuttx', ['--lib', '--target', 'thumbv6m-none-eabi'], BASE | {'rustcam-storage-nuttx', 'rustcam-nuttx-support'}),
        ('native-example', 'rustcam-storage-native', ['--example', 'record'], BASE | {'rustcam-storage-native'}),
    ]
    report = []
    for label, package, flags, expected in cases:
        target = out / (label + '-target')
        assert not target.exists()
        command = ['cargo', 'build', '--locked', '-p', package, *flags, '--message-format=json-render-diagnostics']
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, CARGO_TARGET_DIR=str(target)),
                                capture_output=True, text=True, timeout=240)
        (out / (label + '.jsonl')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        compiled = EVIDENCE.check(result.stdout, names, expected)
        artifacts = [json.loads(line) for line in result.stdout.splitlines()]
        assert not any(m.get('fresh', False) for m in artifacts if m.get('reason') == 'compiler-artifact'), 'cached evidence'
        if label == 'native-example':
            executables = [m['executable'] for m in artifacts if m.get('reason') == 'compiler-artifact' and m.get('executable')]
            assert len(executables) == 1
            directory = out / 'records'
            execution = subprocess.run([executables[0], str(directory)], check=True,
                                       capture_output=True, text=True, timeout=15)
            assert execution.stdout.strip() == 'STORAGE_ONLY_PASS'
            check_records(directory)
            (out / 'native-example.log').write_text(execution.stdout)
        report.append({'case': label, 'compiled_packages': compiled})
        shutil.rmtree(target)
    for label, package, target, diagnostic in [
            ('reject-native-wasm', 'rustcam-storage-native', 'wasm32-unknown-unknown', 'native storage supports'),
            ('reject-nuttx-host', 'rustcam-storage-nuttx', None, 'NuttX descriptor support requires')]:
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
    print('PASS: five isolated storage builds, independent record decoding and two target rejections')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'target/storage-isolation')
    args = parser.parse_args()
    run(args.out)
