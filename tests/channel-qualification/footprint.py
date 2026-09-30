#!/usr/bin/env python3
"""Fail-closed comparison of final linked artifacts from one controlled matrix."""
import argparse
import hashlib
import json
from pathlib import Path

VARIANTS = ('c-minimal', 'cq-core', 'cq-std', 'cq-thread', 'cq-std-channel',
            'cq-crossbeam', 'cq-select', 'cq-coexist')
FIELDS = ('text_bytes', 'data_bytes', 'bss_bytes', 'flash_like_bytes',
          'static_ram_bytes', 'elf_file_bytes')
PAIRS = (
    ('c-minimal', 'cq-core', 'minimal C to Rust core/entry'),
    ('cq-core', 'cq-std', 'minimal core entry to ordinary std startup'),
    ('c-minimal', 'cq-std', 'whole-image std deployment delta'),
    ('cq-std', 'cq-thread', 'thread/join feature use'),
    ('cq-thread', 'cq-std-channel', 'bounded standard channel feature use'),
    ('cq-std-channel', 'cq-crossbeam', 'equivalent-workload channel substitution'),
    ('cq-crossbeam', 'cq-select', 'additional queues and selection'),
    ('cq-crossbeam', 'cq-coexist', 'coexistence with an additional std workload'),
)
IDENTITY = ('scope', 'target', 'source_commit', 'lock_sha256', 'rustc', 'cc',
            'profile', 'kernel_config_sha256', 'platform_sha256',
            'workload_sha256', 'std_patch_driver_sha256', 'instrumented')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(record, verify_artifact=True):
    if record.get('schema') != 1 or record.get('variant') not in VARIANTS:
        raise ValueError('invalid schema or variant')
    identity = record.get('identity', {})
    if set(identity) != set(IDENTITY) or identity['instrumented'] is not False:
        raise ValueError('incomplete identity or instrumented size artifact')
    for key in IDENTITY:
        if key != 'instrumented' and identity[key] in (None, '', {}, []):
            raise ValueError('empty identity field: ' + key)
    metrics = record.get('metrics', {})
    for key in FIELDS:
        if type(metrics.get(key)) is not int or metrics[key] < 0:
            raise ValueError('invalid metric: ' + key)
    if metrics['flash_like_bytes'] != metrics['text_bytes'] + metrics['data_bytes']:
        raise ValueError('inconsistent flash proxy')
    if metrics['static_ram_bytes'] != metrics['data_bytes'] + metrics['bss_bytes']:
        raise ValueError('inconsistent static RAM proxy')
    artifacts = record.get('artifacts', {})
    if not isinstance(artifacts.get('elf'), str) or not isinstance(artifacts.get('sha256'), str):
        raise ValueError('missing linked artifact identity')
    if verify_artifact and sha256(artifacts['elf']) != artifacts['sha256']:
        raise ValueError('linked artifact hash mismatch')
    deployment_keys = {'deployment_image', 'deployment_sha256', 'deployment_bytes'}
    if deployment_keys.intersection(artifacts):
        if not deployment_keys.issubset(artifacts):
            raise ValueError('incomplete deployment artifact')
        if type(artifacts['deployment_bytes']) is not int or artifacts['deployment_bytes'] < 0:
            raise ValueError('invalid deployment size')
        if verify_artifact:
            image = Path(artifacts['deployment_image'])
            if image.stat().st_size != artifacts['deployment_bytes'] or sha256(image) != artifacts['deployment_sha256']:
                raise ValueError('deployment artifact mismatch')
    return record


def compare(records, verify_artifacts=True):
    by_name = {}
    for record in records:
        validate(record, verify_artifacts)
        name = record['variant']
        if name in by_name:
            raise ValueError('duplicate variant: ' + name)
        by_name[name] = record
    if set(by_name) != set(VARIANTS):
        raise ValueError('incomplete footprint matrix')
    reference = by_name['cq-std']['identity']
    for name, record in by_name.items():
        changed = [key for key in IDENTITY if record['identity'][key] != reference[key]]
        if changed:
            raise ValueError(f'unmatched build {name}: {changed}')
    differences = []
    for before, after, meaning in PAIRS:
        a, b = by_name[before]['metrics'], by_name[after]['metrics']
        differences.append({
            'before': before, 'after': after, 'meaning': meaning,
            'delta_bytes': {key: b[key] - a[key] for key in FIELDS},
            'delta_percent': {key: 100.0 * (b[key] - a[key]) / a[key] if a[key] else None
                              for key in FIELDS},
        })
    return {
        'schema': 1, 'identity': reference,
        'variants': [by_name[name] for name in VARIANTS], 'comparisons': differences,
        'interpretation': (
            'Linked-size evidence only. text+data is a flash-like proxy, data+bss '
            'is static RAM; neither includes task stacks or dynamic peak RAM. '
            'Full ELF bytes include debug/symbol metadata. Native dynamic linkage '
            'is not an MCU flash estimate. C/core/std entry differences are included; '
            'these are workload/build-specific deltas, not per-language constants. '
            'No future framework overhead is reported before that framework exists.'
        ),
    }


def markdown(result):
    lines = ['# Channel/runtime linked footprint', '',
             '| Variant | Text | Data | BSS | Flash-like | Static RAM | ELF file |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for record in result['variants']:
        lines.append('| ' + record['variant'] + ' | ' + ' | '.join(
            str(record['metrics'][key]) for key in FIELDS) + ' |')
    lines += ['', '| Comparison | Flash-like delta | Static RAM delta |',
              '| --- | ---: | ---: |']
    for row in result['comparisons']:
        lines.append(f"| {row['before']} -> {row['after']} | {row['delta_bytes']['flash_like_bytes']:+d} | {row['delta_bytes']['static_ram_bytes']:+d} |")
    return '\n'.join(lines) + '\n\n' + result['interpretation'] + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', nargs='+', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = compare([json.loads(path.read_text()) for path in args.records])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    args.out.with_suffix('.md').write_text(markdown(result))


if __name__ == '__main__':
    main()
