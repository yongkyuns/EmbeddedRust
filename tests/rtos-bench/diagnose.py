#!/usr/bin/env python3
"""Bounded, read-only GDB fault capture. Diagnostic execution is not benchmark data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import tempfile
import time

from isolate import commands_for


def diagnose(image, out, sequence, backend='rust-std', prior_sequence=False):
    out.mkdir(parents=True, exist_ok=True)
    selected = commands_for(backend, sequence, prior_sequence)
    (out / 'scenario.json').write_text(json.dumps(dict(
        backend=backend, iterations=sequence, prior_sequence=prior_sequence,
        commands=selected, image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        diagnostic_only=True, physical_timing_qualified=False), indent=2) + '\n')
    qemu = gdb = None
    master, slave = pty.openpty()
    console = ''
    with tempfile.TemporaryDirectory(prefix='rtbench-gdb-') as temporary:
        sock = Path(temporary) / 'gdb'
        commands = out / 'fault.gdb'
        commands.write_text('\n'.join([
            'set pagination off', 'set confirm off', 'set breakpoint pending on',
            'set print pretty on', f'file {image.resolve()}', f'target remote {sock}',
            'break arm_hardfault', 'break arm_usagefault', 'break arm_busfault',
            'break arm_memfault', 'break _assert', 'continue',
            'echo \\nDIAGNOSTIC_STOP_NOT_NECESSARILY_FAULT\\n', 'info registers', 'bt 24',
            'x/48wx $sp', 'x/24wx $r1', 'x/8wx 0xe000ed20',
            'p/x g_running_tasks', 'p/x *g_running_tasks[0]', 'quit', '',
        ]))
        try:
            qemu = subprocess.Popen([
                'qemu-system-arm', '-machine', 'mps2-an521', '-kernel', str(image.resolve()),
                '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
                '-no-reboot', '-S', '-chardev', f'socket,path={sock},server=on,wait=off,id=gdb0',
                '-gdb', 'chardev:gdb0', '-d', 'guest_errors', '-D', str(out / 'qemu-errors.log'),
            ], stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave); slave = -1
            until = time.monotonic() + 5
            while not sock.exists():
                if time.monotonic() > until: raise TimeoutError('GDB socket startup')
                time.sleep(0.02)
            with (out / 'gdb.log').open('w') as log:
                gdb = subprocess.Popen(['gdb-multiarch', '-q', '-batch', '-x', str(commands)],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                pending = ''
                cases = [f'rt_bench {b} {case} {count}' for b, case, count in selected]
                end = time.monotonic() + 90
                while time.monotonic() < end and gdb.poll() is None and qemu.poll() is None:
                    if select.select([master], [], [], 0.1)[0]:
                        try: data = os.read(master, 65536)
                        except OSError: break
                        if not data: break
                        text = data.decode(errors='replace').replace('\r', '')
                        console += text; pending += text
                        if len(console) > 1024 * 1024: raise RuntimeError('console limit')
                        if 'nsh>' in pending:
                            pending = ''
                            if not cases: break
                            for byte in (cases.pop(0) + '\n').encode():
                                os.write(master, bytes([byte])); time.sleep(0.01)
                if gdb.poll() is None:
                    # Interrupt GDB, not the guest's memory; collect the current stop.
                    gdb.send_signal(signal.SIGINT)
                    try: gdb.wait(timeout=5)
                    except subprocess.TimeoutExpired: pass
        finally:
            for process in [gdb, qemu]:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
            if slave != -1: os.close(slave)
            os.close(master)
            (out / 'console.log').write_text(console)
    print('Diagnostic logs retained; no timing or fault-resolution claim.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--iterations', choices=[2000, 200000], type=int, default=2000)
    parser.add_argument('--backend', choices=['rust-std', 'rust-ao'], default='rust-std')
    parser.add_argument('--prior-sequence', action='store_true')
    args = parser.parse_args()
    diagnose(args.image, args.out, args.iterations, args.backend, args.prior_sequence)
