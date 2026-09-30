//! Allocator-only probe. Never link this instrumentation into size/timing images.
use nxrs_allocation_probe::{Snapshot, Tracking};
use std::alloc::System;
use std::time::Duration;

#[global_allocator]
static ALLOCATOR: Tracking<System> = Tracking::new(System);
const CAPACITY: usize = 8;

type Rejected = Result<(), u64>;
trait Probe: Sized {
    fn new() -> Self;
    fn post(&self, value: u64) -> Rejected;
    fn wait(&self, timeout: Duration) -> Option<u64>;
}

struct Standard(std::sync::mpsc::SyncSender<u64>, std::sync::mpsc::Receiver<u64>);
impl Probe for Standard {
    fn new() -> Self {
        let (tx, rx) = std::sync::mpsc::sync_channel(CAPACITY);
        Self(tx, rx)
    }
    fn post(&self, value: u64) -> Rejected {
        match self.0.try_send(value) {
            Ok(()) => Ok(()),
            Err(std::sync::mpsc::TrySendError::Full(value)) => Err(value),
            Err(_) => panic!("unexpected disconnection"),
        }
    }
    fn wait(&self, timeout: Duration) -> Option<u64> {
        match self.1.recv_timeout(timeout) {
            Ok(value) => Some(value),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => None,
            Err(_) => panic!("unexpected disconnection"),
        }
    }
}

struct Crossbeam(crossbeam_channel::Sender<u64>, crossbeam_channel::Receiver<u64>);
impl Probe for Crossbeam {
    fn new() -> Self {
        let (tx, rx) = crossbeam_channel::bounded(CAPACITY);
        Self(tx, rx)
    }
    fn post(&self, value: u64) -> Rejected {
        match self.0.try_send(value) {
            Ok(()) => Ok(()),
            Err(crossbeam_channel::TrySendError::Full(value)) => Err(value),
            Err(_) => panic!("unexpected disconnection"),
        }
    }
    fn wait(&self, timeout: Duration) -> Option<u64> {
        match self.1.recv_timeout(timeout) {
            Ok(value) => Some(value),
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => None,
            Err(_) => panic!("unexpected disconnection"),
        }
    }
}

struct Selection {
    normal: Crossbeam,
    _important_tx: crossbeam_channel::Sender<u64>,
    important: crossbeam_channel::Receiver<u64>,
    _stop_tx: crossbeam_channel::Sender<u64>,
    stop: crossbeam_channel::Receiver<u64>,
}
impl Probe for Selection {
    fn new() -> Self {
        let (important_tx, important) = crossbeam_channel::bounded(4);
        let (stop_tx, stop) = crossbeam_channel::bounded(1);
        Self { normal: Crossbeam::new(), _important_tx: important_tx, important, _stop_tx: stop_tx, stop }
    }
    fn post(&self, value: u64) -> Rejected { self.normal.post(value) }
    fn wait(&self, timeout: Duration) -> Option<u64> {
        crossbeam_channel::select_biased! {
            recv(self.stop) -> value => Some(value.expect("stop disconnected")),
            recv(self.important) -> value => Some(value.expect("important disconnected")),
            recv(self.normal.1) -> value => Some(value.expect("normal disconnected")),
            default(timeout) => None,
        }
    }
}

fn measure<P: Probe>() -> [Snapshot; 7] {
    let mut marks = [Snapshot::default(); 7];
    marks[0] = ALLOCATOR.snapshot();
    let queue = P::new();
    marks[1] = ALLOCATOR.snapshot();
    // Fresh OS thread for this case. No earlier receive/selection can warm its TLS.
    assert_eq!(queue.wait(Duration::from_millis(20)), None);
    marks[2] = ALLOCATOR.snapshot();
    for _ in 0..64 {
        assert_eq!(queue.wait(Duration::from_millis(1)), None);
    }
    marks[3] = ALLOCATOR.snapshot();
    for value in 0..2048 {
        queue.post(value).expect("empty bounded queue");
        assert_eq!(queue.wait(Duration::ZERO), Some(value));
    }
    marks[4] = ALLOCATOR.snapshot();
    for value in 0..CAPACITY as u64 {
        queue.post(value).expect("capacity available");
    }
    assert_eq!(queue.post(999), Err(999));
    for value in 0..CAPACITY as u64 {
        assert_eq!(queue.wait(Duration::ZERO), Some(value));
    }
    marks[5] = ALLOCATOR.snapshot();
    drop(queue);
    marks[6] = ALLOCATOR.snapshot();
    marks
}

fn main() {
    let case = std::env::args().nth(1).expect("std, crossbeam or select");
    assert!(matches!(case.as_str(), "std" | "crossbeam" | "select"));
    println!("MEMORY_BEGIN scope=rust-global-allocator timing=not-a-benchmark");
    let chosen = case.clone();
    let before_thread = ALLOCATOR.snapshot();
    let task = std::thread::Builder::new().name("cq-memory-owner".into()).spawn(move || {
        match chosen.as_str() {
            "std" => measure::<Standard>(),
            "crossbeam" => measure::<Crossbeam>(),
            "select" => measure::<Selection>(),
            _ => unreachable!(),
        }
    }).expect("spawn failed");
    let marks = task.join().expect("probe panicked");
    let after_thread = ALLOCATOR.snapshot();
    let phases = ["construction", "first-blocking-timeout", "steady-timeouts", "steady-ready", "overload", "channel-drop"];
    // All printing happens after ALL windows and after worker termination.
    for (index, phase) in phases.iter().enumerate() {
        marks[index + 1].report(marks[index], "channels", &case, phase);
    }
    after_thread.report(before_thread, "channels", &case, "thread-lifetime");
    // Preserve phase results before enforcing the initial no-allocator-call gates.
    for index in [2, 3, 4] {
        marks[index + 1].no_allocator_calls_since(marks[index])
            .expect("allocator activity in a qualified steady-state probe window");
    }
    // TLS/context can remain live until thread exit; channel-drop alone is not
    // incorrectly required to restore the pre-construction baseline.
    println!("CHANNEL_MEMORY_PASS case={case} scope=timeout-ready-overload-only");
}
