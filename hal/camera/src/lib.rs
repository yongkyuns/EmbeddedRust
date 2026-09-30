//! Camera capability facade. Concrete provider selection stays inside this HAL.
#![no_std]
#![forbid(unsafe_code)]

pub use nxrs_camera_api::{Camera, Capture, DeviceError, Format, Frame, PixelFormat};

#[cfg(any(
    all(feature = "mock", feature = "native"),
    all(feature = "mock", feature = "nuttx"),
    all(feature = "native", feature = "nuttx"),
))]
compile_error!("select at most one nxrs-camera provider feature");

#[cfg(feature = "native")]
pub use nxrs_camera_native::camera as open;

#[cfg(feature = "nuttx")]
pub fn open(path: &core::ffi::CStr) -> impl Camera + '_ {
    nxrs_camera_nuttx::DeviceCamera::new(path)
}

#[cfg(feature = "mock")]
pub fn open(actions: impl IntoIterator<Item = nxrs_camera_mock::CameraAction>) -> impl Camera {
    nxrs_camera_mock::MockCamera::new(actions)
}
