# Build and configuration model

Cargo is the canonical developer-facing build interface. NuttX still owns the OS
configuration/final-image steps that Cargo does not model.

## Developer interface

Build a firmware image by selecting an app and one product platform:

~~~sh
cargo firmware --app event-demo --platform pico2-mock
cargo firmware --app event-demo --platform esp32s3-qemu-mock
~~~

Discovery is also through Cargo:

~~~sh
cargo firmware --list-apps
cargo firmware --list-platforms
~~~

The repository alias in `.cargo/config.toml` invokes the small host-side
`nxrs-firmware` binary under `platform/firmware`.

## Sources of build data

There are only two product-facing inputs.

### Application Cargo metadata

A firmware-capable app declares execution-entry facts in its existing
`Cargo.toml`:

~~~toml
[package.metadata.nxrs.firmware]
bin = "event-demo"
command = "event_demo"
priority = 100
stack-size = 65536
~~~

The app's handwritten `main()` remains the service-composition source of truth.

### Product platform

`platform/nuttx/platforms/<name>.toml` owns hardware/build realization:

- NuttX board;
- Rust target and C toolchain;
- image format;
- HAL provider features;
- required/forbidden Kconfig settings.

The platform profile does not contain application identity or service wiring.

This gives the developer-facing model:

~~~text
app + platform
      |
      v
firmware image
~~~

rather than requiring:

~~~text
app + provider list + target triple + board + Kconfig + linker details
~~~

## Cargo frontend versus NuttX backend

`cargo firmware` resolves app metadata and platform selection, validates names
and output paths, then calls one common backend with explicit arguments:

~~~text
cargo firmware
      |
      v
nxrs-firmware
      |
      v
tools/build-nuttx-std-app.sh
      |
      +--> configure NuttX/Kconfig
      +--> prepare the qualified Rust std target
      +--> invoke Cargo for the selected app/provider graph
      +--> check Rust/C ABI and imports
      +--> perform the NuttX final link
      +--> produce nuttx / nuttx.bin / nuttx.merged.bin
~~~

The shell backend is intentionally not the user-facing build system. It exists
because NuttX's own Kconfig/Make/image tooling must be invoked somehow. It no
longer sources per-app deployment scripts; all application inputs arrive as
normal flags from the Cargo frontend.

There is no app×target wrapper-script cross product.

## Output layout

Unless `--out` is supplied:

~~~text
target/firmware/<app>/<platform>/
~~~

For example:

~~~text
target/firmware/event-demo/pico2-mock/nuttx/nuttx.bin
target/firmware/event-demo/esp32s3-qemu-mock/nuttx/nuttx.merged.bin
~~~

The retained provenance includes app package/bin, product platform, selected HAL
features, NuttX board/target, pinned NuttX source revisions and toolchain
versions.

## Relationship to Zephyr's model

The split remains intentionally similar to the useful part of Zephyr's
board/product model without recreating west or Devicetree:

~~~text
Zephyr:
app + board/overlay
       -> enabled hardware/drivers

Nxrs:
Cargo app + product platform
       -> selected HAL providers + NuttX board/target
~~~

Cargo owns the Rust package graph and is the command surface. NuttX owns its
native OS configuration and final image link.

## Capability-local HALs remain unchanged

The build frontend does not replace the capability facades.

~~~text
ImuService -> nxrs-imu -> selected provider
GnssService -> nxrs-gnss -> selected provider
~~~

Provider features are activated below app/service policy from the selected
platform. Unselected providers remain outside the active Cargo build graph.

## What is intentionally absent

There is no:

- per-app/per-platform wrapper shell script;
- checked-in deployment graph;
- runtime `Platform` trait;
- giant `Hal` object;
- global provider registry;
- generated app/service graph;
- Devicetree clone;
- general xtask/task-runner framework.

`nxrs-firmware` has one purpose: compose an existing Cargo app with one
product platform and produce a firmware image.
