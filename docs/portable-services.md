# Portable service composition

## Scope and status

This is an additive executable architecture slice. It does not replace the
previous diagnostic application or silently adapt its Linux/NuttX global HAL.
There is no Zephyr migration in this change.

The current portable application and service code is `no_std`, allocation-free
and forbids unsafe code. The simulator supplies deterministic devices. The same
Rust scenario registry executes natively and as WASM in Node/Chromium. Hardware,
RTOS scheduling, DMA, physical images and actual network delivery still require
adapter and hardware qualification.

The firmware model is one selected app per production MCU image. In this slice,
Recorder and Monitor are workflows inside `app/nxrs`, not separate runtime
apps. `CameraProduct` is the existing composition type; its name and source path
remain unchanged. The target app interface is a normal Cargo binary with its own
handwritten `src/main.rs` and `fn main()`, not a library hosted by a platform
launcher. Main constructs services from configured HAL resources and starts
execution through ordinary Rust calls. An optional library can support tests but
is not required. See the [architecture review and roadmap](architecture-and-roadmap.md)
for the proposed entry, runtime, build-selection and configuration work. None is
implemented by this documentation update.

## Dependency direction

The current production direction is capability-first:

```text
nxrs-applications -> nxrs-services
                     -> nxrs-camera / nxrs-storage / nxrs-transport
                          -> provider-independent api contract
                          -> one build-selected provider

service/navigation   -> nxrs-imu / nxrs-gnss
                          -> provider-independent api contract
                          -> one build-selected provider
```

Applications and services depend on capability facades/contracts when that is
the natural ownership boundary. Neither may depend on concrete native/mock/NuttX
provider crates. Provider packages are capability-scoped optional dependencies
selected by the build on the corresponding facade.

For the native nxrs profile, main acquires camera/storage/transport through
their capability facades and transfers ownership into the existing generic
services. For the event demo, IMU/GNSS services acquire their resources
internally from `nxrs-imu` and `nxrs-gnss`. No HAL facade constructs
services or owns application lifecycle, and there is no global HAL package.

Selected images exclude unselected HAL provider implementations and their
exclusive Rust/C driver code; linker dead-code elimination is not the provider
selection mechanism.

`tests/portable` is the shared scenario runner, using devices from `hal/mock`.
Mock storage and transport use host vectors with configured maximum record/packet
counts. Device scripts and test oracle allocations belong only to the test
harness, not production services.

## App workflows request capabilities, not platforms

Recorder composes `Frames + Recordings`. Monitor composes `Frames + Telemetry`.
These workflows operate through the traits and can be tested separately or
wired together inside one app. They cannot start/stop the camera through `Frames`.

`CameraProduct` is one ordinary explicit constructor and tick function, not a
registry or mandatory framework. One camera service is shared by both workflows,
while the storage and transport services own their respective HAL adapters.
Another app configuration may omit Monitor or substitute a frame provider.
A different `app/<name>` composes reusable services into a separate firmware
image, never a second app running alongside this one. No product package or
global service/app registry is required.

The current service-level composition API looks like:

```rust,ignore
// Concrete resources come through capability-local HAL facades.
let mut camera = CameraService::<_, 65536, 2, _>::with_buffers(
    platform_camera, history_buffers, staging_buffer,
)?;
let mut recordings = RecordingService::new(platform_storage);
let mut telemetry = TelemetryService::new(platform_transport);
let mut recorder = Recorder::default();
let mut monitor = Monitor::default();

let actual = camera.start(requested)?;
recorder.start(&camera)?;
monitor.start(&camera)?;

// Cooperative callers may still use a simple step. The native active owner
// schedules camera polling independently from local consumer retries.
let capture_result = camera.poll(clock.now_ms());
let recording_result = recorder.step(&camera, &mut recordings);
let monitor_result = monitor.step(&camera, &mut telemetry);
// Handle all three results; one error must not skip an independent workflow.
```

This construction belongs in the selected app's main or private modules in the
target design. The variable names above do not imply an external app launcher.
Ordinary checked-in Rust may supply the capability-local HAL entry; generation is
optional. Settings must not duplicate service wiring in a second language or
move it out of handwritten app code.

The actual negotiated camera format is exposed; unsupported/invalid formats
are rejected rather than reported as successful configurations. This is a
single-source stream per Frames port. Cursors are sequence positions, not
handles: reconnecting a consumer workflow to a different logical stream requires
stopping and starting that consumer. A stopped/restarted camera retains its
sequence counter.

## Ownership, buffers and backpressure

CameraService owns one device, a fixed history, and one private staging buffer.
Payload capacity is `(history + 1) * frame_capacity`, plus metadata. No frame
allocation or deep cloning occurs in the portable path. Failed/pending reads
may overwrite staging but cannot corrupt published data. Actual byte lengths,
negotiated format and monotonic timestamps are checked before publication.

A returned frame borrows its service, so Rust prevents capture/teardown while
that view is still in use. Frames do not escape into unbounded application
queues. This is NOT a general DMA zero-copy lease pool. Large pools need static
or otherwise explicitly budgeted placement, not an oversized thread stack.

Each consumer workflow has its own cursor. A full history overwrites the oldest
frame; slow readers report exact sequence gaps, while a fast peer keeps progressing.
Each consumer processes at most one frame per step. Failed sink acceptance leaves
its cursor unchanged. A retry that outlives retained history sees a gap.

Storage and transport adapters must honor atomic local acceptance: Err accepts
nothing. Do not wrap partial writes with this interface without buffering or
commit semantics. Transport success is local acceptance, not a remote delivery
or exactly-once networking guarantee.

The native recording adapter now implements its cross-thread boundary with a
fixed startup-allocated pool. Queue capacity is reserved before the borrowed
frame is copied; a full queue therefore returns Busy without allocating/copying
a payload. Each accepted record owns one preallocated buffer until the writer
completes or discards it after a sticky error, then that buffer returns to the
pool. This is specific to the recording path and does not introduce a generic
lease pool into portable services.

Slow blocking HAL calls must not run unbounded on the shared owner; use a
bounded worker/timeout adapter.

## Lifecycle

Stopping a workflow does not imply device stop. Recorder first becomes Stopping,
accepts no new frames, and flushes previously accepted records. It does not drain
unread history. Failed flush remains retryable. Monitor stops independently.
The app's coordinated shutdown stops its workflows and services; no other app
remains running on the MCU.

Only the app's composition owner stops the camera. Failed device cleanup remains
StopPending: publication is hidden, new capture/start is rejected, and the
owner retains the device for retry. Invalid format negotiation also rolls back
through that cleanup path. App shutdown attempts all cleanup operations,
not just those before the first error. Callers must complete explicit shutdown;
this slice does not claim reliable hardware cleanup from an infallible Drop.
For native recording, successful flush is the app-visible commit guarantee;
`FileRecorder::finish()` is the explicit blocking worker-join operation, while
Drop only closes submission and detaches.

## Execution adapters

The portable code does not impose threads or async. The example owner can run
on a native/RTOS thread, and a browser can drive the same step functions from
callbacks. The native harness exercises bounded command/reply channels,
shutdown acknowledgement and worker joining. It does not implement isolated
processes or independently scheduled per-workflow/service workers. Future
message passing connects execution owners within the selected app, not apps to
one another. One app does not require all its services to share one thread.

The target main explicitly starts the loops/threads it needs. Prefer ordinary
std threads and bounded channels on NuttX/native and the selected pthread-enabled
Emscripten browser profile. The separate
[browser thread probe](https://github.com/yongkyuns/nxrs/actions/runs/36274987242)
passed in actual Chrome and Safari at `7511b1c`; the roadmap records its exact
scope. This does not migrate the current production services or qualify browser I/O.
No custom thread API, mandatory cooperative executor, generic actor framework,
universal service trait or prescribed runtime package split is needed.

Browser HAL callbacks must run on a responsive context and deliver bounded
completions to the waiting Rust owner. Do not expect a callback queued on a
worker to execute while that worker is stuck inside a synchronous Rust loop.
Never block the browser UI thread waiting for a worker that needs UI proxying.
Keep such platform-specific I/O handling inside HAL/target support. The existing
threadless WASM mock tests remain useful; they are not the chosen threaded profile.

HAL poll functions must return promptly (Pending when no data is ready).
`Camera::next_poll_at_ms()` lets a timer-driven provider advertise the earliest
owner-clock time at which another poll may make useful progress. The native
replay provider uses this to eliminate blanket 1 ms polling. None means no
time-based retry is advertised; a future interrupt/callback-driven provider must
supply an actual readiness wakeup rather than forcing a fake periodic timer.

Existing blocking drivers need a platform-specific worker or bounded timeout
adapter; this is not solved by putting `async` on a blocking function. Device
completion and wakeup logic remain behind the HAL, and clocks are injected in
a single monotonic domain. Browser mocks exercise no actual browser camera.

The simpler design still requires explicit queue limits, overload behavior,
readiness, shutdown and ownership across threads. Small messages can be copied;
large cross-thread payloads need owned buffers. Native recording now demonstrates
the intended narrow pattern: preallocate the selected path's buffers, reserve
capacity before copying, transfer one buffer to the worker, and recycle it on
completion. A generic lease pool, request-ID protocol or subscription system is
not required unless another concrete use needs it.

## Running and CI

The root toolchain is pinned to Rust 1.90.0. Current portable commands are:

```sh
cargo +1.90.0 test --locked -p nxrs-simulator
cargo +1.90.0 run --locked -p nxrs-simulator
rustup target add --toolchain 1.90.0 thumbv6m-none-eabi wasm32-unknown-unknown
cargo +1.90.0 check --locked -p nxrs-applications --target thumbv6m-none-eabi
cargo +1.90.0 build --locked --release --lib -p nxrs-simulator --target wasm32-unknown-unknown
node tests/browser/run-wasm-scenarios.mjs target/wasm32-unknown-unknown/release/nxrs_simulator.wasm
```

For real browser execution install `playwright@1.56.1`, run
`npx playwright install chromium`, and add `--browser` to the Node command.

`.github/workflows/portable.yml` runs native tests on Linux/macOS/Windows,
compiles the production crates for Cortex-M0, and executes the shared Rust
assertions inside Node and a real headless Chromium page. These are application
and HAL-contract qualifications, not MCU emulation or hardware validation.
The browser runner reads scenario names/count from WASM itself and fails on
any trap, failed assertion, invalid registry or missing scenario execution.

The suite covers fan-out, independent/standalone compositions, slow consumers,
atomic retries, full storage, start/stop/flush failures, actual format
negotiation, malformed metadata, staging isolation, clock regression, repeated
lifecycles and deterministic interleavings checked against a separate history
model. Existing Linux/NuttX build checks remain intact. The new normal-main
NuttX/std and app-entry gates remain implementation work.

## Hardware integration

Native and NuttX adapters now live under `hal/native` and `hal/nuttx`. Physical
camera/radio integration and a possible Zephyr adapter remain separate work;
do not expose unsafe global state as safe shared services.
Qualify real negotiated formats, bounded latency, stop/restart, buffers and
error/partial-write behavior with the same contract tests plus hardware tests.
Route firmware entry points through the selected app's construction. OS selection
is a backend decision; it must not fork application policy or scenario behavior.
