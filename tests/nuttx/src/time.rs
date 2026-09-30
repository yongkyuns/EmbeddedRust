//! Time compatibility kept local to the core-only NuttX simulator fixture.
use core::ffi::c_int;

extern "C" {
    fn rc_test_now_ms(value: *mut u64) -> c_int;
    fn rc_test_sleep_ms(milliseconds: u32) -> c_int;
}

pub fn now_ms() -> u64 {
    let mut value = 0;
    // SAFETY: valid exclusive scalar output; the fixture retains no pointer.
    assert_eq!(unsafe { rc_test_now_ms(&mut value) }, 0, "NuttX test clock failed");
    value
}

pub fn sleep_ms(milliseconds: u64) {
    let milliseconds = u32::try_from(milliseconds).expect("sleep duration overflow");
    // SAFETY: scalar-only synchronous fixture helper.
    assert_eq!(unsafe { rc_test_sleep_ms(milliseconds) }, 0, "NuttX test sleep failed");
}
