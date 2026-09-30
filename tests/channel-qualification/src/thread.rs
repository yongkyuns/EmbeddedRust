mod workload;

fn main() {
    let task = std::thread::Builder::new()
        .name("cq-producer".into())
        .stack_size(workload::STACK)
        .spawn(|| {
            (0..workload::COUNT)
                .map(|n| std::hint::black_box(workload::value(n)))
                .sum::<u64>()
        })
        .unwrap_or_else(|_| panic!("spawn failed"));
    let sum = task.join().unwrap_or_else(|_| panic!("join failed"));
    assert_eq!(std::hint::black_box(sum), workload::expected());
}
