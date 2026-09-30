#!/usr/bin/env python3
"""Run one Cargo-selected std app on Cortex-M33 NuttX in QEMU.

A bounded PTY transcript and external deadline are deliberately independent of
in-app success markers and cooperative shutdown. Hardware timing is not inferred.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time

from test_std_apps import validate_std, validate_stress


def run(qemu: Path, image: Path, app: str, log: Path) -> None:
    master, slave = pty.openpty()
    process = None
    transcript: list[str] = []
    pending = ""
    total = 0
    try:
        process = subprocess.Popen(
            [str(qemu.resolve()), "-machine", "mps2-an521", "-kernel", str(image.resolve()),
             "-display", "none", "-serial", "stdio", "-monitor", "none", "-nic", "none", "-no-reboot"],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        os.close(slave)
        slave = -1

        def until(marker: str, seconds: float = 90) -> str:
            nonlocal pending, total
            end_time = time.monotonic() + seconds
            while marker not in pending:
                if time.monotonic() >= end_time:
                    raise TimeoutError(f"missing {marker!r}, QEMU status={process.poll()}")
                if select.select([master], [], [], 0.1)[0]:
                    data = os.read(master, 65536)
                    if not data:
                        raise RuntimeError("console EOF")
                    total += len(data)
                    if total > 2 * 1024 * 1024:
                        raise RuntimeError("transcript exceeded 2 MiB")
                    text = data.decode("utf-8", errors="replace").replace("\r", "")
                    transcript.append(text)
                    pending += text
                    sys.stdout.write(text)
                    sys.stdout.flush()
                elif process.poll() is not None:
                    raise RuntimeError(f"QEMU exited {process.returncode}")
            end = pending.index(marker) + len(marker)
            answer, pending = pending[:end], pending[end:]
            return answer

        def command(text: str) -> str:
            # Same MPS2 UART pacing as the existing event-demo qualification;
            # this paces test input, never the app's measured event traffic.
            time.sleep(0.02)
            for value in (text + "\n").encode():
                os.write(master, bytes((value,)))
                time.sleep(0.01)
            return until("nsh>")

        assert "NuttShell" in until("nsh>"), "not a NuttX boot"
        nsh_name = app.replace("-", "_")
        # Invoke twice in one boot to exercise TLS/thread teardown and restart.
        for _ in range(2):
            output = command(nsh_name)
            (validate_std if app == "std-demo" else validate_stress)(output)
        invalid = command(nsh_name + (" --case missing" if app == "std-demo" else " --capacity 0"))
        prefix = "STD_DEMO" if app == "std-demo" else "AO_STRESS"
        assert prefix + " FAIL" in invalid, invalid
        assert prefix + " PASS" not in invalid, invalid
        print(f"\nNUTTX_STD_APP PASS app={app} machine=mps2-an521 restarts=2")
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        if slave != -1:
            os.close(slave)
        os.close(master)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(transcript), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--app", choices=("std-demo", "ao-stress"), required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    run(args.qemu, args.image, args.app, args.log)


if __name__ == "__main__":
    main()
