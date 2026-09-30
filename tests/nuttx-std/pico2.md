# Pico 2 ordinary-main build gate

This is a build/link/ABI gate, not a physical-board runtime pass. It uses the
pinned `raspberrypi-pico-2:nsh` ARM Cortex-M33 configuration and Rust's existing
`thumbv8m.main-nuttx-eabi` target. FPU and SMP are disabled; the resolved board
profile must retain 532480 bytes of RAM. The wireless-specific Pico 2 W
integration, radio and production HALs are not covered by this Pico 2 baseline.

The same handwritten main, bounded channels, TLS-destructor checks and CPU-peer
handshake used by RISC-V/native/browser qualification are compiled here. Worker
stacks are now 64 KiB on all profiles instead of the old host-sized 512 KiB;
all runtime assertions remain. The ordinary-main NuttX registration retains its
64-KiB main stack. Static linker fit is not a proof of total runtime memory fit,
stack high-water marks, interrupt behavior or timing.

## Reproduce

Install `nightly-2025-09-15` with `rust-src`, GNU `arm-none-eabi` compiler/binutils,
and the existing NuttX build prerequisites. Initialize the pinned submodules.
Then, from the repository root:

```sh
NUTTX_STD_COMPAT_FIXES=1 bash tests/nuttx-std/build.sh pico2
```

Outputs are isolated under `target/nuttx-pico2`: kernel ELF/bin, map, resolved
configuration, ARM ELF attributes, section sizes, exact link arguments, source
hashes, private SDK patches and target-compiled ABI observations. UF2 generation
is deliberately disabled for this first build gate; no download/flash/run is
automatically performed. Real hardware must run the complete report and failure
case, with clean return, before claiming board execution.

## SDK review boundary

The three scoped NuttX standard-library patches are reused with source-blob
checks, explicit opt-in and proof of Cargo's actual SDK source. The parker fix
performs dynamic mutex initialization; its applicability is still tied to the
configured native storage/alignment. The descriptor fix preserves standard-fd sanitization through the existing
fcntl fallback, but does not repair raw pollfd. The signal-startup fix supplies
the measured NuttX null ignore-handler value only inside std's SIGPIPE startup
path; raw libc SIG_IGN and general signal APIs remain unqualified.
The separate Emscripten TLS cleanup fix is not part of this target.

The 47 C/Rust ABI witnesses compile separately for RV32 or ARM, using the exact
libc/core/compiler_builtins consumed by that target's std build. They must not
reuse another architecture's table. Before final image linking, imports of
`poll` or `ppoll` from the partially linked Rust program are rejected. Native C
uses of poll are not rejected: they use the native C layout. This prevents the
known unsupported Rust poll path from silently entering these probe builds;
it is not a complete foreign-function ABI audit or a production sandbox.

At `3b4df480639ccaccc4c7c05a9732b754d91f430b`, the Pico 2 build/link/ABI
workflow passed with all 47 observations. This remains build-only evidence:
physical Pico 2 execution is still required.

No upstream approval, stock-SDK compatibility, hardware execution or production
migration follows from a green build. ESP32-S3 emulated execution is qualified
separately and does not substitute for Pico hardware execution. Exact run results
belong to the PR, rather than being inferred in advance by this document.
