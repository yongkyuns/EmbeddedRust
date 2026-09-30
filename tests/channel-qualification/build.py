#!/usr/bin/env python3
"""Build controlled final-artifact matrices; never interpret archive bytes as flash."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tomllib
from types import SimpleNamespace

import footprint

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = 'nxrs-channel-qualification'
PROFILE = {'opt_level': 'z', 'lto': False, 'codegen_units': 1, 'panic': 'abort',
           'debug': 1, 'strip': 'none', 'overflow_checks': False,
           'debug_assertions': False, 'worker_stack': 16384, 'main_stack': 65536}


def capture(args, cwd=ROOT, env=None):
    return subprocess.check_output(list(map(str, args)), cwd=cwd, env=env, text=True)


def run(args, log, env=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    log.with_suffix('.command.json').write_text(json.dumps(list(map(str, args))) + '\n')
    with log.open('w') as stream:
        subprocess.run(list(map(str, args)), cwd=ROOT, env=env, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def environment():
    forbidden = ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC', 'CARGO_BUILD_RUSTC',
                 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_TARGET',
                 'NXRS_NUTTX_DIAGNOSTIC_UNWIND']
    if any(os.environ.get(key) for key in forbidden):
        raise ValueError('uncontrolled build override: ' + ', '.join(
            key for key in forbidden if os.environ.get(key)))
    if any(key.startswith(('CARGO_PROFILE_', 'CARGO_TARGET_')) for key in os.environ):
        raise ValueError('uncontrolled Cargo profile/target environment')
    env = dict(os.environ)
    for key, value in [('OPT_LEVEL', 'z'), ('LTO', 'false'), ('CODEGEN_UNITS', '1'),
                       ('PANIC', 'abort'), ('DEBUG', '1'), ('STRIP', 'none'),
                       ('OVERFLOW_CHECKS', 'false'), ('DEBUG_ASSERTIONS', 'false')]:
        env['CARGO_PROFILE_RELEASE_' + key] = value
    env['CARGO_INCREMENTAL'] = '0'
    return env


def combined_hash(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def rt_build_module():
    spec = importlib.util.spec_from_file_location('nxrs_rt_build', ROOT / 'tests/rtos-bench/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(elf, directory, prefix, variant):
    size = capture([prefix + 'size', elf])
    values = size.splitlines()[-1].split()
    if len(values) < 4:
        raise ValueError('unexpected GNU size output')
    text, data, bss = map(int, values[:3])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'size.txt').write_text(size)
    for filename, command in [
        ('sections.txt', [prefix + 'size', '-A', elf]),
        ('layout.txt', [prefix + 'readelf', '-W', '-h', '-l', '-S', elf]),
        ('symbols.txt', [prefix + 'nm', '-C', '-S', '--size-sort', elf]),
        ('symbols-raw.txt', [prefix + 'nm', elf]),
    ]:
        (directory / filename).write_text(capture(command))
    symbols = (directory / 'symbols.txt').read_text()
    raw = (directory / 'symbols-raw.txt').read_text()
    if 'nxrs_allocation_probe' in symbols or 'nxrs_allocation_probe' in raw:
        raise ValueError('allocator instrumentation leaked into size artifact')
    if variant in ('c-minimal', 'cq-core') and ('std::' in symbols or '_ZN3std' in raw):
        raise ValueError('std linked into C/core baseline')
    if variant in ('c-minimal', 'cq-core', 'cq-std', 'cq-thread', 'cq-std-channel'):
        if 'crossbeam_channel::' in symbols or 'crossbeam_channel' in raw:
            raise ValueError('Crossbeam linked into non-Crossbeam baseline')
    elif 'crossbeam_channel::' not in symbols:
        raise ValueError('Crossbeam use not observable in linked symbols')
    if variant == 'c-minimal' and any(marker in raw for marker in ['rust_eh_personality', '_RNv', '_ZN3std']):
        raise ValueError('Rust linked into C baseline')
    return dict(text_bytes=text, data_bytes=data, bss_bytes=bss,
                flash_like_bytes=text + data, static_ram_bytes=data + bss,
                elf_file_bytes=elf.stat().st_size)


def base_identity(scope, target, rustc, cc):
    return dict(scope=scope, target=target, source_commit=capture(['git', 'rev-parse', 'HEAD']).strip(),
                lock_sha256=footprint.sha256(ROOT / 'Cargo.lock'), rustc=rustc, cc=cc,
                profile=PROFILE, kernel_config_sha256='not-applicable-native',
                platform_sha256='not-applicable-native',
                workload_sha256=combined_hash(list((HERE / 'src').glob('*.rs'))),
                std_patch_driver_sha256=combined_hash([
                    ROOT / 'tests/nuttx-std/prepare-std.py', ROOT / 'tests/nuttx-std/link.py',
                    ROOT / 'tools/build-nuttx-std-app.sh']), instrumented=False)


def record(variant, elf, directory, prefix, identity, deployment=None):
    metrics = inspect(elf, directory, prefix, variant)
    artifacts = dict(elf=str(elf.resolve()), sha256=footprint.sha256(elf))
    if deployment and deployment.is_file():
        artifacts['deployment_image'] = str(deployment.resolve())
        artifacts['deployment_sha256'] = footprint.sha256(deployment)
        artifacts['deployment_bytes'] = deployment.stat().st_size
    row = dict(schema=1, variant=variant, identity=identity, metrics=metrics, artifacts=artifacts)
    footprint.validate(row)
    (directory / 'record.json').write_text(json.dumps(row, indent=2) + '\n')
    return row


def native(out, env):
    if platform.system() != 'Linux':
        raise ValueError('initial native ELF matrix requires Linux')
    rustc = capture(['rustc', '+1.90.0', '-vV'])
    target = next(line.split(': ', 1)[1] for line in rustc.splitlines() if line.startswith('host: '))
    identity = base_identity('native-linked-executable-diagnostic', target, rustc,
                             capture(['gcc', '--version']))
    identity['profile'] = dict(PROFILE, c_flags=['-Os', '-fno-lto', '-g1', '-ffunction-sections',
                                               '-fdata-sections', '-Wl,--gc-sections'])
    rows = []
    cdir = out / 'c-minimal'
    cdir.mkdir(parents=True, exist_ok=True)
    celf = cdir / 'c-minimal'
    run(['gcc', *identity['profile']['c_flags'], ROOT / 'tests/rtos-bench/minimal_c.c',
         '-Wl,-Map=' + str(cdir / 'link.map'), '-o', celf], cdir / 'build.log', env)
    run([celf], cdir / 'run.log', env)
    rows.append(record('c-minimal', celf, cdir, '', identity))
    cargo_target = out / 'cargo'
    env = dict(env, CARGO_TARGET_DIR=str(cargo_target))
    for name in footprint.VARIANTS[1:]:
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        run(['cargo', '+1.90.0', 'rustc', '--locked', '--release', '-p', PACKAGE,
             '--bin', name, '--no-default-features', '--', '-C',
             'link-arg=-Wl,-Map=' + str(directory / 'link.map')], directory / 'build.log', env)
        elf = directory / name
        shutil.copy2(cargo_target / 'release' / name, elf)
        run(['timeout', '20', elf], directory / 'run.log', env)
        rows.append(record(name, elf, directory, '', identity))
    return rows


def firmware(out, env, selected):
    profile_path = ROOT / f'platform/nuttx/platforms/{selected}.toml'
    profile = tomllib.loads(profile_path.read_text())
    if profile['target'] != 'thumbv8m.main-nuttx-eabi':
        raise ValueError('initial matched C firmware matrix supports ARM profiles only')
    rt = rt_build_module()
    common = None
    rows = []
    # Build std first so the existing C builder can use its EXACT resolved kernel settings.
    order = ['cq-std', *[name for name in footprint.VARIANTS[1:] if name != 'cq-std']]
    for name in order:
        directory = out / name
        run(['bash', ROOT / 'tools/build-nuttx-std-app.sh', '--app-manifest', HERE / 'Cargo.toml',
             '--app-package', PACKAGE, '--bin', name, '--command', 'cq_probe', '--priority', '100',
             '--stack-size', '65536', '--platform', selected, '--abi-profile', 'minimal',
             '--out', directory], out / (name + '-build.log'), env)
        proof = json.loads((directory / 'std-source.json').read_text())
        if proof.get('selected_source_matches') is not True:
            raise ValueError('target std source was not qualified')
        rustc = capture([proof['rustc'], '-vV'])
        identity = base_identity('whole-linked-firmware', profile['target'], rustc,
                                 capture([profile['crossdev'] + 'gcc', '--version']))
        identity['kernel_config_sha256'] = rt.config_identity(directory / 'resolved.config')
        identity['platform_sha256'] = footprint.sha256(profile_path)
        if common is None:
            common = identity
        elif common != identity:
            raise ValueError('firmware matrix identity changed during build')
        elf = directory / 'nuttx/nuttx'
        rows.append(record(name, elf, directory, profile['crossdev'], identity,
                           directory / 'nuttx' / profile['image']))
    directory = out / 'c-minimal'
    directory.mkdir()
    args = SimpleNamespace(platform=selected, suite='footprint', case='basic', profile='matched',
                           window_seconds=1, matched_config=out / 'cq-std/resolved.config')
    rt.c_firmware(args, directory)
    identity = dict(common, kernel_config_sha256=rt.config_identity(directory / 'resolved.config'))
    rows.append(record('c-minimal', directory / 'nuttx/nuttx', directory, profile['crossdev'],
                       identity, directory / 'nuttx' / profile['image']))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['native', 'firmware'])
    parser.add_argument('--platform', default='mps2-an521-mock', choices=['mps2-an521-mock', 'pico2-mock'])
    args = parser.parse_args()
    env = environment()
    if capture(['git', 'status', '--porcelain', '--untracked-files=no']).strip():
        raise ValueError('tracked source modifications: commit before footprint qualification')
    out = ROOT / 'target/channel-qualification' / (args.mode if args.mode == 'native' else args.platform)
    if out.exists():
        raise ValueError('output already exists; archive or remove it explicitly: ' + str(out))
    out.mkdir(parents=True)
    (out / 'dependency-features.txt').write_text(capture(
        ['cargo', '+1.90.0', 'tree', '--locked', '-p', PACKAGE, '--edges', 'normal,build,features']))
    rows = native(out, env) if args.mode == 'native' else firmware(out, env, args.platform)
    result = footprint.compare(rows)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'summary.md').write_text(footprint.markdown(result))
    print('CHANNEL_FOOTPRINT=' + str(out / 'summary.json'))


if __name__ == '__main__':
    main()
