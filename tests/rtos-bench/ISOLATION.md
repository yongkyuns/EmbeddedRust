# Threaded runtime fault isolation

Run after building the existing benchmark firmware:

```sh
python3 tests/rtos-bench/isolate.py --image PATH_TO_NUTTX_ELF --out target/bench-logs/isolation --repeats 2
```

Every matrix entry starts a new MPS2/QEMU process with the identical ELF:

| Scenario | Prior commands in that boot | Target iterations |
| --- | --- | --- |
| fresh-short | None | 2,000 |
| fresh-long | None | 200,000 |
| after-primitives | Four C/POSIX cases, four Rust/POSIX cases, raw std queue-hot; each 200,000 | 200,000 |

Both raw `rust-std` and the existing `rust-ao` implementation run in all three
scenarios. Two rounds reverse the backend order and produce twelve independent
boots. A fault in raw std cannot prevent an AO boot. A fault in the prelude is
recorded as a prelude failure, not a fault in an unexecuted target. Missing or
truncated results, changed iteration counts, explicit failure messages, and
return-to-shell timeouts all fail qualification. Partial transcripts and results
remain in each case directory; summary.json reports every planned boot and the
script exits nonzero if any case failed. The original same-boot capture is retained
as an additional gate, not replaced by a shorter passing workload.

The independent C Thread-Metric adapter calls NuttX's void sched_lock/sched_unlock
APIs without trying to compare a nonexistent return value. It still gates startup
until all test resources exist and preserves the upstream counter checks.

The GDB helper now separates --iterations, --backend and --prior-sequence. A
200,000-iteration request no longer implicitly executes earlier applications.
It reuses the same command planner and records the image hash and exact scenario.
A debugger stop caused by the harness's SIGINT is not represented as a CPU fault.
Successful diagnostic log collection is not successful benchmark execution.

These runs qualify runtime behavior only. They do not establish physical MCU
latency, speedups, hard deadlines, or a cause of the fault. In particular, the
upstream non-SMP task-exit issue is only a hypothesis until this failure is actually
localized. No speculative kernel patch or production transport change is applied.
The separate Thread-Metric CI windows remain one-second smoke tests; comparison
with the report requires the documented thirty-second windows and physical board.
