#!/usr/bin/env python3
"""Reject host ELFs or firmware missing the shared Rust/NuttX execution path."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
header = (root / 'elf.txt').read_text()
assert re.search(r'Class:\s+ELF32', header), 'not a 32-bit firmware'
assert re.search(r'Machine:.*Xtensa', header), 'not Xtensa machine code'
assert not re.search(r'\bINTERP\b|\(NEEDED\)', header), 'host loader/runtime dependency'
symbols = {}
for line in (root / 'symbols.txt').read_text().splitlines():
    parts = line.split()
    if len(parts) == 3:
        symbols[parts[2]] = parts[1]
for name in ['rc_rust_std_main', 'rc_rust_abi_probe', 'rc_target_qualify',
             'rc_nx_camera_open', 'rc_nx_read', 'rc_nx_close_real', 'rc_nx_file_create_real', 'rc_nx_append',
             'open', 'read', 'write', 'lseek', 'ftruncate', 'fsync', 'socket', 'sendto', 'recvfrom',
             'pthread_create', 'pthread_join', 'sem_wait', 'clock_gettime', 'usleep']:
    assert symbols.get(name, '').upper() in {'T', 'W'}, f'missing target definition: {name}'
for legacy in ['rc_rust_run', 'rc_nx_udp_open', 'rc_nx_send']:
    assert legacy not in symbols, f'legacy core/UDP bridge leaked into std image: {legacy}'
image = root / 'nuttx/nuttx.merged.bin'
assert image.stat().st_size == 4 * 1024 * 1024, 'expected exactly 4 MiB flash image'
assert image.read_bytes()[0] == 0xe9, 'missing ESP boot image magic at offset zero'
print('PASS: 32-bit Xtensa std-main integration, target HAL/syscall symbols, no legacy UDP bridge or host loader')
