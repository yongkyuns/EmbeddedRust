#!/usr/bin/env python3
"""Cortex-M33 QEMU qualification only; UART pacing is outside measurements."""
import argparse
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import time
from analyze import matched, thread_metric

POSIX = ['semaphore-hot', 'heap128', 'queue-hot', 'yield-alone', 'semaphore-handoff']

def capture(image, mode, log, seconds):
    master, slave = pty.openpty()
    process = None
    transcript, pending, results = '', '', []
    try:
        process = subprocess.Popen(['qemu-system-arm', '-machine', 'mps2-an521', '-kernel', str(image.resolve()),
            '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none', '-no-reboot'],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave); slave = -1
        def until(done, timeout=90):
            nonlocal transcript, pending
            end = time.monotonic() + timeout
            while not done(pending):
                if time.monotonic() >= end: raise TimeoutError('QEMU console deadline')
                if select.select([master], [], [], 0.1)[0]:
                    data = os.read(master, 65536)
                    if not data: raise RuntimeError('console EOF')
                    text = data.decode(errors='replace').replace('\r', '')
                    transcript += text; pending += text
                    if len(transcript) > 2 * 1024 * 1024: raise RuntimeError('console too large')
                    print(text, end='', flush=True)
                elif process.poll() is not None: raise RuntimeError('QEMU exited')
            text, pending = pending, ''
            return text
        def send(command):
            time.sleep(0.02)
            for byte in (command + '\n').encode():
                os.write(master, bytes([byte])); time.sleep(0.01)
        boot = until(lambda s: 'nsh>' in s)
        if 'NuttShell' not in boot: raise ValueError('not a NuttX boot')
        if mode == 'thread-metric':
            send('tm_bench')
            text = until(lambda s: s.count('Time Period Total:') >= 2 and s.endswith('\n'), 2 * seconds + 30)
            results = thread_metric(text, seconds)
            if not results['valid']: raise ValueError('original counter validation FAILED (retained in log)')
        else:
            cases = [('c-posix', c) for c in POSIX]
            if mode == 'rust':
                cases += [('rust-posix', c) for c in POSIX]
                cases += [(b, c) for b in ['rust-std', 'rust-ao'] for c in ['queue-hot', 'ping-pong']]
            for repeat in range(2):
                for backend, case in cases:
                    command = f'rt_c {case} 200000' if mode == 'c' else f'rt_bench {backend} {case} 200000'
                    send(command)
                    row = matched(until(lambda s: 'nsh>' in s), backend, case, 200000)
                    results.append(dict(repeat=repeat, result=row))
            send('rt_c missing 0' if mode == 'c' else 'rt_bench rust-ao missing 0')
            invalid = until(lambda s: 'nsh>' in s)
            if 'RTBENCH {' in invalid: raise ValueError('invalid configuration reported success')
        print('\nBENCH_HARNESS_QUALIFIED (QEMU, NOT MCU performance)')
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
        if slave != -1: os.close(slave)
        os.close(master)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(transcript)
        log.with_suffix('.json').write_text(json.dumps(dict(runtime_kind='qemu', board='mps2-an521',
            physical_timing_qualified=False, results=results), indent=2) + '\n')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--mode', choices=['c', 'rust', 'thread-metric'], required=True)
    p.add_argument('--log', type=Path, required=True)
    p.add_argument('--window-seconds', type=int, default=30)
    a = p.parse_args()
    capture(a.image, a.mode, a.log, a.window_seconds)
