#!/usr/bin/env python3
"""Compare matched whole-firmware C and ordinary Rust std footprints."""
import argparse
import hashlib
import json
from pathlib import Path

IGNORED = {'CONFIG_EXAMPLES_NXRS_STD_APP', 'CONFIG_EXAMPLES_NXRS_BENCH'}


def config_identity(path):
    lines = [
        line for line in Path(path).read_text().splitlines()
        if line.startswith('CONFIG_') and line.split('=')[0] not in IGNORED
    ]
    return hashlib.sha256(('\n'.join(sorted(lines)) + '\n').encode()).hexdigest()


def compare(c_dir, rust_dir):
    c_dir, rust_dir = Path(c_dir), Path(rust_dir)
    if config_identity(c_dir / 'resolved.config') != config_identity(rust_dir / 'resolved.config'):
        raise ValueError('C and Rust footprint images do not share matched NuttX configuration')
    c = json.loads((c_dir / 'image-size.json').read_text())
    r = json.loads((rust_dir / 'image-size.json').read_text())
    fields = ['text_bytes', 'data_bytes', 'bss_bytes', 'flash_like_bytes', 'static_ram_bytes']
    for record in [c, r]:
        for key in fields:
            if type(record.get(key)) is not int or record[key] < 0:
                raise ValueError(f'invalid footprint field: {key}')
    delta = {key: r[key] - c[key] for key in fields}
    return {
        'schema': 1,
        'scope': 'minimal-whole-linked-firmware',
        'c': {key: c[key] for key in fields},
        'rust_std': {key: r[key] for key in fields},
        'rust_minus_c': delta,
        'flash_ratio_rust_over_c': r['flash_like_bytes'] / c['flash_like_bytes'],
        'static_ram_ratio_rust_over_c': r['static_ram_bytes'] / c['static_ram_bytes'],
        'matched_kernel_config_sha256': config_identity(c_dir / 'resolved.config'),
        'interpretation': (
            'Whole-image delta with matched NuttX configuration and minimal app bodies. '
            'It includes Rust std/runtime/linkage effects and any unavoidable app/link-layout '
            'differences; it is not a language-intrinsic byte constant.'
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--c-dir', type=Path, required=True)
    p.add_argument('--rust-dir', type=Path, required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    result = compare(a.c_dir, a.rust_dir)
    text = json.dumps(result, indent=2) + '\n'
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
