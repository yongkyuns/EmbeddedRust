//! Portable nxrs product policy and composition; no OS or device construction.
#![no_std]
#![forbid(unsafe_code)]

mod reader;
pub mod recorder;
pub mod monitor;
pub mod product;

pub use recorder::Recorder;
pub use monitor::Monitor;
pub use product::{CameraProduct, ConsumerReport, ShutdownReport, TickReport};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum AppState {
    #[default]
    Stopped,
    Running,
    Stopping,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct AppStats { pub processed: u64, pub skipped: u64 }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Progress { Idle, Processed { sequence: u64, skipped: u64 } }
