# Capability contracts and independently selected providers

`camera`, `storage`, and `transport` each own an `api` crate plus independently
selected implementations. Camera/storage currently have `native`, `nuttx`, and
`mock` providers; transport has native/NuttX std-socket providers plus a mock. Domain APIs activate no providers.
Services import only the APIs they need. App main selects resources through
ordinary Cargo dependencies and supplies them to service constructors.

See [camera support](camera/README.md), [frame-storage semantics](storage/README.md),
and [transport contracts and isolation](transport/README.md). Native providers
use standard-library file/socket operations beneath these device/data contracts.
Mock providers are explicit test choices, not evidence of real web hardware/I/O.

`common` contains only shared DeviceError values. `support/nuttx` contains the
existing descriptor ownership and scalar error translation used by NuttX
camera/storage compatibility providers. Neither imports camera, storage or
network implementations. NuttX transport no longer uses that descriptor/FFI
support; its production provider is ordinary `std::net`.

## Composition and ordinary standard-library facilities

There are no platform-wide HAL facade packages. Callers select camera, storage,
and transport API/provider crates directly. Cross-capability composition belongs
in an application or test package, not in `hal/api`, `hal/native`, `hal/mock`,
or `hal/nuttx`.

Ordinary system timekeeping uses `std::time`, not a capability HAL. There is
no Clock trait or clock mock. Deterministic tests pass explicit timestamps
directly; the core-only x86 NuttX fixture keeps its C time shim under
`tests/nuttx` only. Service state transitions receive explicit time values;
sensor acquisition timestamps and clock-domain conversion stay device/data
contracts. No clock, memory, or runtime package suite is required.
