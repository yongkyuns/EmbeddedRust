# Concurrency and event communication architecture

> **Status: design discussion, not an implemented framework.** The proposed
> direction is Rust-native event communication with HAL-owned acquisition and
> protocol processing. Public helper APIs, lifecycle details and capacity policy
> remain open. This document changes no production code or dependencies.

## Direction

> **Keep tightly coupled processing together. Use messages at meaningful
> boundaries, including normalized hardware events from the HAL.**

Inter-service communication is for coordination, not for constructing a
fine-grained graph of routine sample-processing stages. Hardware delivery is a
legitimate asynchronous boundary: a completed GNSS measurement can be an event
in the receiving service's inbox even though measurements occur periodically.
Do not confuse that boundary with relaying every sample between small services.

The app/service layer is Rust, so the defaults should be Rust-native:

| Concern | Proposed default |
| --- | --- |
| Service state | An ordinary owning struct with synchronous helper modules |
| Independent service execution | `std::thread::Builder`; no mandatory actor trait |
| Device waiting, acquisition and parsing | HAL provider/driver implementation, not the service loop |
| HAL delivery | Bounded device-independent events sent directly to the owning service's inbox |
| Commands and peer events | Service-defined enums with bounded payloads |
| Multiple event sources | One destination-owned bounded inbox with a local enum |
| Service wait | One `recv()` or deadline-aware `recv_timeout()` for HAL, peer and command events |
| Existing separate inboxes | Crossbeam selection only when separate queues are justified |
| Bulk data | Local borrows or budgeted owning buffers/rings, with integrated notification |

This assumes an in-process application on qualified `std` execution targets.
It does not assume every desktop crate supports NuttX or that ordinary browser
WASM supports blocking Rust threads.

## Ownership boundaries, not a service graph

A service may contain several reusable processing modules and own lifecycle
handles for several HAL capabilities. The service owns application state; an
active HAL provider owns its acquisition/parsing state and low-level resources.
Owning a capability's lifecycle handle does not require servicing its UART on
the service thread.

For navigation, the intended boundary is:

~~~text
GNSS device -> HAL acquisition + parser -> normalized event -> service inbox
peer service ------------------------------ semantic event -> same inbox
application -------------------------------------- command -> same inbox

service dispatch -> calibration / fusion / health (ordinary local calls)
~~~

Do not introduce an additional GNSS relay service merely to forward the HAL's
already-normalized result to navigation. A separate service is justified only
when it owns useful domain behavior or an independent lifecycle/scheduling need.

One module, device, capability or crate does not automatically require a thread.
Independent execution should have a resource, scheduling or latency reason.
A storage writer may need a bounded worker while recording policy remains in
navigation. Do not introduce unpredictable blocking storage into navigation
merely to avoid a thread. Separate threads do not establish memory-fault
containment; process/MPU isolation is a different decision.

The review question remains: if A sends B data on every normal processing cycle,
should their application processing share an owner? Device acquisition can still
be independently hosted behind HAL without splitting the application algorithm.

## HAL owns device waiting, parsing and normalization

For GNSS, the HAL implementation should own opening/configuring the selected
receiver, waiting/reading, buffering partial input, validating frames, parsing
NMEA or UBX as appropriate, and producing the common GNSS contract. Polling,
descriptors, serial framing and receiver-specific recovery stay below the
portable service boundary. Reuse parser/driver implementations where suitable;
this proposal does not require writing new protocol parsers.

Parsing code can live in a reusable driver/protocol crate used by the HAL
provider. "In the HAL" means hidden behind the capability contract, not that
all parsing must be embedded in one facade source file. The service must not
branch on NMEA versus UBX or depend on a physical receiver model.

| Responsibility | Owner |
| --- | --- |
| UART/socket/device wait and cancellation | HAL provider/target support |
| Byte framing, checksum validation, protocol decoding | Provider/driver behind HAL |
| Assemble and timestamp a device-independent GNSS solution | GNSS HAL |
| Queue admission of a HAL event | Injected typed sink and explicit delivery policy |
| Sensor fusion, application modes and product decisions | Service |
| Product composition and top-level lifecycle | Ordinary application `main()` |

The common contract must define units, coordinate/time frames, measurement time
versus arrival time, validity and optional fields. Do not fabricate fields absent
from a source protocol, merge incompatible measurement epochs, or pass parser-
owned temporary references across threads. Device independence does not mean
pretending every receiver provides the same information.

HAL status describes capability facts, such as a solution becoming unavailable
or an acquisition failure. Application reactions, such as entering a degraded
navigation mode, remain service decisions.

### Does the HAL need its own thread?

An event-driven HAL owns the execution needed to make progress. A dedicated
`std` worker that waits, reads, parses and posts normalized events is a reasonable
starting point for a blocking serial GNSS provider. It does useful acquisition
work, not merely queue forwarding.

Threading is nevertheless a provider implementation choice, not one thread per
capability or parser. A provider may use an existing driver worker, a shared HAL
I/O loop, or platform callbacks where appropriate. A native replay/mock provider
can emit the same events without a UART parser. A browser provider can use its
available callback/worker machinery under the separately qualified browser
profile. The service event contract must not change with that choice.

The HAL must not invoke service handlers on its worker/callback thread. Its
injected sink only translates and enqueues; the service mutates its state after
receiving the event. No std channel operation is assumed ISR-safe: interrupts
must hand off through a target-qualified deferred path before using such a sink.

## Idiomatic Rust service shape

Use an owning struct with `&mut self` methods. Illustrative domain code:

~~~rust,ignore
struct Navigation {
    gnss: GnssSession, // capability lifecycle/control, not raw UART access
    calibration: Calibration,
    fusion: Fusion,
    health: Health,
}

impl Navigation {
    fn on_gnss(&mut self, event: gnss::Event) {
        match event {
            gnss::Event::Solution(solution) => {
                self.fusion.update_gnss(&solution);
                self.health.observe_gnss(&solution);
            }
            gnss::Event::Unavailable => self.health.gnss_unavailable(),
        }
    }
}
~~~

`GnssSession`, event variants and methods here are proposed shapes, not existing
nxrs APIs. The receiver owns coherent typed values; it does not call `poll()`,
read bytes, run a parser, or wait on a second GNSS receiver from this handler.

Move the service state into its thread where needed. Do not default to
`Arc<Mutex<Navigation>>` or expose mutable service state to senders.
`Builder::spawn` supplies fallible spawning, names, stack configuration and
`Send + 'static` requirements on captured values; private state need not be
`Sync` simply to move into a thread. [Thread builder][thread-builder]

Keep a cloneable command handle separate from the unique lifecycle/task handle.
A service normally acquires its HAL capability during `start()`, registers a
narrow event sink and retains the returned lifecycle handle. No platform launcher,
mandatory actor trait, custom scheduler or universal service interface is needed.

## Typed contracts and destination-owned fan-in

Services expose command and semantic-event enums. HAL capabilities expose their
own device-independent data/status event enums. A receiver's private inbox enum
combines only the contracts it consumes; there is no system-wide message enum.

The HAL must not depend on the receiving service or its private inbox type.
Inject a narrow sink such as `Fn(gnss::Event) -> Result<(), PostError<gnss::Event>>`.
For a worker-owned sink, require the appropriate `Send + 'static` bounds at start.
Use ordinary generics or a small helper, not a dynamic message registry.

Capability data/event types may remain `no_std`. A std-backed delivery/lifecycle
adapter can sit in the facade/provider or a small neutral support crate. Do not
make HAL depend upward on a service implementation to obtain a channel wrapper.
The exact placement remains open; no dependency-checker rules change in this PR.

`std::sync::mpsc::sync_channel` provides bounded storage, cloned senders and one
receiver. Cloning a sender does not create another queue. Events move as Rust
values; no `Copy`, `Clone`, enum codec, byte casting or `#[repr(C)]` is required.
[Bounded channel][std-channel], [sender operations][std-sender]

Set a nonzero capacity. Bound both event count and payload: inline values,
fixed-capacity fields or explicitly budgeted handles. `size_of::<Event>()` does
not account for storage behind pointers. [Value size][size-of]

The connection is direct:

~~~text
GNSS HAL   -> sink wraps Inbox::Gnss(event) ------+
recording  -> sink wraps Inbox::Recording(event)-+-> one bounded inbox -> recv()
commands   -> handle wraps Inbox::Command(cmd) --+
~~~

There is no HAL-output queue that another thread drains into a service queue.
The source-typed sink executes on the producer, not on a new relay thread, and
never runs the receiving service's behavior. Each admitted event crosses one
queue boundary.

### Self-contained std-only fan-in illustration

This demonstrates delivery of a normalized HAL result, a peer service event and
a command to one wait point. The synthetic worker does not implement real GNSS
acquisition or parsing; the timestamp domain below is an arbitrary test domain.
It is not an implementation of the proposed nxrs HAL API.

~~~rust
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};

mod gnss {
    #[derive(Debug)]
    pub struct Solution {
        pub sequence: u64,
        pub measurement_time_ms: u64,
        pub velocity_ned_mps: Option<[f32; 3]>,
    }

    #[derive(Debug)]
    pub enum Event {
        Solution(Solution),
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
    BeginCalibration,
}

#[derive(Debug)]
enum Inbox {
    Gnss(gnss::Event),
    Recording(recording::Event),
    Command(Command),
}

#[derive(Default)]
struct Service {
    last_fix: Option<gnss::Solution>,
    storage_full: bool,
    calibration_requested: bool,
}

impl Service {
    fn run(mut self, inbox: Receiver<Inbox>) -> Self {
        while let Ok(event) = inbox.recv() { // the only blocking service wait
            match event {
                Inbox::Gnss(gnss::Event::Solution(fix)) => {
                    self.last_fix = Some(fix); // real service calls fusion here
                }
                Inbox::Recording(recording::Event::StorageFull) => {
                    self.storage_full = true;
                }
                Inbox::Command(Command::BeginCalibration) => {
                    self.calibration_requested = true;
                }
            }
        }
        self
    }
}

fn gnss_sink(
    tx: SyncSender<Inbox>,
) -> impl Fn(gnss::Event) -> Result<(), TrySendError<gnss::Event>> + Send {
    move |event| match tx.try_send(Inbox::Gnss(event)) {
        Ok(()) => Ok(()),
        Err(TrySendError::Full(Inbox::Gnss(event))) => {
            Err(TrySendError::Full(event))
        }
        Err(TrySendError::Disconnected(Inbox::Gnss(event))) => {
            Err(TrySendError::Disconnected(event))
        }
        _ => unreachable!("try_send returns the value passed to this call"),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (tx, inbox) = mpsc::sync_channel::<Inbox>(8);
    let emit_gnss = gnss_sink(tx.clone());
    let provider = std::thread::Builder::new()
        .name("synthetic-gnss-hal".into())
        .spawn(move || {
            emit_gnss(gnss::Event::Solution(gnss::Solution {
                sequence: 1,
                measurement_time_ms: 1000,
                velocity_ned_mps: Some([1.0, 0.0, 0.0]),
            }))
        })?;

    // Production recording/command endpoints use equally narrow adapters.
    tx.try_send(Inbox::Recording(recording::Event::StorageFull))?;
    tx.try_send(Inbox::Command(Command::BeginCalibration))?;
    drop(tx);

    // The finite fixture ends when all producers drop their senders.
    // This is not a production shutdown protocol for service-owned HALs.
    let state = Service::default().run(inbox);
    provider.join().map_err(|_| "synthetic HAL worker panicked")??;
    let fix = state.last_fix.expect("GNSS result was admitted");
    assert_eq!(fix.sequence, 1);
    assert_eq!(fix.measurement_time_ms, 1000);
    assert_eq!(fix.velocity_ned_mps, Some([1.0, 0.0, 0.0]));
    assert!(state.storage_full && state.calibration_requested);
    Ok(())
}
~~~

An admitted message from any producer wakes the same receive operation.
Do not sequentially block on a GNSS receiver and a command receiver, and do not
return raw descriptor readiness to portable service code.
[Receiver operations][std-receiver]

The adapter preserves the original typed event on full/disconnected rejection;
a one-way `Into<Inbox>` conversion alone does not supply that error mapping.
Successful admission means queued, not processed. Normal producers should use
`try_send`, with explicit handling rather than silently discarding errors.
[Sender operations][std-sender]

The service creates its inbox before enabling HAL production. If startup later
fails, it must stop any producers already started. A `Ready` notification needs a
defined meaning: worker started, device configured and first valid solution are
not equivalent milestones.

Multiple instances can use destination-local variants or bounded tags. Another
consumer has its own inbox enum, or receives its own commands through semantic
translation. A cloned sender is not a subscription; fan-out requires an explicit
partial-admission policy. Keep those connections out of the GNSS protocol code.

## One service wait, with optional deadlines

Normalized HAL events, commands and peer events all use the same service inbox.
A plain `recv()` is sufficient when the service has no independent deadline.
No generic service-side I/O reactor or separate HAL receive loop is required.

When it has a deadline, use `recv_timeout()` with the remaining time until an
absolute `Instant`. Check due deadlines between events, not only after a timeout;
continuous GNSS or peer traffic must not indefinitely defer time-based work.
Do not reset the deadline merely because another event arrived.
[Receiver operations][std-receiver]

~~~rust,ignore
loop {
    if Instant::now() >= next_deadline {
        on_deadline(); // bounded work and an explicit missed-period policy
        next_deadline = next_deadline_after(Instant::now());
    }
    let remaining = next_deadline.saturating_duration_since(Instant::now());
    match inbox.recv_timeout(remaining) { // the single blocking service wait
        Ok(event) => dispatch(event),
        Err(RecvTimeoutError::Timeout) => continue,
        Err(RecvTimeoutError::Disconnected) => break,
    }
}
~~~

Use ordinary `std::time`; no mandatory timer thread, periodic tick-message
producer or custom clock HAL is needed. Measurement timestamps remain explicit
HAL data, not inferred from when `recv()` returns.

### Alternative: selecting separate typed channels

One wait point does not require one physical queue. Existing APIs or separate
capacity/lifetime requirements may justify `crossbeam-channel::select!`/`Select`
over typed HAL, command and peer receivers. Reuse this existing mechanism rather
than implement a selector. It selects channel operations, not raw device I/O.
[Crossbeam selection][crossbeam-select]

These must be Crossbeam receivers, not std receivers. Keep one consumer per
service even though Crossbeam permits receiver cloning. Normal selection is
random among ready operations, not a hard fairness/priority guarantee. Closed
channels are ready too: stop or disable an optional closed source rather than
repeatedly ignoring errors. This is an alternative, not a reason to introduce
separate queues or change every service. No Rust async `.await` is required.
[Crossbeam selection][crossbeam-select]

## Provider-internal I/O waits and cancellation

The earlier proposal to combine device descriptors and the inbox in the
**service** loop is superseded. Any such mixed I/O wait belongs inside HAL
provider/target support, for example combining a GNSS UART and cancellation or
receiver-configuration requests. The portable service consumes normalized events.

A provider may reuse a supported poller or a narrow native adapter. `polling`
supplies `wait`/`notify`; Mio supplies `Poll`/`Waker`. Neither is assumed qualified
for nxrs's NuttX/browser profiles. POSIX MQ may still suit a real C/process
boundary or measured provider requirement, but is not needed to serialize
Rust-only service events. [Poller][poller], [Mio Waker][mio-waker]

Provider internals must address coalesced notifications, wake-before-wait races,
edge/one-shot rearming, cancellation, and close wakeups. After a bounded batch,
retain runnable state until an edge-triggered source is drained to `WouldBlock`;
do not sleep indefinitely awaiting another edge while work remains.
[Mio readiness][mio-poll]

A notification failure after admission is not a rejected message safe to resend.
Define backend failure/recovery separately. These concerns stay behind HAL;
the service does not implement an OS-specific queue-to-descriptor bridge.

## Normalized measurements, bulk data and overload

A small normalized GNSS result is useful hardware input even when periodic.
Sending it once from HAL to its owning service is within this design. Do not
then forward it through separate preprocessing, fusion and health actors: those
can be ordinary calls inside the same service. Message rate alone is not the
criterion; meaningful ownership and work performed at the boundary are.

Raw byte chunks, per-character notifications and redundant per-sentence events
should not leak into the service. Define which complete measurements/status
changes are relevant and deliver those. Keep buffering and normalization bounded
inside HAL; do not conceal unbounded buffering behind a small event type.

For genuinely high-rate or large payloads, use a specialized bounded buffer/ring
path and a HAL event in the same service inbox indicating available work. A
bounded `drain`/`take_ready` API may access already-normalized data; it must not
block awaiting hardware, expose raw descriptors or ask the service to parse.
Notification coalescing must not lose work: preserve pending data, re-notify or
continue bounded local dispatch before sleeping again. The exact protocol needs
tests; a boolean flag without race/lifecycle handling is insufficient.

Within one processing owner, borrow data. Across a justified boundary, transfer
preallocated owning buffers or reuse a bounded SPSC ring such as `rtrb`.
Moving an owning buffer handle avoids a deep payload copy. A fixed set of
`Box<[u8]>` buffers can be allocated once and recycled. Use immutable `Arc` only
for genuinely overlapping readers. DMA alignment, cache maintenance and device
completion remain provider responsibilities. [SPSC ring][rtrb], [Box][box], [Arc][arc]

`Vec::with_capacity` is a reservation, not a hard limit. Enforce limits or use
arrays, boxed slices or `ArrayVec`. Verify allocation budgets including error
paths; neither a bounded queue nor a small handle bounds all reachable memory.
[Vec][vec], [ArrayVec][arrayvec]

A common inbox shares capacity across HAL and peer producers. A fix flood must
not silently remove command/shutdown progress. Specify source rate/burst limits,
capacity and full policies. Do not indefinitely block an acquisition worker on
service progress and thereby prevent device draining or cancellation.

A latest-value display might permit replacing stale solutions; an estimator may
need chronological measurements and visible gap/overrun reporting instead.
Coalescing/dropping is a capability-and-consumer contract, never an automatic
framework policy. Report overflow independently of successfully enqueueing one
more event into the same full queue, for example with sticky status/counters
that become observable when the service resumes. No delivery guarantee is
claimed before this protocol and its tests exist.

## Lifecycle, source failure and determinism

Distinguish startup from readiness, admission from completion, and source failure
from whole-inbox closure. One failed HAL producer may disappear while command
senders remain alive: that does not disconnect the common receiver. Provide an
explicit source-lifecycle outcome/status mechanism rather than infer hardware
health from `recv()` disconnection. Terminal-event admission must have a policy.

Normal dispatch must not synchronously await another service, wait for queue
space, or join a peer/HAL worker. Hardware configuration that completes later
can produce a completion event at this same service inbox. A synchronous,
bounded local operation does not require an artificial asynchronous protocol.

A service owns its HAL session lifecycle. Startup creates/registers sinks before
enabling production and rolls back partial starts. Shutdown requests provider
stop, wakes any provider blocked on hardware, resolves queued/in-flight data and
quiesces callbacks before releasing their resources. Requesting stop and joining
must not create a cycle where the provider needs the service to drain a full
inbox before it can finish. Exact drain/discard and acknowledgment rules remain
open; finite queues alone do not provide shutdown guarantees.

Stop must progress even at capacity. Options include quiescing producers before
a queued stop marker or a persistent stop request integrated with the same wait.
A flag alone cannot wake a blocked service. A service holding HAL handles whose
workers hold sender clones cannot rely on automatic channel closure for shutdown.

The lifecycle owner explicitly joins tasks after the needed progress is ensured.
Do not hide blocking joins in `Drop`; dropping `JoinHandle` detaches its thread.
An aborting embedded build does not make panics recoverable. Ordinary recoverable
errors use `Result`. [Thread completion][thread-join]

One owner serializes private mutations, not the measurement times of racing
sources. Preserve explicit timestamps/sequence information. Neither this model
nor `try_send` guarantees hard real-time scheduling, lock freedom, priority
inheritance or ISR safety. Measure provider/service latency, starvation, CPU,
stacks, queue/pool occupancy and allocation on the actual target.

## Small reusable crate and existing implementation

Tentative name: `nxrs-ao`; placement and name remain open. Reuse the current
[std-backed transport](../service/event/src/lib.rs) and standard threads rather
than write a queue algorithm or scheduler. The shared value is narrow typed
endpoints, one inbox, lifecycle outcomes and consistently tested dispatch.

Keep neutral messaging support independent of service implementations and HAL
provider selection. HAL event/data contracts do not require a global event enum.
No generic actor runtime, serializer, service graph, mandatory async executor or
service-side device wait-set API is required by this design. Provider-internal
waiting belongs to HAL/target support.

The current [GNSS API](../hal/gnss/api/src/lib.rs) is synchronous
(`Gnss::fix`) and already hides receiver protocols; it does not implement the
proposed event-producing HAL session. This document specifies a direction for
future work, not an existing capability. The [event demo](event-driven-demo.md)
remains useful std/thread/channel and lifecycle evidence, not a requirement to
retain its separate sensor-service-to-fusion message topology. See the
[architecture overview](architecture.md) for the distinction from current code.

Use established bounded collections/rings where needed. Loom can help with small
custom synchronization protocols expressed through its model types; it does not
qualify arbitrary OS readiness or DMA operations. [Loom][loom]

Before implementation, qualify same-inbox HAL/peer/command delivery, rejected
payload recovery, device-independent normalization, source termination while
other producers remain alive, deadlines under sustained data, overflow visibility,
partial startup rollback, full-inbox shutdown, blocked-read cancellation and
post-stop callback quiescence. Test normalization using synthetic protocol input
and test service behavior using already-normalized values; hardware is not needed
for those layers. Hardware and selected-target execution still require their own
qualification. No runtime or performance guarantees follow from these sketches.

## Remaining discussion

1. **HAL session API and support placement:** sink closures versus a narrow typed
   endpoint, neutral support dependencies and how the service owns start/stop.
2. **GNSS data contract:** coherent epochs, optional fields, validity, timestamp
   domains and observable source lifecycle without protocol leakage.
3. **Capacity and shutdown:** admission/reservations or separate queues, overload
   policy, terminal-event handling and cancellation without wait-for cycles.
4. **Provider execution:** dedicated/shared worker or callbacks, selected-target
   cancellation support, scheduling, stack budgets and ISR deferred paths.
5. **Bulk delivery and fairness:** bounded drains and loss-free notification,
   pool reuse, deadline policy and a coarse-owner example alongside existing tests.

The boundary is settled for this proposal: **HAL waits on and interprets devices;
services wait once for normalized HAL events, peer events and commands.** The
helper APIs and qualification details remain open for review.

## API references

These describe primitives, not qualification of a specific nxrs build. Pin
actual toolchains/dependencies when implementing the design.

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
