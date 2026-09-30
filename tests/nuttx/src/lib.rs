//! Core-only compatibility entry for the NuttX ARCH_SIM oracle.
//! ESP32-S3 integration uses src/main.rs with ordinary Rust std.
#![no_std]
#![deny(unsafe_op_in_unsafe_fn)]

mod app;
mod qualification;
mod transport;
mod time;

use core::ffi::{c_char, CStr};
use time::{now_ms, sleep_ms};

extern "C" {
    fn rc_sim_panic(file: *const u8, length: usize, line: u32) -> !;
}

#[panic_handler]
fn panic(info: &core::panic::PanicInfo<'_>) -> ! {
    let (file, line) = info.location().map_or(("unknown", 0), |p| (p.file(), p.line()));
    // SAFETY: file remains alive through this nonreturning diagnostic call.
    unsafe { rc_sim_panic(file.as_ptr(), file.len(), line) }
}

/// # Safety
/// output must point to a live nul-terminated path for this complete call.
#[no_mangle]
pub unsafe extern "C" fn rc_rust_run(output: *const c_char, port: u16) -> i32 {
    // SAFETY: guaranteed by the C fixture; borrowed only for this invocation.
    let output = unsafe { CStr::from_ptr(output) };
    let transport =
        transport::UdpSender::connect([127, 0, 0, 1], port).expect("NuttX UDP connect");
    app::run(output, transport, now_ms, sleep_ms)
}
