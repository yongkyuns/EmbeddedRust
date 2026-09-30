// SPDX-License-Identifier: MIT
// Benchmark-only C shim. No guessed opaque POSIX layouts in Rust and no cc crate.
use std::{env, fs, path::PathBuf, process::Command};
fn checked(c: &mut Command) {
    assert!(c.status().expect("start C tool").success(), "failed: {c:?}");
}
fn main() {
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("../../..");
    let source = root.join("tests/rtos-bench/posix.c");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let target = env::var("TARGET").unwrap();
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    let mut flags: Vec<String> = [
        "-std=c11",
        "-O2",
        "-fno-lto",
        "-ffunction-sections",
        "-fdata-sections",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    let prefix;
    if os == "nuttx" {
        let sysroot = PathBuf::from(
            env::var_os("NUTTX_STD_SYSROOT").expect("use the qualified NuttX builder"),
        );
        let nuttx = sysroot.parent().unwrap().join("nuttx");
        let arch_flags: &[&str];
        if target == "thumbv8m.main-nuttx-eabi" {
            prefix = "arm-none-eabi-";
            arch_flags = &["-mcpu=cortex-m33", "-mthumb", "-mfloat-abi=soft"];
        } else if target == "xtensa-esp32s3-nuttx" {
            prefix = "xtensa-esp32s3-elf-";
            arch_flags = &["-mlongcalls", "-mtext-section-literals"];
        } else {
            panic!("unsupported benchmark target: {target}");
        }
        // The normal std build has resolved Kconfig but has not built C yet.
        let app_command =
            env::var("NXRS_APP_COMMAND").unwrap_or_else(|_| "rt_bench".to_owned());
        let app_priority =
            env::var("NXRS_APP_PRIORITY").unwrap_or_else(|_| "100".to_owned());
        let app_stack =
            env::var("NXRS_APP_STACKSIZE").unwrap_or_else(|_| "65536".to_owned());
        checked(
            Command::new("make")
                .arg("-C")
                .arg(&nuttx)
                .arg("context")
                .arg(format!("CROSSDEV={prefix}"))
                .arg(format!("NXRS_APP_COMMAND={app_command}"))
                .arg(format!("NXRS_APP_PRIORITY={app_priority}"))
                .arg(format!("NXRS_APP_STACKSIZE={app_stack}")),
        );
        flags.extend(arch_flags.iter().map(|s| (*s).to_owned()));
        flags.push("-D__NuttX__".into());
        flags.push("-isystem".into());
        flags.push(nuttx.join("include").display().to_string());
        println!("cargo:rerun-if-changed={}", nuttx.join(".config").display());
    } else {
        assert!(
            os == "linux" && env::var("HOST").unwrap() == target,
            "initial POSIX benchmark host is native Linux (not a browser/macOS mqueue emulation)"
        );
        prefix = "";
        flags.push("-pthread".into());
        println!("cargo:rustc-link-lib=rt");
    }
    let compiler = format!("{prefix}gcc");
    let mut c = Command::new(&compiler);
    c.args(&flags)
        .arg("-c")
        .arg(&source)
        .arg("-o")
        .arg(out.join("posix.o"));
    let version = Command::new(&compiler)
        .arg("--version")
        .output()
        .expect("C version");
    fs::write(
        out.join("cc-command.txt"),
        format!("{c:?}\n{}", String::from_utf8_lossy(&version.stdout)),
    )
    .unwrap();
    checked(&mut c);
    checked(
        Command::new(format!("{prefix}ar"))
            .arg("crs")
            .arg(out.join("librtbench.a"))
            .arg(out.join("posix.o")),
    );
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=rtbench");
    println!("cargo:rerun-if-changed={}", source.display());
    println!(
        "cargo:rerun-if-changed={}",
        source.with_file_name("posix.h").display()
    );
    println!("cargo:rerun-if-env-changed=NUTTX_STD_SYSROOT");
    println!("cargo:rerun-if-env-changed=NXRS_APP_COMMAND");
    println!("cargo:rerun-if-env-changed=NXRS_APP_PRIORITY");
    println!("cargo:rerun-if-env-changed=NXRS_APP_STACKSIZE");
}
