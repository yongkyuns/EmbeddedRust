//! Portable reusable services. OS implementations enter only through HAL contracts.
#![no_std]
#![forbid(unsafe_code)]

pub mod camera;
pub mod recording;
pub mod telemetry;

pub use camera::{CameraService, CameraState, CaptureProgress, Frames};
pub use recording::{RecordingService, Recordings};
pub use telemetry::{payload_checksum, Telemetry, TelemetryService, SUMMARY_BYTES};
use nxrs_camera_api::DeviceError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Device(DeviceError),
    InvalidCapacity,
    InvalidFormat,
    InvalidFrame,
    ClockWentBackwards,
    AlreadyRunning,
    NotRunning,
    SequenceExhausted,
}

impl From<DeviceError> for Error {
    fn from(value: DeviceError) -> Self { Self::Device(value) }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SinkStats { pub accepted: u64, pub errors: u64 }
