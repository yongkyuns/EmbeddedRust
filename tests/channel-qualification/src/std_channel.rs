#[macro_use]
mod workload;
channel_workload!(std::sync::mpsc::sync_channel);

fn main() {
    assert_eq!(std::hint::black_box(run()), workload::expected());
}
