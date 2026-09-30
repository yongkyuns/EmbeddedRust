# Device drivers

Repository-owned physical device protocols and hardware drivers belong here.
No physical driver has been moved out of the pinned NuttX fork: its sources
remain in `external/nuttx`, including the ESP32-S3 camera work. Do not duplicate
those sources just to populate this directory. New portable bus-based drivers
may depend on `hal/api`; OS driver implementations may use their OS APIs.
Drivers must not depend on application/service policy or platform launchers.

The synthetic NuttX sensor and syscall fault injectors are qualification-only
fixtures in `tests/nuttx/c`, not production drivers. Scripted HAL substitutes
are in `hal/mock`. Board pin assignments, registration and configuration belong
in `platform`, while OS-device adaptation belongs in `hal/<implementation>`.
