//! Minimal C-ABI Rust entry. The footprint driver must verify no std symbols.
#![no_std]
#![no_main]

// Native diagnostic uses the same system CRT/libc as the minimal C executable.
// NuttX supplies the final C runtime when linking its complete firmware image.
#[cfg(not(target_os = "nuttx"))]
#[link(name = "c")]
extern "C" {}

#[no_mangle]
pub extern "C" fn main(_argc: i32, _argv: *const *const u8) -> i32 {
    0
}

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo<'_>) -> ! {
    loop {
        core::hint::spin_loop();
    }
}
