//! Shared device error values, without providers, OS types or runtime policy.
#![no_std]
#![forbid(unsafe_code)]

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DeviceError {
    Unsupported,
    Busy,
    Timeout,
    Full,
    Io,
    InvalidData,
}
