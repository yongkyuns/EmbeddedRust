# Concurrency and event communication architecture

> **Status: design discussion, not an implemented framework.** This revision
> maps the ownership model to Rust `std` and existing libraries. The defaults
> below are the current proposal; lifecycle details, readiness integration and
> the final public API still need discussion. No production code or dependencies
> are changed by this document.

## Direction

> **Messages are for coordination, not routine data flow.**

A high-rate exchange is a reason to reconsider the ownership boundary, not a
reason to start optimizing a message graph. Keep tightly coupled processing in
one owner with direct calls and borrowed data. Introduce independent execution
only for a concrete scheduling, resource, latency or lifecycle requirement.

The app/service layer is Rust, so the default should be Rust-native:

| Concern | Proposed default |
| --- | --- |
| Service state | An ordinary owning struct, with synchronous helper modules |
| Independent execution | `std::thread::Builder`; no mandatory actor trait |
| Commands and important events | Service-defined enums with bounded payloads |
| Messages from multiple services | One bounded inbox per receiving owner, using a destination-local enum |
| Message-only wait | One `recv()` or deadline-aware `recv_timeout()` |
| Existing separate inboxes | `crossbeam-channel::select!` when separate queues are justified |
| Messages plus device readiness | Typed queue plus a wake source in one I/O wait set |
| Bulk data | Local borrows, or explicitly budgeted owned buffers/rings across a justified boundary |

This assumes an in-process application with qualified `std` threading support.
It does not assume that every desktop crate supports NuttX, or that ordinary
browser WASM supports blocking Rust threads.

## Ownership boundaries, not a service graph

One active owner may contain several reusable modules, services and HAL
capabilities. A module, service, device or crate does not automatically need a
thread or an inbox. Reusability comes from normal Rust APIs, not from scheduling
every reusable component independently.

For navigation, acquisition, calibration and fusion normally share an owner:

~~~text
IMU/GNSS HAL -> preprocessing -> fusion -> local consumers
                 one owner; ordinary Rust calls
~~~

Sparse commands and semantic events cross that owner's boundary: start/stop,
mode changes, calibration completion, GNSS loss/recovery and faults. A sample
produced each processing cycle is not automatically a service event.

Another owner can be justified by independent scheduling, bounded buffering,
exclusive resource lifecycle, or isolating expensive/blocking work. For example,
a storage writer may need a bounded worker even when recording policy stays in
navigation. Do not put unpredictable blocking storage calls into the shared
owner merely to avoid a thread. A separate Rust thread also does not establish
memory-fault containment; process/MPU isolation is a different decision.

The review question remains:

> If A sends B a message every time A performs normal work, should A and B share
> an owner? If not, what scheduling or ownership requirement justifies the split?

## Idiomatic Rust service shape

Use an ordinary struct for private state and resources, with methods that take
`&mut self`. The following is illustrative domain code, not a framework API:

~~~rust,ignore
struct Navigation<I, G> {
    imu: I,
    gnss: G,
    calibration: Calibration,
    fusion: Fusion,
    health: Health,
}

impl<I: Imu, G: Gnss> Navigation<I, G> {
    fn on_imu_ready(&mut self) -> Result<(), Error> {
        let sample = self.imu.try_read()?;
        if let Some(sample) = sample {
            let corrected = self.calibration.correct(sample);
            self.fusion.update_imu(&corrected);
            self.health.observe_imu(&corrected);
        }
        Ok(())
    }
}
~~~

Move that state into its owner thread when independent execution is needed.
Do not default to `Arc<Mutex<Navigation>>` or expose mutable state to senders.
`Builder::spawn` already supplies fallible spawning, names, stack configuration,
and the `Send + 'static` requirements on captured values; privately owned state
need not be `Sync` merely to move into a thread. [Thread builder][thread-builder]

Keep two capabilities separate: a cloneable command handle for authorized
producers, and a unique lifecycle/task handle retained by the composition owner.
The latter owns joining and completion. Ordinary `main()` remains the composition
root; a service can continue acquiring its HAL resources during `start()`.

No universal `ActiveObject<Input, Output, Context, State, ...>` trait, custom
scheduler, async runtime or replacement thread API is required. Repeated run-loop
mechanics may become a small helper accepting closures or a narrow contract after
real services demonstrate the need.

## Typed, bounded service contracts

Each service can expose its own public `Command` and `Event` enums. They describe
requests and important transitions, not periodic stream outputs. Keep contract
types independent of concrete providers; importing an event type should not
select its producer's hardware implementation.

Use a typed in-process channel by default. `std::sync::mpsc::sync_channel` provides
bounded storage, cloneable producer endpoints and one receiver. Values move into
the channel; messages need not implement `Copy` or `Clone`. No enum codec,
`#[repr(C)]`, byte casting or serialization is required for this path.
[Bounded channel][std-channel], [sender operations][std-sender]

Set a nonzero capacity explicitly. Bound the payload as well as the event count:
small inline fields, fixed-capacity values, and only explicitly budgeted handles.
`size_of::<Event>()` does not bound heap storage reachable through a pointer. An
unrestricted `Vec` or `String` in a small enum is not a complete memory budget.
[Value size][size-of]

Use `try_send` during normal owner dispatch. Preserve ownership of a rejected
message and distinguish full from disconnected. Admission means queued, not
processed or acknowledged. A thin nxrs wrapper may rename these outcomes, but
should not replace the existing queue implementation. [Sender operations][std-sender]

## Messages from different services at one wait point

**The default is destination-owned fan-in, not one outbound queue per service.**
A receiving owner defines a local inbox enum containing just the command/event
contracts it consumes. Each producer gets a narrow endpoint that wraps its event
and submits it directly into this same bounded inbox.

~~~text
navigation::Event -> typed adapter --+
recording::Event  -> typed adapter --+-> bounded Controller inbox -> recv()
ControllerCommand -> command handle-+
~~~

The adapters are ordinary calls on the producer thread. They do not run the
controller's behavior, create relay threads, or add intermediate queues. Each
admitted event crosses one queue boundary.

Here is a self-contained message-only sketch using real standard-library APIs.
It deliberately contains only semantic events; it is not the proposed runtime
implementation or a timing/target qualification test.

~~~rust
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};

mod navigation {
    #[derive(Debug)]
    pub enum Event {
        GnssLost,
    }
}

mod recording {
    #[derive(Debug)]
    pub enum Event {
        StorageFull,
    }
}

#[derive(Debug)]
enum Command {
    Shutdown,
}

// Private to this destination, NOT a system-wide message enum.
#[derive(Debug)]
enum Inbox {
    Command(Command),
    Navigation(navigation::Event),
    Recording(recording::Event),
}

#[derive(Default)]
struct Controller {
    gnss_lost: bool,
    storage_full: bool,
}

impl Controller {
    fn run(mut self, inbox: Receiver<Inbox>) -> Self {
        while let Ok(message) = inbox.recv() { // sole blocking wait
            match message {
                Inbox::Navigation(navigation::Event::GnssLost) => {
                    self.gnss_lost = true;
                }
                Inbox::Recording(recording::Event::StorageFull) => {
                    self.storage_full = true;
                }
                Inbox::Command(Command::Shutdown) => break,
            }
        }
        self
    }
}

// An injected sink exposes only navigation's own public event type.
fn navigation_sink(
    tx: SyncSender<Inbox>,
) -> impl Fn(navigation::Event) -> Result<(), TrySendError<navigation::Event>> {
    move |event| match tx.try_send(Inbox::Navigation(event)) {
        Ok(()) => Ok(()),
        Err(TrySendError::Full(Inbox::Navigation(event))) => {
            Err(TrySendError::Full(event))
        }
        Err(TrySendError::Disconnected(Inbox::Navigation(event))) => {
            Err(TrySendError::Disconnected(event))
        }
        _ => unreachable!("try_send returns the value passed to this call"),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (tx, inbox) = mpsc::sync_channel::<Inbox>(8);
    let report_navigation = navigation_sink(tx.clone());
    let recording_tx = tx.clone();

    // Smoke illustration: queue a finite sequence, then run the owner.
    // Production passes narrow sinks to independently running services;
    // recording gets the same source-typed adapter as navigation.
    report_navigation(navigation::Event::GnssLost)?;
    recording_tx.try_send(Inbox::Recording(recording::Event::StorageFull))?;
    tx.try_send(Inbox::Command(Command::Shutdown))?;

    let state = Controller::default().run(inbox);
    assert!(state.gnss_lost && state.storage_full);
    Ok(())
}
~~~

Cloning `SyncSender` does not create another queue: the clones address the same
receiver. A blocked receive wakes for an admitted message from any of those
senders. Do not sequentially call `navigation_rx.recv()` and
`recording_rx.recv()`; waiting on an idle first channel could conceal work on the
second. [Bounded channel][std-channel], [receiver operations][std-receiver]

The service need not know `Controller` or `Inbox`. It can accept an injected
`Fn(Event) -> Result<(), TrySendError<Event>> + Send + 'static`, or an equivalent
small typed sink. The explicit adapter above preserves the source event on
rejection; a plain one-way `Into<Inbox>` conversion does not by itself supply that
error mapping. Choose a helper only after this boilerplate repeats. No `Any`,
`Box<dyn Message>`, proc macro or subscription registry is necessary.

`Inbox` belongs to this destination/composition. Another destination has its own
enum. A reusable consumer that should not depend on producer types can instead
receive its own commands, with semantic translation in application wiring. Do
not solve module dependency cycles by inventing a global enum.

Multiple instances can be distinguished with local variants such as
`PrimaryNavigation(...)` and `BackupNavigation(...)`, or a bounded instance tag.
A sender clone is not a broadcast subscription. Explicit fan-out to multiple
owners, when justified, needs a policy for partial admission and does not create
a system-wide publish/subscribe facility.

A common inbox shares capacity across senders and uses slots large enough for
its enum. It does not reserve capacity for each source or make racing producers'
arrival order deterministic. Encode correlation/ordering only when the domain
needs it; avoid treating scheduling order as measurement-time order.

## Alternative: select across existing typed queues

A **single wait point does not require a single physical queue**. Where separate
queue capacities, source lifetimes or existing APIs are useful, reuse
`crossbeam-channel::select!` (or `Select` for a dynamic set). The receive arms may
have different payload types. [Crossbeam selection][crossbeam-select]

~~~rust,ignore
loop {
    crossbeam_channel::select! {
        recv(navigation_events) -> event => match event {
            Ok(event) => controller.on_navigation(event),
            Err(_) => break, // chosen policy: a required source closed
        },
        recv(recording_events) -> event => match event {
            Ok(event) => controller.on_recording(event),
            Err(_) => break,
        },
        recv(commands) -> command => match command {
            Ok(command) => controller.on_command(command),
            Err(_) => break,
        },
    }
}
~~~

This is one blocking selection, not round-robin polling or sequential waits.
These must be Crossbeam receivers, not `std::mpsc::Receiver` values. Normal
`select!` chooses randomly among simultaneously ready operations; it is not a
hard fairness, deadline or priority guarantee. Disconnected channels are ready
too: handle closure by stopping as above, or removing/disabling an optional arm.
Ignoring repeated receive errors can otherwise produce a busy loop.
[Crossbeam selection][crossbeam-select]

Keep exactly one consumer for each active-owner inbox even though Crossbeam
allows receiver cloning. Prefer the existing std-backed channel for simple
fan-in; select is an available alternative, not a reason to add queues or migrate
all services. Neither alternative requires Rust async `.await`.

## Deadlines at the same wait point

For a message-only owner with a deadline, use `recv_timeout()` with the remaining
time until an absolute `Instant`. Check due deadlines between dispatches, not
only when a receive reports timeout: continuous message traffic can otherwise
starve the timer. Do not reset the deadline after every incoming event.
[Receiver operations][std-receiver]

~~~rust,ignore
loop {
    if Instant::now() >= next_deadline {
        on_deadline(); // bounded work; advance with an explicit overrun policy
        next_deadline = next_deadline_after(Instant::now());
    }
    let remaining = next_deadline.saturating_duration_since(Instant::now());
    match inbox.recv_timeout(remaining) { // sole blocking wait
        Ok(event) => dispatch(event),
        Err(RecvTimeoutError::Timeout) => continue,
        Err(RecvTimeoutError::Disconnected) => break,
    }
}
~~~

Deadline computation and missed-period policy remain service-specific. There is
no mandatory timer thread, periodic tick-message producer or custom clock HAL.
Use `std::time`; behavior tests can supply explicit timestamps to ordinary
methods without replacing the whole OS time API.

## Device readiness and messages: one I/O wait, not two

A standard channel receive does not wait on arbitrary device descriptors, and
Crossbeam selection selects channel operations rather than device I/O. For an
owner with pollable I/O, keep typed message storage but attach a persistent wake
source to the same I/O wait set as its device readiness. [Receiver API][std-receiver],
[Crossbeam selection][crossbeam-select]

The producer enqueues the typed message, then notifies that wake source. The
owner processes bounded inbox batches with `try_recv()`, processes ready devices
and due deadlines, then blocks only in the I/O wait operation. It must never
block in `recv()` after the I/O poller wakes: doing so could stall device work.

`polling::Poller` supplies `wait()` and `notify()`; notification wakes the current
or following wait. Mio supplies `Poll` and `Waker`. Reuse a supported backend
rather than designing a general reactor. These are candidates, not claims that
either library is already qualified on nxrs's NuttX/browser profiles.
[Poller][poller], [Mio Waker][mio-waker]

The small adapter still needs a precise, tested protocol:

- Queue contents are authoritative; notifications may coalesce. Do not assume
  one wake equals one message, or that an empty wake is an error.
- After a bounded batch, never sleep indefinitely while queued or locally ready
  work remains. Retain pending-work state and use a nonblocking wait iteration
  to reconsider other sources when necessary.
- Wake notification must cover the empty-check-to-sleep race, including the
  sender notifying before the owner enters its wait.
- Edge-triggered I/O must remain runnable until drained to `WouldBlock`; a batch
  limit alone is not permission to await another edge. One-shot modes require
  rearming according to their API. [Mio readiness][mio-poll], [Poller][poller]
- An enqueue followed by wake failure is not a rejected message. Do not return
  the event as unsent or encourage retry/duplication. Surface an admitted-but-
  wake-failed/backend-failed outcome and define recovery before implementation.
- Close/shutdown must wake an idle owner too. Dropping the last ordinary channel
  sender does not independently notify an unrelated I/O poller; the adapter
  needs an explicit close notification or equivalent integrated lifecycle.

For NuttX, a narrow native readiness adapter may be appropriate after checking
its selected configuration and HAL support. Device descriptors and their
registration/lifetime belong behind that adapter; portable services should not
select concrete device paths. No queue, wakeup or try-send operation is assumed
ISR-safe merely because it does not wait for queue capacity.

## Why POSIX MQ is no longer the default

Active ownership is compatible with POSIX MQ, but it does not require it. For
this Rust-only, in-process model, prefer typed Rust queues plus an I/O wake source
when needed. Do not encode every enum into bytes merely to obtain a pollable
notification.

Retain POSIX MQ only for a justified external/C/process interface or a measured
platform-specific requirement. That boundary then needs an explicit validated
representation and its own lifetime rules. Native `poll()` remains useful for
readiness regardless of whether POSIX MQ is used for message storage.

## Bounded bulk data and memory

High-rate or large data remains outside the generic command/event channel.
Within one owner, use borrows. Across a justified execution boundary, transfer
preallocated owning buffers on a specialized bounded data path, or reuse a
bounded SPSC ring such as `rtrb` when its constraints fit. Shared storage does
not mean unrestricted shared mutation. [SPSC ring][rtrb]

Rust ownership should do the default lifetime work: moving an owning buffer
handle avoids a deep payload copy. A fixed set of `Box<[u8]>` buffers can be
allocated at startup and recycled. Use immutable `Arc` sharing only when multiple
consumers genuinely need overlapping ownership; it is not automatic mutation
safety or a complete pool-reuse protocol. DMA alignment, cache maintenance,
completion and device access need a provider-specific contract.
[Box][box], [Arc][arc]

Use an existing bounded collection when helpful rather than a new nxrs container.
`Vec::with_capacity` reserves capacity; it is not a hard length limit. Enforce a
limit or use arrays/boxed slices/`ArrayVec`. Initialization may allocate while
steady state follows an explicit allocation budget, verified on the actual
build including overload and error paths. [Vec][vec], [ArrayVec][arrayvec]

No per-frame control event is required when a device/ring readiness source can
wake the consumer. Pool exhaustion, held-buffer limits and shutdown reclamation
must remain explicit even when the associated control inbox is empty.

## Lifecycle, overload and determinism

The common contract should distinguish startup attempted from service ready,
message admission from completion, and service failure from channel closure.
A thread being spawned does not by itself establish readiness. Keep acknowledgments
explicit and sparse; do not build a general RPC system or allocate a reply channel
for every routine event.

Normal handlers should not block on another owner, wait for queue capacity, or
join a peer. `try_send` full/disconnected outcomes need message-specific policies.
Important events are not automatically safe to discard. Persistent saturation
should trigger investigation; bounded storage does not guarantee delivery.

Define stop admission and shutdown progress even when the queue is full. Options
still under discussion include quiescing producers before a queued stop marker,
or a separate persistent stop request integrated into the same wait. A queued
stop drains only work preceding it under the chosen protocol; it does not
magically close cloned senders or acknowledge racing posts. A stop flag alone
cannot wake a sleeping owner. No policy here permits an additional blocking wait.

The composition owner explicitly shuts down and joins tasks, handling failures
and outstanding buffers. Do not hide a potentially blocking join in `Drop`.
Dropping `JoinHandle` detaches the thread. A panic is not necessarily recoverable
on an aborting embedded build; ordinary recoverable failures use `Result`.
[Thread completion][thread-join]

Check deadlines and bound device/command batches. Ordered private mutation does
not establish global producer order, hard real-time scheduling, lock freedom,
priority inheritance, or memory-fault isolation. Measure handler latency,
starvation, CPU, stacks, queue/pool high-water marks and steady-state allocation
before making performance claims.

## Small reusable crate: contracts and integration

Tentative name: `nxrs-ao`; placement and name remain open. Build on the existing
[std-backed transport](../service/event/src/lib.rs), not another queue algorithm.
The useful shared pieces are typed endpoint/inbox ownership, a unique task handle,
explicit lifecycle outcomes, and narrowly tested wake/dispatch integration.

Reuse `std` first. Add Crossbeam only for operations actually needed; choose
`polling`/Mio or a native adapter only after target validation. Fixed-capacity
collections, specialized rings and tools such as Loom are available where the
requirement warrants them. Loom only explores synchronization modeled through
its types; it does not qualify arbitrary OS readiness calls. [Loom][loom]

Keep this crate independent of navigation, HAL provider selection and application
composition. Do not add a global enum/bus, service registry, generic actor runtime,
mandatory executor, universal service trait, serializer, scheduler, buffer-ID
protocol or subscription graph. A few private structs and helpers may be enough.

## Existing demo and validation boundaries

The [event demo](event-driven-demo.md) currently puts IMU, GNSS and fusion in
separate owners and sends samples through channels. Retain its execution,
portability and lifecycle evidence, but do not treat that topology as the target
product decomposition. The [architecture overview](architecture.md) distinguishes
that current implementation from this discussion.

This documentation change does not refactor those services or select new target
backends. The Rust sketches explain the proposed contract; they do not establish
allocation freedom, deadlines, NuttX/browser support or production shutdown.

Before adopting helpers, qualify multi-producer fan-in, full/disconnected payload
recovery, source closure, deadline progress under sustained events, shutdown at
capacity, and mixed-I/O wake/close races. Compare with raw std primitives on the
same target. Avoid benchmarking an unnecessary message graph and calling that an
architecture improvement.

## Remaining discussion

1. **API surface and reuse:** are narrow closures sufficient for event sinks, or
   does repeated code justify a small typed sender adapter/task helper? No
   mandatory `ActiveObject` trait is presumed.
2. **Capacity and stop policy:** when is common-inbox capacity enough, and when
   are separate queues or reserved admission needed? How is shutdown progress
   ensured without blocking another owner or pretending queued means completed?
3. **Readiness adapter:** choose the minimal NuttX/native/browser integration,
   ownership of registrations, and treatment of notification/close failures.
4. **Scheduling and fairness:** define deadline-overrun and source-batch policies;
   keep target-specific priorities separate from portable stack/name settings.
5. **Bulk ownership and examples:** reuse path-specific pools until common needs
   justify sharing; decide whether to add a coarse-owner example alongside the
   existing qualification demo rather than replacing its evidence.

The default direction is now typed Rust fan-in, not an unresolved choice between
POSIX MQ and Rust messaging. The broader wait/dispatch and lifecycle API remains
open for review.

## API references

These references describe primitives, not qualification of a specific nxrs target
or dependency version. Use pinned toolchains/dependencies for implementation.

[std-channel]: https://doc.rust-lang.org/std/sync/mpsc/fn.sync_channel.html
[std-sender]: https://doc.rust-lang.org/std/sync/mpsc/struct.SyncSender.html
[std-receiver]: https://doc.rust-lang.org/std/sync/mpsc/struct.Receiver.html
[thread-builder]: https://doc.rust-lang.org/std/thread/struct.Builder.html
[thread-join]: https://doc.rust-lang.org/std/thread/struct.JoinHandle.html
[size-of]: https://doc.rust-lang.org/std/mem/fn.size_of.html
[crossbeam-select]: https://docs.rs/crossbeam-channel/latest/crossbeam_channel/macro.select.html
[poller]: https://docs.rs/polling/latest/polling/struct.Poller.html
[mio-poll]: https://docs.rs/mio/latest/mio/struct.Poll.html
[mio-waker]: https://docs.rs/mio/latest/mio/struct.Waker.html
[box]: https://doc.rust-lang.org/std/boxed/index.html
[arc]: https://doc.rust-lang.org/std/sync/struct.Arc.html
[vec]: https://doc.rust-lang.org/std/vec/struct.Vec.html
[arrayvec]: https://docs.rs/arrayvec/latest/arrayvec/
[rtrb]: https://docs.rs/rtrb/latest/rtrb/
[loom]: https://docs.rs/loom/latest/loom/
