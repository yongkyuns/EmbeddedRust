#!/usr/bin/env python3
"""Qualify bounded resource failures and pre-start closed-fd recovery on NuttX."""
import argparse
import json
from pathlib import Path
import re
import run as console


def verify(text, status, mode):
    lines = text.replace('\r', '').splitlines()
    assert not any(x in text for x in ('PANIC', 'panic:', 'panicked at', 'Assertion failed')), 'target failure'
    values = re.findall(r'^RUSTCAM_STATUS_([0-9]+)\s*$', status.replace('\r', ''), re.M)
    assert values == ['1' if mode == 'reject' else '0'], 'unclean NSH return'
    def reports(prefix):
        return [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
    markers = [line for line in lines if line.startswith('RUSTCAM_RESOURCE_MAIN ')]
    if mode == 'reject':
        assert lines.count('RUSTCAM_FD_SETUP_REJECTED') == 1
        assert not markers
        assert not any(line.startswith(('RUSTCAM_FD_PREPARED ', 'RUSTCAM_FD_RUST ',
                                        'RUSTCAM_FD_RETURN ', 'RUSTCAM_RESOURCE_REPORT ')) for line in lines)
        return
    assert 'RUSTCAM_FD_SETUP_REJECTED' not in text
    if mode == 'resources':
        assert markers == ['RUSTCAM_RESOURCE_MAIN resources']
        actual = reports('RUSTCAM_RESOURCE_REPORT ')
        assert len(actual) == 1
        report = actual[0]
        held = report.get('held_chunks')
        assert isinstance(held, list) and len(held) == 2
        assert all(type(n) is int and 0 < n < 160 for n in held), 'no bounded pressure witnessed'
        assert report == dict(heap_failures=2, heap_recoveries=2, held_chunks=held,
                              chunk_bytes=1048576, spawn_failures=3, spawn_recoveries=3,
                              oversized_started=False)
        assert not any(line.startswith('RUSTCAM_FD_') for line in lines)
    else:
        assert mode.startswith('fd-') and mode[3:] in list('01234567')
        mask = int(mode[3:])
        count = mask.bit_count()
        assert markers == ['RUSTCAM_RESOURCE_MAIN fds']
        assert reports('RUSTCAM_FD_PREPARED ') == [dict(mask=mask, closed=count)]
        actual = reports('RUSTCAM_FD_RUST ')
        assert len(actual) == 1 and set(actual[0]) == {'mask', 'fresh_fd'}
        assert actual[0]['mask'] == mask and type(actual[0]['fresh_fd']) is int
        assert actual[0]['fresh_fd'] >= 3, 'new open stole a standard descriptor'
        assert reports('RUSTCAM_FD_RETURN ') == [dict(mask=mask, recovered=count, rust_status=0)]
        assert not reports('RUSTCAM_RESOURCE_REPORT ')
        prepared = next(i for i, line in enumerate(lines) if line.startswith('RUSTCAM_FD_PREPARED '))
        entered = lines.index('RUSTCAM_RESOURCE_MAIN fds')
        returned = next(i for i, line in enumerate(lines) if line.startswith('RUSTCAM_FD_RETURN '))
        assert prepared < entered < returned, 'startup/return evidence out of order'


def self_test():
    resource = dict(heap_failures=2, heap_recoveries=2, held_chunks=[126, 126],
                    chunk_bytes=1048576, spawn_failures=3, spawn_recoveries=3,
                    oversized_started=False)
    text = 'RUSTCAM_RESOURCE_MAIN resources\nRUSTCAM_RESOURCE_REPORT ' + json.dumps(resource)
    status = 'RUSTCAM_STATUS_0\n'
    verify(text, status, 'resources')
    fd = '\n'.join(['RUSTCAM_FD_PREPARED ' + json.dumps(dict(mask=7, closed=3)),
                    'RUSTCAM_RESOURCE_MAIN fds',
                    'RUSTCAM_FD_RUST ' + json.dumps(dict(mask=7, fresh_fd=4)),
                    'RUSTCAM_FD_RETURN ' + json.dumps(dict(mask=7, recovered=3, rust_status=0))])
    verify(fd, status, 'fd-7')
    verify('RUSTCAM_FD_SETUP_REJECTED', 'RUSTCAM_STATUS_1', 'reject')
    invalid = [(text, 'RUSTCAM_STATUS_1', 'resources'), (text + '\nPANIC', status, 'resources'),
               (fd.replace('"fresh_fd": 4', '"fresh_fd": 0'), status, 'fd-7'),
               (fd.replace('"recovered": 3', '"recovered": 2'), status, 'fd-7'),
               (fd.replace('"rust_status": 0', '"rust_status": 1'), status, 'fd-7'),
               (fd.replace('"closed": 3', '"closed": 2'), status, 'fd-7'),
               (fd, status, 'fd-6'), (fd + '\n' + fd, status, 'fd-7'),
               (fd, status, 'reject'), ('RUSTCAM_FD_SETUP_REJECTED', status, 'reject'),
               (fd.splitlines()[-1] + '\n' + '\n'.join(fd.splitlines()[:-1]), status, 'fd-7'),
               (text + '\n' + text, status, 'resources')]
    for field, bad in [('heap_failures', 0), ('heap_recoveries', 0), ('spawn_failures', 0),
                       ('spawn_recoveries', 0), ('held_chunks', [160, 160]),
                       ('held_chunks', [0, 0]), ('oversized_started', True)]:
        invalid.append((text.replace(json.dumps(resource), json.dumps(dict(resource, **{field: bad}))),
                        status, 'resources'))
    for args in invalid:
        try:
            verify(*args)
        except (AssertionError, ValueError):
            continue
        raise AssertionError('resource oracle accepted invalid evidence')
    print(f'PASS: {len(invalid)} resource/descriptor rejection controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--output', type=Path, default=Path('target/nuttx-resources'))
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.image or not args.image.is_file():
            parser.error('--image must name the resource-test NuttX image')
        cases = [('resources', 'rust_resources resources')] * 2
        cases += [(f'fd-{mask}', f'rust_resources fds {mask}') for mask in range(8)]
        cases += [('reject', 'rust_resources fds-reject')]
        console.run_cases(args.image, args.output, cases, verify)
