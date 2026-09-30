//! Shared workload, not the proposed production service API.
#![allow(dead_code, unused_macros)]
pub const COUNT: u64 = 64;
pub const CAPACITY: usize = 8;
pub const STACK: usize = 16 * 1024;

pub fn value(sequence: u64) -> u64 {
    sequence.wrapping_mul(3).wrapping_add(1)
}

pub fn expected() -> u64 {
    (0..COUNT).map(value).sum()
}

macro_rules! channel_workload {
    ($constructor:path) => {
        pub fn run() -> u64 {
            let (tx, rx) = $constructor(crate::workload::CAPACITY);
            let producer = std::thread::Builder::new()
                .name("cq-producer".into())
                .stack_size(crate::workload::STACK)
                .spawn(move || {
                    for sequence in 0..crate::workload::COUNT {
                        tx.send(std::hint::black_box(crate::workload::value(sequence)))
                            .unwrap_or_else(|_| panic!("send failed"));
                    }
                })
                .unwrap_or_else(|_| panic!("spawn failed"));
            let mut sum = 0u64;
            for _ in 0..crate::workload::COUNT {
                sum += rx.recv_timeout(std::time::Duration::from_secs(5))
                    .unwrap_or_else(|_| panic!("receive failed"));
            }
            producer.join().unwrap_or_else(|_| panic!("join failed"));
            sum
        }
    };
}
