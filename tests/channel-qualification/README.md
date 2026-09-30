# Channel and linked-footprint qualification

This is an isolated fixture, not `nxrs-ao` or a production HAL migration.
Architecture discussion: PR #7. Crossbeam channel 0.5.17 and utils 0.8.23 are
locked; production service dependencies remain unchanged. The exact upstream
checksums are in the root lockfile. The fixture is not a default workspace member.

## Run the first qualification slice

```sh
python3 -m unittest discover -s tests/channel-qualification -p test_footprint.py -v
cargo +1.90.0 test --locked -p nxrs-channel-qualification --lib
cargo +1.90.0 build --locked --release -p nxrs-channel-qualification --features memory-probe --bin cq-memory
for mode in std crossbeam select; do
  target/release/cq-memory "$mode"
done
python3 tests/channel-qualification/build.py native
```

The native footprint command requires Linux ELF/binutils and a clean tracked
checkout. It refuses an existing output directory instead of mixing old/new
artifacts; archive or explicitly remove `target/channel-qualification/native`
before repeating. The firmware driver has the same restriction.

Each memory case runs as a fresh process with a fresh receiving thread. It reuses
`nxrs-allocation-probe`, measuring construction, first blocking timeout, repeated
timeouts, ready-path transfers, queue saturation/recovery, channel drop, and the
complete thread lifetime separately. Reports are emitted after all snapshots.
Steady timeout/ready/overload windows fail on any allocator calls. No arbitrary
warm-up hides the first blocking case. These are Rust global-allocator measurements,
not OS heap or task-stack measurements and NOT timing benchmarks.

The first functional tests cover separate capacities, rejected important payloads,
stop preference at capacity, each source reaching the same selector, required
closure, explicit HAL failure while other senders live, due-work checks, synthetic
cancellation without draining a full data queue, and owned-payload cleanup.

## Binary footprint ladder

| Binary | What it isolates |
| --- | --- |
| `c-minimal` | Existing minimal C entry, generated with matched settings |
| `cq-core` | `no_std` C-ABI Rust entry; absence of std symbols is checked |
| `cq-std` | Empty ordinary Rust `main` and std entry/runtime linkage |
| `cq-thread` | One thread/join and the shared checksum computation |
| `cq-std-channel` | Standard bounded-channel workload |
| `cq-crossbeam` | Same source macro/payload/count/capacity, Crossbeam substituted |
| `cq-select` | Additional dedicated important/stop queues and biased selection |
| `cq-coexist` | Standard and Crossbeam implementations both used |

All footprint binaries are uninstrumented. The allocator dependency is optional,
only enabled in `cq-memory`; symbol checks reject instrumentation in size images.
The baseline crate declares Crossbeam but does not reference it from the core/std/
thread/std-channel binaries. Symbol checks verify it was not linked into those
baselines. This distinguishes dependency resolution from actual linked cost.

`cq-std-channel` versus `cq-crossbeam` is the equivalent-workload substitution
comparison. `cq-select` adds queue/selection semantics and is deliberately labeled
as an incremental feature workload, not the same benchmark. `cq-coexist` executes
two workloads and exposes migration coexistence cost; its extra bytes are not
claimed to be entirely duplicate runtime. No framework-overhead figure exists yet.

The C/core/std minimal delta includes entry, panic and link-layout differences.
It is not a universal byte cost of Rust or std. Host binaries retain native CRT
and dynamic library dependencies; they are diagnostics, not MCU flash estimates.

## Matched firmware builds

```sh
# Install the same ARM/NuttX prerequisites used by the existing RTOS benchmark CI.
git submodule update --init
python3 tests/channel-qualification/build.py firmware --platform mps2-an521-mock
# Actual Pico 2 target layout can be built separately; this is not a board run.
python3 tests/channel-qualification/build.py firmware --platform pico2-mock
```

The driver reuses `tools/build-nuttx-std-app.sh` and the minimal C build path in
`tests/rtos-bench/build.py`. It builds std first and uses that resolved kernel
configuration for C. Only the existing pair of application-selection Kconfig
symbols may differ. Every Rust variant uses the same command name, main stack,
platform, compiler and release settings. The core variant is compiled by the
same pipeline but must have no linked std symbols. Building std dependencies
is not evidence they entered the final image.

Reports include `.text`-like code/read-only totals, data, BSS, flash-like and static
RAM proxies, full ELF file length, delta bytes/percent, raw section/segment and
symbol dumps, native link maps, deployment bytes where present, lock/feature
identity, source/config/compiler fingerprints and artifact hashes. The final
NuttX ELF is measured, not the relocatable Rust object or `.rlib` archive.
Full ELF length includes debug/symbol metadata; `text+data` is only a flash proxy.
Task stacks, heap peaks and reserved pools remain separate resource accounting.

`footprint.py` rejects missing/duplicate rows, incompatible build identities,
negative/bool metrics, inconsistent derived totals and changed artifacts. It
cannot turn unverified metadata into proof; build provenance and source review
remain part of qualification. Size profiling uses opt-level z, one codegen unit,
no LTO, panic abort and retained symbols/debug metadata for attribution. It is
an explicit comparison profile, not a claim of the smallest achievable firmware.

## CI and status boundaries

The trusted workflow runs host functional/memory/size checks, then matched ARM
firmware builds with the existing isolated Linux runner labels. It uploads even
partial artifacts after a failure; incomplete matrices cannot generate a passing
comparison. No workflow permission or branch protection is relaxed.

Pending beyond this first slice: concurrent blocking-wakeup allocation windows,
measured latency distributions without allocator hooks, long-run deadline/fairness
qualification, real protocol normalization, real blocked-UART cancellation,
partial-start rollback, session restart/late-event handling, target OS-heap/stack
measurements, firmware runtime tests and browser execution. Synthetic provider
cancellation is not hardware-driver cancellation evidence. A build/ABI pass is
not a timing or physical-device pass. No size or allocation result is claimed
until an actual run produces its source-bound artifact.
