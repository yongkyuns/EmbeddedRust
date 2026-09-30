# Concurrency and event communication architecture

> **Status: design discussion.** This document is intentionally non-normative.
> It captures the current direction for nxrs concurrency and event communication,
> including open questions that should be resolved before introducing a shared
> active-object/runtime crate or refactoring existing services.

## Motivation

Nxrs should provide a consistent concurrency model without turning a vertically
integrated embedded application into a graph of independently scheduled actors.

The main concern is not whether queues or active objects are "fast enough".
The concern is choosing the correct ownership boundary in the first place.

A high-rate exchange between two software components is usually evidence that
they belong to the same execution/ownership domain. Splitting them across a
message boundary adds scheduling, queueing, copies, overload policy and latency
without necessarily adding useful isolation.

The proposed direction is therefore:

> **Messages are for coordination, not routine data flow.**

and:

> **An active ownership boundary should exist because independent execution,
> resource ownership, isolation or lifecycle is useful—not merely because two
> pieces of code are separate modules.**

This differs from a conventional actor/pub-sub architecture where normal data
flow is routinely expressed as messages between many independently scheduled
entities.

## Two planes

Nxrs should distinguish a **control/event plane** from a **data plane**.

~~~text
                control / important events
            +------------------------------->
            |
+-----------+--------------------------------------------------+
|                    active ownership domain                   |
|                                                              |
|  device/HAL -> processing -> estimation -> local consumers   |
|                  direct calls / borrowed data                |
|                  bounded shared buffers                      |
|                                                              |
+--------------------------------------------------------------+
                       data plane
~~~

### Control/event plane

Messages are appropriate for semantically important, relatively sparse events:

- start, stop and shutdown;
- mode/configuration changes;
- calibration requests and completion;
- fault and recovery notification;
- lifecycle transitions;
- health/status changes;
- explicit commands from another independently scheduled owner.

These messages should be bounded, typed and easy to reason about.

### Data plane

Normal high-rate work should normally remain inside one ownership domain:

- IMU samples feeding a navigation filter;
- GNSS updates feeding the same navigation filter;
- camera frames feeding tightly coupled vision processing;
- intermediate algorithm state;
- monitoring/recording that is naturally part of the same processing cadence.

Inside one owner these are ordinary Rust calls and references, not messages.

For example:

~~~rust,ignore
let sample = imu.read()?;
navigation.update_imu(&sample);

if let Some(fix) = gnss.try_read()? {
    navigation.update_gnss(&fix);
}
~~~

There is no benefit in inserting an inbox between these stages merely because
they are separate modules.

## Active ownership domain

An **active ownership domain** is one independently scheduled owner of mutable
state and the resources that belong with that state.

One owner may contain many reusable modules:

~~~text
+---------------------- Navigation owner ----------------------+
|                                                              |
|  IMU HAL                                                     |
|      \                                                       |
|       +--> preprocessing --> fusion core --> local outputs    |
|      /                                                       |
|  GNSS HAL                                                    |
|                                                              |
|  calibration / health / recording as appropriate             |
|                                                              |
+--------------------------------------------------------------+
~~~

"Active object" is useful terminology for this ownership discipline, but nxrs
does not need to reproduce a full actor framework or the complete Quantum Leaps
programming model.

In particular:

- one module does **not** imply one active object;
- one service does **not** imply one thread;
- one hardware capability does **not** imply one active object;
- one active object may own several services/modules/capabilities;
- synchronous modules remain ordinary Rust.

The useful invariant is that one owner serializes mutation of its private state.

## When to introduce another active owner

A separate active ownership domain should have a concrete reason. Examples
include:

- independent scheduling priority or timing requirements;
- isolation from a long or unpredictable blocking operation;
- exclusive ownership of a resource with an independent lifecycle;
- fault/restart isolation;
- unavoidable asynchronous external I/O;
- producer/consumer decoupling where bounded buffering has real value;
- CPU isolation for expensive work.

The following are usually reasons **not** to split the ownership domain:

- the two components exchange data on every normal processing cycle;
- the consumer is part of the producer's core algorithm;
- the only reason is source-code modularity;
- the split requires large/high-rate messages just to reconstruct local state;
- the two components must remain tightly synchronized anyway.

A useful review question is:

> **If A sends B a message every time A performs normal work, should A and B
> actually share an owner?**

The answer is not always yes, but the split should be justified explicitly.

## Typed messages

At an actual active boundary, public message contracts should be ordinary,
service/domain-specific Rust enums.

For example:

~~~rust,ignore
pub enum NavigationCommand {
    Start,
    Stop,
    SetMode(Mode),
    BeginCalibration,
    ResetFault,
}

pub enum NavigationEvent {
    Ready,
    Stopped,
    CalibrationComplete(CalibrationResult),
    GnssLost,
    GnssRecovered,
    Fault(FaultCode),
}
~~~

The enums are the semantic interface. They do not imply a global event bus,
runtime type registry or serialization framework.

The expected properties are:

- payloads are bounded;
- payloads are small enough to copy cheaply when copying is required;
- event meaning is explicit in the type system;
- each active boundary owns its own command/event vocabulary;
- there is no system-wide "all events" enum.

A service may expose both an inbound command enum and an outbound event enum,
but the outbound side is **not a streaming output interface**. If a value is
produced at 100 Hz simply because the algorithm runs at 100 Hz, that value is
normally data-plane traffic, not an event.

The transport representation does not have to be identical to the Rust enum's
in-memory representation. A POSIX-message-queue backend, for example, may encode
a bounded enum into an explicit fixed representation rather than copying an
arbitrary Rust enum layout verbatim.

## Bulk and high-rate data

Large buffers should not be copied through control/event queues.

Where high-rate data genuinely crosses an execution boundary, use an explicit
bounded data-plane mechanism such as:

- a fixed-capacity SPSC ring;
- a preallocated buffer pool;
- a DMA buffer set;
- a bounded shared-memory region with explicit ownership transfer.

For example:

~~~text
 producer owner                         consumer owner
      |                                      |
      | fill slot                            |
      v                                      |
 +---------------- bounded buffer pool ----------------+
      |                                      ^
      +---------- transfer ownership --------+
~~~

"Shared memory" here does **not** mean uncontrolled shared mutable state.
The preferred model is explicit ownership of a slot/lease:

~~~text
free -> producer owns -> published/consumer owns -> free
~~~

If multiple consumers genuinely need the same large payload, immutable shared
leases or another explicit lifetime scheme may be appropriate. That should be a
data-plane design decision, not a feature of the generic event system.

A readiness notification may still cross the control/wakeup path, but it should
not turn the payload itself into a conventional message.

## One logical wait point

An active owner should normally have one logical blocking/wait point for all work
that can wake that owner.

On NuttX, a useful candidate is a `poll()`-based owner loop that waits on:

- a bounded control/message queue;
- device descriptors that support readiness notification;
- transport/socket descriptors;
- a timeout representing the next internal deadline.

Conceptually:

~~~text
                         +--> control MQ
                         |
Navigation owner --> poll+--> IMU fd
                         |
                         +--> GNSS fd
                         |
                         +--> transport fd
                         |
                         +--> next deadline
~~~

and:

~~~rust,ignore
loop {
    let ready = wait(...)?;

    if ready.control() {
        handle_command();
    }

    if ready.imu() {
        let sample = imu.read()?;
        navigation.update_imu(&sample);
    }

    if ready.gnss() {
        let fix = gnss.read()?;
        navigation.update_gnss(&fix);
    }

    if deadline_due() {
        navigation.on_deadline();
    }
}
~~~

This retains the active-owner properties we care about:

- one owner of mutable state;
- one serialized dispatch context;
- blocking while idle;
- no separate thread merely to forward every device sample through another
  queue.

NuttX currently provides poll support for its message-queue file objects, so a
POSIX-MQ + poll implementation is a plausible NuttX backend. That is a backend
capability, not a portable semantic requirement: other targets may require a
different wake/wait mechanism.

The portable architecture should specify **one logical wait point**, not require
that every wake source physically be converted into the same queue.

## Fairness and bounded work

A single wait set does not automatically provide fair service.

The owner loop must avoid spending an unbounded amount of time draining one
source while starving:

- commands;
- another ready device;
- an already-due deadline;
- shutdown.

A shared execution helper may therefore define bounded drain/fairness rules such
as:

1. observe due deadlines before blocking again;
2. process only a bounded batch from a perpetually ready source;
3. return to the dispatch point so other readiness is reconsidered;
4. make overload/overrun visible rather than silently growing work.

The exact policy is still open and should be validated with real nxrs workloads.

## Queueing and overload

Control/event queues should always be bounded.

Because events are intended to be sparse and important, persistent queue
saturation is different from a high-rate telemetry backlog: it usually means the
owner is stalled, badly sized or receiving an inappropriate class of traffic.

The transport should distinguish at least:

- accepted;
- full;
- closed/disconnected.

The policy for a full queue remains message-specific. A stale informational
notification may be coalesced or dropped; a shutdown/configuration command may
need reliable admission from top-level lifecycle code.

An active owner should not synchronously block waiting for another active owner
to process a command/reply during normal dispatch. That recreates wait-for
cycles and undermines the isolation that the ownership boundary was intended to
provide.

## Candidate nxrs active-object crate

A small reusable crate is still attractive, but its purpose should be narrower
than a general actor system.

Tentative name: `nxrs-ao` (name not decided).

Possible responsibilities:

- standardize active-owner lifecycle;
- provide bounded typed control/event endpoints;
- start/join a dedicated owner thread where that execution model is selected;
- provide a common dispatch/wait contract;
- integrate deadlines and fairness;
- make queue-full/closed outcomes explicit;
- provide test support for deterministic/manual dispatch where practical;
- allow target-specific wait backends such as NuttX `poll()`.

Explicit non-responsibilities:

- no global event bus;
- no generic publish/subscribe graph;
- no dynamic actor/service discovery;
- no mandatory state-machine framework;
- no async executor;
- no automatic "one service = one thread" rule;
- no high-rate sample/frame transport;
- no implicit large-buffer copying;
- no universal HAL/device registry.

The crate should reduce repeated concurrency/lifecycle code. It should not force
a component that already has a natural synchronous data path to become an actor.

## Relationship to POSIX MQ and poll

The active-object idea and POSIX primitives are not competing architecture
choices.

The active-object layer defines:

~~~text
ownership + lifecycle + serialization + messaging semantics
~~~

A NuttX backend may implement the relevant mechanisms with:

~~~text
POSIX MQ + poll + device fds + timer/deadline
~~~

A native host backend may use the same approach where practical or use a typed
in-process queue plus an appropriate wake mechanism.

A browser backend may require a different adaptation.

Portable service/domain code should not depend on which backend provides the
wake mechanism.

This is preferable to hiding useful OS functionality behind a queue-only model
that requires extra forwarding threads for already-pollable I/O.

## Example: navigation

A target navigation design would more likely look like:

~~~text
                         sparse commands/events
                     <--------------------------->
                               application
                                    |
                                    v
+------------------------- Navigation owner -------------------------+
|                                                                    |
|                    one wait/dispatch context                       |
|                                                                    |
|  IMU readiness --> read --> preprocess ---+                        |
|                                           |                        |
|                                           +--> fusion/update       |
|                                           |                        |
|  GNSS readiness -> read --> normalize ----+                        |
|                                                    |               |
|                                           local consumers          |
|                                           health/recording         |
|                                                                    |
+--------------------------------------------------------------------+
~~~

rather than:

~~~text
IMU actor -- every sample --> Fusion actor <-- every fix -- GNSS actor
~~~

The second shape remains valid when there is an actual scheduling/isolation
reason for those owners, but it should not be the default decomposition.

## Example: camera / large buffers

A camera/vision path may remain one owner when processing is tightly coupled:

~~~text
camera -> frame buffer -> vision
          same owner
~~~

If vision processing requires an independent CPU/scheduling boundary:

~~~text
camera owner --> bounded frame pool/ring --> vision owner
                     bulk data
~~~

The cross-owner control path can still carry sparse events such as:

~~~rust,ignore
VisionEvent::Started
VisionEvent::TrackingLost
VisionEvent::Fault(...)
VisionEvent::Stopped
~~~

The existence of the separate owner does not mean every frame becomes an
`Event::Frame(...)`.

## Relationship to the current event demo

The existing `app/event-demo` is useful qualification evidence for:

- Rust std threads on selected targets;
- bounded channels;
- service-owned HAL acquisition;
- lifecycle and join behavior;
- multi-instance composition.

It currently models IMU, GNSS and Fusion as separate active services and sends
sensor data through bounded channels.

That topology should be treated as an **execution/portability demonstration**,
not as the target nxrs product decomposition.

In particular, it should not establish the general rule that high-rate sensor
samples must cross active-service message queues.

The current `service/event` crate is likewise useful implementation evidence,
but the design of a future shared active-owner crate should be driven by the
coarser ownership model described here rather than by preserving the demo's
queue topology.

No implementation change is proposed by this document.

## Open questions

The following need explicit discussion before implementation:

1. **Crate boundary/name**  
   Should this become `nxrs-ao`, `nxrs-active`, or remain a small execution
   helper under `service/`?

2. **Production control transport**  
   On NuttX, should typed command/event endpoints use POSIX message queues,
   an in-process Rust queue with a pollable wake source, or both?

3. **Typed enum encoding over POSIX MQ**  
   If POSIX MQ is used, should each boundary provide a small explicit codec,
   generated fixed layout, or a common derive/helper? Raw Rust enum memory
   should not become the wire/storage contract accidentally.

4. **Wait-set abstraction**  
   What is the smallest portable interface that supports NuttX/native
   descriptor readiness without imposing that model on browsers?

5. **HAL readiness contract**  
   Should a device-facing HAL expose a pollable descriptor/readiness token, or
   should poll integration remain entirely within a target/provider adapter?

6. **Outbound event connection**  
   Should an owner receive one injected event sink, several explicit sinks, or
   another narrow composition mechanism? Avoid turning this into generic pub/sub.

7. **Deadlines and fairness**  
   What batching/starvation rules should the shared owner loop guarantee?

8. **Priorities and stack sizes**  
   Which owner-thread attributes belong in portable configuration versus
   NuttX-specific deployment configuration?

9. **Bulk-buffer ownership**  
   Is one small generic bounded lease-pool abstraction worthwhile, or should
   camera/storage/etc. keep specialized pools until repeated requirements are
   demonstrated?

10. **ISR/device completion path**  
    What is the preferred path from interrupt/callback completion into the owner
    wait set without introducing a forwarding thread for every device?

11. **Migration of current navigation demo**  
    Should event-demo remain intentionally actor-like as a stress/qualification
    fixture, or later gain a second example demonstrating the coarse ownership
    model?

## Proposed review rules

Until the open questions are resolved, new designs can use these review
heuristics:

1. Do not introduce an active boundary solely for code organization.
2. Treat repeated/high-rate message exchange as a prompt to reconsider the
   boundary.
3. Keep tightly coupled algorithms in one owner and use direct Rust calls.
4. Use bounded shared buffers/rings for genuine cross-owner bulk data.
5. Use typed messages for sparse commands and important semantic events.
6. Keep every queue and data buffer explicitly bounded.
7. Prefer one logical wait point per active owner.
8. Reuse OS readiness mechanisms instead of adding forwarding threads without a
   concrete reason.
9. Require an explicit scheduling/isolation/lifecycle justification for every
   additional active owner.
10. Measure the real end-to-end cost before claiming that a particular queue or
    wait backend is faster or more deterministic.

The intended end state is a small number of meaningful execution owners with
clear resource ownership—not a fine-grained actor graph.
