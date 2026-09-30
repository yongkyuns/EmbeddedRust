#!/usr/bin/env python3
"""Fresh-boot fault isolation. These are QEMU correctness runs, not MCU timings."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import time

from analyze import matched

BACKENDS = ('rust-std', 'rust-ao')
POSIX = ('semaphore-hot', 'heap128', 'queue-hot', 'yield-alone')
SCENARIOS = (('fresh-short', 2000, False), ('fresh-long', 200000, False),
             ('after-primitives', 200000, True))
FAULT = re.compile(r'qemu: fatal:|Lockup:|arm_hardfault:|arm_usagefault:|arm_busfault:')
FAILURE = re.compile(r'RTBENCH FAIL|TM_PORT FAIL|panicked at|Assertion failed')


def commands_for(backend, iterations, prior_sequence=False):
    """Count and prior history are independent axes. Preserve the exact prelude."""
    if backend not in BACKENDS or iterations not in (2000, 200000):
        raise ValueError('unsupported isolation case')
    commands = []
    if prior_sequence:
        commands = [(b, c, 200000) for b in ('c-posix', 'rust-posix') for c in POSIX]
        commands.append(('rust-std', 'queue-hot', 200000))
    commands.append((backend, 'ping-pong', iterations))
    return commands


def plans(repeats):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError('repeats must be 1..10')
    result = []
    for repeat in range(repeats):
        # Counterbalance backend order; every entry still starts a new emulator.
        for backend in BACKENDS if repeat % 2 == 0 else BACKENDS[::-1]:
            for scenario, iterations, prior in SCENARIOS:
                result.append(dict(name=f'r{repeat}-{backend}-{scenario}', backend=backend,
                                   iterations=iterations, prior_sequence=prior, repeat=repeat))
    return result


def run_boot_commands(image, directory, plan, expected, *, qemu='qemu-system-arm', timeout=120, pacing=0.01):
    """One owned QEMU child, one boot, complete result/return-to-shell validation."""
    directory.mkdir(parents=True, exist_ok=True)
    record = dict(schema=1, **plan, runtime_kind='qemu', board='mps2-an521',
                  physical_timing_qualified=False, qualified=False, target_started=False,
                  target_completed=False, expected_commands=[list(c) for c in expected],
                  results=[], failure_stage='boot', error=None)
    transcript = ''
    master = slave = None
    process = None
    try:
        record['image_sha256'] = hashlib.sha256(image.read_bytes()).hexdigest()
        master, slave = pty.openpty()
        command = [qemu, '-machine', 'mps2-an521', '-kernel', str(image.resolve()),
                   '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
                   '-nic', 'none', '-no-reboot']
        record['emulator_command'] = command
        process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                   start_new_session=True)
        record['emulator_pid'] = process.pid
        os.close(slave)
        slave = None
        deadline = time.monotonic() + timeout

        def prompt():
            nonlocal transcript
            pending = ''
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('whole-boot console deadline')
                if select.select([master], [], [], min(0.1, max(0, deadline - time.monotonic())))[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            raise RuntimeError('console closed before complete result/prompt') from error
                        raise
                    if not data:
                        raise RuntimeError('console EOF before complete result/prompt')
                    text = data.decode(errors='replace').replace('\r', '')
                    transcript += text
                    pending += text
                    if len(transcript) > 2 * 1024 * 1024:
                        raise RuntimeError('console limit')
                    if FAULT.search(pending):
                        raise RuntimeError('guest fault/lockup')
                    if FAILURE.search(pending):
                        raise RuntimeError('guest reported failure')
                    if 'nsh>' in pending:
                        return pending
                elif process.poll() is not None:
                    raise RuntimeError('QEMU exited before complete result/prompt')

        if 'NuttShell' not in prompt():
            raise ValueError('not a NuttX boot')
        for index, (backend, case, count) in enumerate(expected):
            record['failure_stage'] = f'command-{index}'
            record['active_command'] = [backend, case, count]
            record['target_started'] = index == len(expected) - 1
            for byte in f'rt_bench {backend} {case} {count}\n'.encode():
                if time.monotonic() >= deadline:
                    raise TimeoutError('whole-boot transmit deadline')
                os.write(master, bytes([byte]))
                time.sleep(pacing)
            row = matched(prompt(), backend, case, count)
            record['results'].append(row)
        record.update(qualified=True, target_completed=True, failure_stage=None)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record['error'] = f'{type(error).__name__}: {error}'
    finally:
        if process is not None:
            record['emulator_returncode_before_cleanup'] = process.poll()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        for fd in (slave, master):
            if fd is not None:
                os.close(fd)
        (directory / 'console.log').write_text(transcript)
        (directory / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def run_boot(image, directory, plan, *, qemu='qemu-system-arm', timeout=120, pacing=0.01):
    expected = commands_for(plan['backend'], plan['iterations'], plan['prior_sequence'])
    return run_boot_commands(image, directory, plan, expected, qemu=qemu, timeout=timeout, pacing=pacing)


def fresh_matrix_plans(repeats=2):
    """One benchmark command per emulator boot; no Rust-runtime restart history."""
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError('repeats must be 1..10')
    cases = []
    for backend in ('c-posix', 'rust-posix'):
        for case in (*POSIX, 'semaphore-handoff'):
            cases.append((backend, case))
    for backend in BACKENDS:
        for case in ('queue-hot', 'ping-pong'):
            cases.append((backend, case))
    result = []
    for repeat in range(repeats):
        ordered = cases if repeat % 2 == 0 else list(reversed(cases))
        for backend, case in ordered:
            result.append(dict(
                name=f'fresh-r{repeat}-{backend}-{case}',
                backend=backend,
                case=case,
                iterations=200000,
                repeat=repeat,
            ))
    return result


def run_fresh_matrix(image, output, repeats=2):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for plan in fresh_matrix_plans(repeats):
        command = [(plan['backend'], plan['case'], plan['iterations'])]
        result = run_boot_commands(image, output / plan['name'], plan, command)
        results.append(result)
        print('FRESH ' + json.dumps({
            'name': result['name'],
            'qualified': result['qualified'],
            'target_completed': result['target_completed'],
            'error': result['error'],
        }), flush=True)
    summary = dict(
        schema=1,
        runtime_kind='qemu',
        physical_timing_qualified=False,
        one_command_per_boot=True,
        planned=len(results),
        completed=len(results),
        qualified=all(r['qualified'] for r in results),
        results=results,
    )
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def history_prefix_plans(backend='rust-std'):
    """Locate the first prior invocation after which a clean long ping-pong fails."""
    if backend not in BACKENDS:
        raise ValueError('unsupported history-scan backend')
    prelude = [(b, c, 200000) for b in ('c-posix', 'rust-posix') for c in POSIX]
    prelude.append(('rust-std', 'queue-hot', 200000))
    return [
        dict(name=f'history-{backend}-prefix-{prefix}', backend=backend,
             iterations=200000, repeat=0, history_prefix=prefix,
             explicit_commands=prelude[:prefix] + [(backend, 'ping-pong', 200000)])
        for prefix in range(len(prelude) + 1)
    ]


def run_history_scan(image, output, backend='rust-std'):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    first_failed_prefix = None
    for plan in history_prefix_plans(backend):
        explicit = plan.pop('explicit_commands')
        # Reuse run_boot's strict executor by temporarily expressing the exact
        # prefix through a plan-local command list.
        result = run_boot_commands(image, output / plan['name'], plan, explicit)
        results.append(result)
        if not result['qualified'] and first_failed_prefix is None:
            first_failed_prefix = plan['history_prefix']
        print('HISTORY ' + json.dumps({
            'name': result['name'], 'qualified': result['qualified'],
            'history_prefix': result['history_prefix'],
            'target_started': result['target_started'],
            'target_completed': result['target_completed'],
            'error': result['error'],
        }), flush=True)
    prelude = [(b, c, 200000) for b in ('c-posix', 'rust-posix') for c in POSIX]
    prelude.append(('rust-std', 'queue-hot', 200000))
    first_added_command = (
        list(prelude[first_failed_prefix - 1])
        if first_failed_prefix is not None and first_failed_prefix > 0
        else None
    )
    summary = dict(
        schema=1, runtime_kind='qemu', physical_timing_qualified=False,
        backend=backend, planned=len(results), completed=len(results),
        first_failed_prefix=first_failed_prefix,
        first_added_command=first_added_command,
        results=results,
    )
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def run_matrix(image, output, repeats=2):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for plan in plans(repeats):
        result = run_boot(image, output / plan['name'], plan)
        results.append(result)
        print('ISOLATION ' + json.dumps({key: result[key] for key in
              ('name', 'qualified', 'target_started', 'target_completed', 'error')}), flush=True)
        # A failed prior boot must not suppress any other backend or scenario.
    summary = dict(schema=1, runtime_kind='qemu', physical_timing_qualified=False,
                   qualified=all(r['qualified'] for r in results),
                   planned=len(plans(repeats)), completed=len(results), results=results)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--history-scan', choices=BACKENDS)
    parser.add_argument('--fresh-matrix', action='store_true')
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error('image must be an existing firmware ELF')
    try:
        plans(args.repeats)
    except ValueError as error:
        parser.error(str(error))
    if args.fresh_matrix:
        summary = run_fresh_matrix(args.image, args.out, args.repeats)
        raise SystemExit(0 if summary['qualified'] else 1)
    if args.history_scan:
        summary = run_history_scan(args.image, args.out, args.history_scan)
        # A history scan is diagnostic: success means the scan completed and
        # retained every prefix result, not that no prefix reproduced the fault.
        raise SystemExit(0 if summary['completed'] == summary['planned'] else 1)
    raise SystemExit(0 if run_matrix(args.image, args.out, args.repeats)['qualified'] else 1)
