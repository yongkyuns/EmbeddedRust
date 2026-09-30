#!/usr/bin/env python3
"""Link a Cargo binary to a relocatable NuttX input, retaining Rust startup.

Only C libraries supplied by the final NuttX link are deferred. No source main
is replaced, no host libc is used, and unresolved symbols must resolve in NuttX.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys


def arguments(args):
    kept, deferred = [], []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == '-l':
            index += 1
            arg += args[index]
        if arg in ('-lc', '-lm', '-lpthread'):
            deferred.append(arg)
        else:
            kept.append(arg)
        index += 1
    return kept + ['-r', '--gc-sections', '-u', 'main'], deferred


def prune_discarded_undefined(binary, prefix, evidence):
    """Remove GNU -r/GC's local undefined residue, never a referenced symbol.

GNU ld can retain LOCAL/UND symbols from discarded sections. They have no
remaining relocations but nm still prints U. Only those local entries are
candidates; global/weak imports and every defined symbol remain untouched.
objcopy --strip-symbols independently rejects a candidate used by a relocation.
Do not use --strip-unneeded: that would also remove debugging information.
"""
    env = dict(os.environ, LC_ALL='C')
    table = subprocess.check_output([prefix + 'readelf', '-W', '-s', str(binary)],
                                    text=True, env=env)
    (evidence / 'rust-symbols-before.txt').write_text(table)
    names = sorted({parts[7] for line in table.splitlines()
                    if len(parts := line.split()) == 8
                    and parts[0].endswith(':') and parts[0][:-1].isdigit()
                    and parts[4] == 'LOCAL' and parts[6] == 'UND'})
    # One exact name per line; reject names interpreted as comments by objcopy.
    assert all('#' not in name for name in names), 'unsupported symbol spelling'
    candidates = evidence / 'discarded-undefined.txt'
    candidates.write_text(''.join(name + '\n' for name in names))
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    if names:
        output = binary.with_name(binary.name + '.pruned')
        try:
            subprocess.run([prefix + 'objcopy', '--strip-symbols=' + str(candidates),
                            str(binary), str(output)], check=True, env=env)
            output.replace(binary)
        finally:
            output.unlink(missing_ok=True)
    (evidence / 'rust-symbol-pruning.json').write_text(json.dumps({
        'removed_local_undefined': names, 'before_sha256': before,
        'after_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'policy': 'local undefined only; objcopy rejects remaining relocation references',
    }, indent=2) + '\n')


if __name__ == '__main__':
    root = Path(os.environ['NUTTX_STD_SYSROOT'])
    rustc = str(root / 'bin/rustc')
    assert Path(subprocess.check_output([rustc, '--print', 'sysroot'], text=True).strip()) == root
    host = next(line.split(': ', 1)[1] for line in subprocess.check_output(
        [rustc, '-vV'], text=True).splitlines() if line.startswith('host: '))
    args, deferred = arguments(sys.argv[1:])
    if 'NUTTX_STD_GNU_LINKER' in os.environ:
        linker = Path(os.environ['NUTTX_STD_GNU_LINKER'])
        assert linker.is_absolute() and linker.is_file()
        assert linker.name == 'xtensa-esp32s3-elf-ld', 'only the selected Xtensa linker is allowed'
        assert '-flavor' not in args, 'GNU ld must not receive LLD flavor arguments'
        evidence = Path(os.environ['NUTTX_STD_LINK_LOG']).parent
        args += ['-Map=' + str(evidence / 'rust-partial.map'), '--cref']
    else:
        linker = root / 'lib/rustlib' / host / 'bin/rust-lld'
        if '-flavor' not in args:
            args = ['-flavor', 'gnu', *args]
    Path(os.environ['NUTTX_STD_LINK_LOG']).write_text(json.dumps({
        'linker': str(linker), 'original': sys.argv[1:],
        'effective': args, 'deferred_nuttx_libraries': deferred,
    }, indent=2) + '\n')
    status = subprocess.call([str(linker), *args])
    if status == 0 and 'NUTTX_STD_GNU_LINKER' in os.environ:
        binary = Path(args[args.index('-o') + 1])
        shutil.copy2(binary, evidence / 'rust-input-before.elf')
        prefix = str(linker)[:-2]  # Keep the same pinned tool directory/prefix.
        prune_discarded_undefined(binary, prefix, evidence)
        shutil.copy2(binary, evidence / 'rust-input.elf')
        with (evidence / 'rust-relocations.txt').open('w') as stream:
            subprocess.run([prefix + 'readelf', '-W', '-S', '-r', str(binary)],
                           stdout=stream, check=True)
    raise SystemExit(status)
