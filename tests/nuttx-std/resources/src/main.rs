//! Destructive resource tests for the finite-memory NuttX qualification image.
#![forbid(unsafe_code)]

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::AsRawFd;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::sync_channel;
use std::thread;

const CHUNK: usize = 1024 * 1024;
const LIMIT: usize = 160;
const IMPOSSIBLE_STACK: usize = 256 * CHUNK;
static ENTRIES: AtomicUsize = AtomicUsize::new(0);
static OVERSIZED_STARTED: AtomicBool = AtomicBool::new(false);

fn heap_pressure() -> usize {
    // Bookkeeping lives on the stack; no logging or infallible allocation while
    // pressure is held. Valid one-MiB layouts cannot be capacity-overflow errors.
    let mut held: [Vec<u8>; LIMIT] = std::array::from_fn(|_| Vec::new());
    let mut rejected_at = None;
    for (index, slot) in held.iter_mut().enumerate() {
        if slot.try_reserve_exact(CHUNK).is_err() {
            assert!(slot.is_empty() && slot.capacity() == 0);
            rejected_at = Some(index);
            break;
        }
        slot.resize(CHUNK, 0x5a);
    }
    // Validate already allocated contents without allocating more memory.
    let intact = held.iter().all(|slot| slot.iter().all(|byte| *byte == 0x5a));
    drop(held);
    let chunks = rejected_at.expect("finite heap must reject before the test limit");
    assert!(chunks > 0 && intact);
    let mut recovered: Vec<u8> = Vec::new();
    recovered.try_reserve_exact(CHUNK).expect("allocation after releasing pressure");
    recovered.resize(CHUNK, 0xa5);
    assert!(recovered.iter().all(|byte| *byte == 0xa5));
    chunks
}

fn thread_failure() {
    // The configured target has at most 128 MiB, so this legal stack-size
    // request must fail in the OS rather than execute the closure.
    let failed = thread::Builder::new().stack_size(IMPOSSIBLE_STACK).spawn(|| {
        OVERSIZED_STARTED.store(true, Ordering::SeqCst);
    });
    match failed {
        Err(error) => assert_eq!(error.kind(), std::io::ErrorKind::OutOfMemory),
        Ok(worker) => {
            worker.join().unwrap();
            panic!("oversized stack unexpectedly admitted");
        }
    }
    assert!(!OVERSIZED_STARTED.load(Ordering::SeqCst));
    // A failed spawn must not poison subsequent channel/thread startup.
    let (tx, rx) = sync_channel(1);
    let worker = thread::Builder::new().stack_size(64 * 1024)
        .spawn(move || tx.send(42_u32).unwrap()).expect("spawn after resource rejection");
    assert_eq!(rx.recv().unwrap(), 42);
    worker.join().unwrap();
}

fn resources() {
    println!("NXRS_RESOURCE_MAIN resources");
    let counts = [heap_pressure(), heap_pressure()];
    for _ in 0..3 {
        thread_failure();
    }
    println!("NXRS_RESOURCE_REPORT {{\"heap_failures\":2,\"heap_recoveries\":2,\"held_chunks\":[{},{}],\"chunk_bytes\":{CHUNK},\"spawn_failures\":3,\"spawn_recoveries\":3,\"oversized_started\":false}}", counts[0], counts[1]);
}

fn descriptors(mask: u8) {
    assert!(mask <= 7);
    // This open must NOT steal stdin/stdout/stderr after runtime sanitization.
    let fresh = File::open("/dev/null").expect("open after Rust startup");
    let fd = fresh.as_raw_fd();
    assert!(fd >= 3, "Rust startup left a standard descriptor closed");
    if mask & 1 != 0 {
        assert_eq!(std::io::stdin().read(&mut [0_u8; 1]).unwrap(), 0);
    }
    if mask & 2 != 0 {
        std::io::stdout().write_all(b"stdout recovered\n").unwrap();
        std::io::stdout().flush().unwrap();
    }
    if mask & 4 != 0 {
        std::io::stderr().write_all(b"stderr recovered\n").unwrap();
        std::io::stderr().flush().unwrap();
    }
    drop(fresh);
    // Target-specific diagnostics only, opened AFTER testing descriptor recovery.
    let mut console = OpenOptions::new().write(true).open("/dev/console").unwrap();
    writeln!(console, "NXRS_RESOURCE_MAIN fds").unwrap();
    writeln!(console, "NXRS_FD_RUST {{\"mask\":{mask},\"fresh_fd\":{fd}}}").unwrap();
}

fn main() {
    assert_eq!(ENTRIES.fetch_add(1, Ordering::SeqCst), 0);
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("resources") if args.len() == 2 => resources(),
        Some("fds") if args.len() == 3 => descriptors(args[2].parse().unwrap()),
        _ => panic!("expected resources or fds <0..7>"),
    }
}
