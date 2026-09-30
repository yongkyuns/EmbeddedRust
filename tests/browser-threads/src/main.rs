//! The same ordinary std program runs natively and in pthread-enabled WASM.
#![forbid(unsafe_code)]

use std::cell::Cell;
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{sync_channel, RecvTimeoutError, TrySendError};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

static ENTRIES: AtomicUsize = AtomicUsize::new(0);
thread_local! { static LOCAL: Cell<u64> = const { Cell::new(0) }; }
const ROUNDS: u64 = 4;
const MESSAGES: u64 = 256;
static TLS_DROPS: AtomicUsize = AtomicUsize::new(0);
static TLS_MASK: AtomicUsize = AtomicUsize::new(0);
static PEER_STEPS: AtomicUsize = AtomicUsize::new(0);

struct Cleanup(Cell<usize>);

impl Drop for Cleanup {
    fn drop(&mut self) {
        let tag = self.0.get();
        assert!((1..=8).contains(&tag));
        let bit = 1 << (tag - 1);
        assert_eq!(TLS_MASK.fetch_or(bit, Ordering::SeqCst) & bit, 0);
        TLS_DROPS.fetch_add(1, Ordering::SeqCst);
    }
}

thread_local! { static CLEANUP: Cleanup = const { Cleanup(Cell::new(0)) }; }

fn main() {
    assert_eq!(ENTRIES.fetch_add(1, Ordering::SeqCst), 0);
    let mode = std::env::args().nth(1).unwrap_or_else(|| "pass".into());
    assert!(mode == "pass" || mode == "fail");
    println!("RUSTCAM_MAIN_ENTERED");
    if mode == "fail" {
        eprintln!("RUSTCAM_INJECTED_FAILURE");
        std::process::exit(7);
    }

    // UI heartbeat must continue DURING this CPU work, not just during startup.
    println!("RUSTCAM_CPU_BEGIN");
    let start = Instant::now();
    let mut work = 0u64;
    while start.elapsed() < Duration::from_millis(400) {
        work = black_box(work.wrapping_add(1));
    }
    assert!(work > 0);
    println!("RUSTCAM_CPU_END");

    LOCAL.set(99);
    let main_id = thread::current().id();
    let mut checksum = 0u64;
    for round in 0..ROUNDS {
        let mut owners = Vec::new();
        let progress = Arc::new([AtomicUsize::new(0), AtomicUsize::new(0)]);
        for factor in 1..=2u64 {
            let (tx, rx) = sync_channel::<u64>(2);
            let (gate_tx, gate_rx) = sync_channel::<()>(0);
            let (ready_tx, ready_rx) = sync_channel(0);
            let progress = Arc::clone(&progress);
            let worker = thread::Builder::new()
                .name(format!("probe-{round}-{factor}"))
                .stack_size(64 * 1024)
                .spawn(move || {
                    assert_eq!(LOCAL.get(), 0);
                    LOCAL.set(factor);
                    CLEANUP.with(|cleanup| cleanup.0.set((round * 2 + factor) as usize));
                    ready_tx.send(thread::current().id()).unwrap();
                    gate_rx.recv().unwrap();
                    // No sleep, yield, I/O, clock read or blocking call inside
                    // this handshake. With one QEMU CPU, progress requires
                    // preemption; browser/native success alone cannot prove it.
                    let own = (factor - 1) as usize;
                    for step in 1..=8 {
                        progress[own].store(step, Ordering::Release);
                        while progress[1 - own].load(Ordering::Acquire) < step {
                            std::hint::spin_loop();
                        }
                        PEER_STEPS.fetch_add(1, Ordering::Relaxed);
                    }
                    let mut next = 1;
                    let mut sum = 0;
                    // Blocking receive, FIFO validation, and disconnect exit.
                    for value in rx {
                        assert_eq!(value, next);
                        assert_eq!(LOCAL.get(), factor);
                        sum += value * factor;
                        next += 1;
                    }
                    assert_eq!(next, MESSAGES + 1);
                    sum
                })
                .expect("std thread creation");
            let worker_id = ready_rx.recv_timeout(Duration::from_secs(10)).unwrap();
            assert_ne!(worker_id, main_id);
            // Worker cannot drain rx until gate release: no sleep-based race.
            tx.send(1).unwrap();
            tx.send(2).unwrap();
            assert!(matches!(tx.try_send(3), Err(TrySendError::Full(3))));
            owners.push((tx, gate_tx, worker, worker_id));
        }
        assert_ne!(owners[0].3, owners[1].3);
        for (_, gate, _, _) in &owners {
            gate.send(()).unwrap();
        }
        for value in 3..=MESSAGES {
            for (tx, _, _, _) in &owners {
                tx.send(value).unwrap();
            }
        }
        for (tx, gate, worker, _) in owners {
            drop(tx);
            drop(gate);
            checksum += worker.join().expect("worker completed without panic");
        }
        assert_eq!(LOCAL.get(), 99);
        // join must include thread-local destructors, not just the closure.
        let ended = ((round + 1) * 2) as usize;
        assert_eq!(TLS_DROPS.load(Ordering::SeqCst), ended);
        assert_eq!(TLS_MASK.load(Ordering::SeqCst), (1 << ended) - 1);
        assert_eq!(PEER_STEPS.load(Ordering::SeqCst), ended * 8);
    }
    assert_eq!(checksum, ROUNDS * 3 * MESSAGES * (MESSAGES + 1) / 2);
    let (tx, rx) = sync_channel::<u8>(1);
    assert_eq!(
        rx.recv_timeout(Duration::from_millis(20)),
        Err(RecvTimeoutError::Timeout)
    );
    drop(tx);
    assert_eq!(
        rx.recv_timeout(Duration::from_secs(1)),
        Err(RecvTimeoutError::Disconnected)
    );
    let tls_drops = TLS_DROPS.load(Ordering::SeqCst);
    let cpu_peer_steps = PEER_STEPS.load(Ordering::SeqCst);
    assert_eq!((tls_drops, cpu_peer_steps), (8, 64));
    println!(
        "RUSTCAM_THREAD_REPORT {{\"main_entries\":1,\"rounds\":{ROUNDS},\"joined_workers\":8,\"messages\":2048,\"checksum\":{checksum},\"backpressure_checks\":8,\"tls_isolation\":true,\"timeout\":true,\"disconnect\":true,\"tls_drops\":{tls_drops},\"cpu_peer_steps\":{cpu_peer_steps}}}"
    );
}
