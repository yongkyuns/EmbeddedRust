#[macro_use]
mod workload;

mod standard {
    channel_workload!(std::sync::mpsc::sync_channel);
}
mod crossbeam {
    channel_workload!(crossbeam_channel::bounded);
}

fn main() {
    assert_eq!(std::hint::black_box(standard::run()), workload::expected());
    assert_eq!(std::hint::black_box(crossbeam::run()), workload::expected());
}
