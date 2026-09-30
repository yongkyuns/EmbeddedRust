#[macro_use]
mod workload;
channel_workload!(crossbeam_channel::bounded);

fn main() {
    assert_eq!(std::hint::black_box(run()), workload::expected());
}
