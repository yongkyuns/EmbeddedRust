//! Finite raw-Crossbeam footprint workload; not a production shutdown protocol.
mod workload;

fn main() {
    let (normal_tx, normal_rx) = crossbeam_channel::bounded::<u64>(workload::CAPACITY);
    let (important_tx, important_rx) = crossbeam_channel::bounded::<u8>(4);
    let (stop_tx, stop_rx) = crossbeam_channel::bounded::<()>(1);
    // Keep originals alive: closure of a producer is not a permanently ready arm.
    let (normal, important, stop) = (normal_tx.clone(), important_tx.clone(), stop_tx.clone());
    let producer = std::thread::Builder::new()
        .name("cq-producer".into())
        .stack_size(workload::STACK)
        .spawn(move || {
            important.try_send(1).unwrap_or_else(|_| panic!("important admission failed"));
            for sequence in 0..workload::COUNT {
                // Controlled finite footprint workload; production HALs use explicit
                // nonblocking admission/overload policies, tested separately.
                normal.send(std::hint::black_box(workload::value(sequence)))
                    .unwrap_or_else(|_| panic!("send failed"));
            }
            stop.try_send(()).unwrap_or_else(|_| panic!("stop admission failed"));
        })
        .unwrap_or_else(|_| panic!("spawn failed"));
    let (mut count, mut sum, mut ready, mut stopping) = (0, 0u64, false, false);
    while count < workload::COUNT || !ready || !stopping {
        crossbeam_channel::select_biased! {
            recv(stop_rx) -> event => {
                event.unwrap_or_else(|_| panic!("stop closed"));
                stopping = true;
            },
            recv(important_rx) -> event => {
                assert_eq!(event.unwrap_or_else(|_| panic!("important closed")), 1);
                ready = true;
            },
            recv(normal_rx) -> event => {
                sum += event.unwrap_or_else(|_| panic!("normal closed"));
                count += 1;
            },
            default(std::time::Duration::from_secs(5)) => panic!("selection timeout"),
        }
    }
    producer.join().unwrap_or_else(|_| panic!("join failed"));
    assert_eq!(std::hint::black_box(sum), workload::expected());
    drop((normal_tx, important_tx, stop_tx));
}
