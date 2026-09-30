//! Transport capability facade. Concrete provider selection stays inside this HAL.
#![no_std]
#![forbid(unsafe_code)]

pub use nxrs_transport_api::{DeviceError, PacketSink, Transport};

#[cfg(any(
    all(feature = "mock", feature = "native"),
    all(feature = "mock", feature = "nuttx"),
    all(feature = "native", feature = "nuttx"),
))]
compile_error!("select at most one nxrs-transport provider feature");

#[cfg(feature = "native")]
pub use nxrs_transport_native::transport as open;

#[cfg(feature = "nuttx")]
pub fn open(address: [u8; 4], port: u16) -> Result<impl Transport, DeviceError> {
    nxrs_transport_nuttx::UdpSender::connect(address, port)
}

#[cfg(feature = "mock")]
pub fn open() -> impl Transport {
    nxrs_transport_mock::MockTransport::default()
}
