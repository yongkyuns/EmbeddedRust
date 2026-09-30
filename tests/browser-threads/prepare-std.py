#!/usr/bin/env python3
"""Opt-in Emscripten TLS cleanup fix in a private, version-checked SDK copy."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

RELATIVE = Path('lib/rustlib/src/rust/library/std/src/sys/thread_local/mod.rs')
EXPECTED = '809ef5cfe9c60dd7ca99d587a9246751c1be338f'
GUARD = '            all(target_family = "wasm", not(target_env = "p3")),\n'
KEY = '            all(not(target_vendor = "apple"), not(target_family = "wasm"), target_family = "unix"),\n'
REPLACEMENT = ('            all(\n'
               '                target_family = "wasm",\n'
               '                not(target_env = "p3"),\n'
               '                not(all(target_os = "emscripten", target_feature = "atomics")),\n'
               '            ),\n')


def blob(data):
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()


def transform(text):
    assert text.count(GUARD) == text.count(KEY) == 1, 'unexpected TLS selection layout'
    return text.replace(GUARD, REPLACEMENT).replace(
        KEY, KEY + '            all(target_os = "emscripten", target_feature = "atomics"),\n')


def patch(data):
    assert blob(data) == EXPECTED, 'unexpected SDK source; review before updating the pin'
    return transform(data.decode()).encode()


def self_test():
    original = GUARD + KEY
    changed = transform(original)
    assert changed == REPLACEMENT + KEY + '            all(target_os = "emscripten", target_feature = "atomics"),\n'
    for bad in [KEY, GUARD, original + GUARD, original + KEY, changed]:
        try:
            transform(bad)
        except AssertionError:
            pass
        else:
            raise AssertionError('accepted missing, duplicate or already-patched SDK anchors')
    try:
        patch(original.encode())
    except AssertionError:
        pass
    else:
        raise AssertionError('accepted a different SDK hash')
    print('PASS: 6 TLS SDK patch rejection controls')


def prepare(source, output):
    original = (source / RELATIVE).read_bytes()
    changed = patch(original)
    destination = output / 'toolchain'
    assert not destination.exists(), 'private toolchain must be new'
    shutil.copytree(source, destination, symlinks=True)
    target = destination / RELATIVE
    assert target.resolve().is_relative_to(destination.resolve()), 'source symlink escapes SDK copy'
    target.write_bytes(changed)
    assert (source / RELATIVE).read_bytes() == original, 'installed SDK changed'
    (output / 'site/std-tls.patch').write_text(''.join(difflib.unified_diff(
        original.decode().splitlines(True), changed.decode().splitlines(True),
        fromfile=str(RELATIVE), tofile=str(RELATIVE))))
    (output / 'site/std-patch.json').write_text(json.dumps({
        'mode': 'emscripten-atomic-tls-key-cleanup', 'source_path': str(RELATIVE),
        'original_blob': blob(original), 'patched_blob': blob(changed),
        'installed_toolchain_unchanged': True,
    }, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.source is None or args.output is None:
            parser.error('--source and --output are required')
        prepare(args.source, args.output)
