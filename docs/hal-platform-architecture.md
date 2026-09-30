# HAL capability architecture

**Status:** architectural source of truth for provider selection and service-owned resources.

## Core rule

Rustcam has no global HAL platform package or universal HAL object.

Each capability owns its public facade and its provider selection:

~~~text
hal/imu/             -> rustcam-imu
  api/               -> provider-independent Imu/ImuSample contract
  mock/              -> synthetic provider
  <future provider>/ -> physical/native/web implementation

hal/camera/          -> rustcam-camera
  api/
  native/
  nuttx/
  mock/
~~~

Portable applications and services depend on capability facades such as
`rustcam-imu`, `rustcam-camera`, `rustcam-storage`, and
`rustcam-transport`. They do not depend on concrete provider crates.

Provider selection is a build/deployment decision implemented through features
on each capability facade. Production deployments should normally not enumerate
those features themselves. Instead they select one checked-in **product platform**
whose hardware description owns the complete set of provider bindings.

For example, the developer selects only:

~~~sh
cargo firmware --app vehicle --platform pico2w-product-a
~~~

The app's Cargo metadata supplies entry/resource settings while that platform
profile selects the appropriate IMU, GNSS, storage, network, board, target and
Kconfig configuration.

There is deliberately no central `hal/platform` Rust package or runtime object.
The product platform is build metadata, not a software dependency.

## Dependency direction

~~~text
application
    |
    +--> services
    |      |
    |      +--> capability facade when the service owns the resource
    |
    +--> capability facade when the application owns the resource
             |
             +--> stable capability contract
             |
             +--> one build-selected provider
                      |
                      +--> driver / OS support as required
~~~

Examples:

~~~text
ImuService
  -> rustcam-imu
       -> rustcam-imu-api
       -> rustcam-imu-mock          # selected by build

app/rustcam
  -> rustcam-camera
       -> rustcam-camera-api
       -> rustcam-camera-native     # selected by build
~~~

The application/service source sees the capability, not the provider identity.

## Why the facade is separate from api/

The `api/` crate contains only the provider-independent contract. Providers
depend on that contract, so putting provider dependencies directly into the
contract crate would create a Cargo cycle:

~~~text
camera-api -> camera-native -> camera-api
~~~

The capability root crate is therefore the thin selection facade:

~~~text
camera facade -> camera-api
              -> selected camera provider
~~~

The facade re-exports the portable contract and exposes acquisition where that is
useful. It must not become a registry, service factory, runtime manager, bus
container, or giant global HAL object.

## Build selection

Provider choice belongs below application and service policy.

The Cargo firmware frontend composes:

- one application, whose existing Cargo metadata owns binary/command/resource
  settings;
- one product platform.

The selected product platform owns:

- the provider feature required for each used HAL capability;
- execution target/OS and board configuration;
- target-specific Kconfig/build facts.

Thus a new product normally adds a new platform description rather than editing
the app or manually composing provider features at every build site.

Capability-local Cargo features remain the mechanism that excludes unselected
providers from the dependency graph. They are intentionally lower-level than
the product platform abstraction. Do not put provider-selection features in
application or service manifests.

## Build-time exclusion

Unselected providers must stay out of the active Cargo build graph. Source-level
`#[cfg]` around code is not enough if the provider remains an unconditional
Cargo dependency.

Provider crates therefore remain optional dependencies of their capability
facade. The selected feature activates exactly one provider for that capability.

The build checks must verify:

- app/service manifests do not depend directly on provider packages;
- each selected facade feature maps to one local provider;
- no capability selects conflicting providers;
- the provider declares support for the requested execution environment;
- minimal-image evidence excludes unselected Rust providers and exclusive C
  driver/registration objects.

A broad workspace test may compile several providers independently. That is not
evidence that a production image selected all of them.

## Resource ownership

The component that naturally consumes a capability normally owns it.

For a service-owned sensor:

~~~text
app
  -> ImuService::start()
       -> rustcam_imu::open()
            -> selected IMU provider
~~~

For the current native camera profile, the app is the natural composition and
configuration boundary:

~~~text
app/rustcam
  -> rustcam_camera::open(...)
  -> CameraService(camera)

  -> rustcam_storage::open(...)
  -> RecordingService(storage)

  -> rustcam_transport::open(...)
  -> TelemetryService(transport)
~~~

Both are valid. The important boundary is that neither app nor service names
`rustcam-*-native`, `rustcam-*-nuttx`, `rustcam-*-mock`, a concrete sensor,
or a bus/IRQ implementation.

## Capability configuration

Different providers may legitimately need different setup data. A native replay
camera needs a source path and replay period; a physical NuttX camera may need a
device/resource description.

Do not invent one giant cross-platform configuration enum merely to force every
provider constructor into one signature. Keep portable behavior in the
capability contract, keep provider-specific setup below the facade when possible,
and add a genuinely portable configuration type only when the semantics are
actually common.

## Relationship to platform/

`hal/` answers:

> Which implementation satisfies this capability in this build?

`platform/` answers:

> How is this firmware built, linked, configured, and booted on this target?

For example, `cargo firmware --app event-demo --platform pico2-mock` combines
the event-demo Cargo metadata with
`platform/nuttx/platforms/pico2-mock.toml`. The platform file contains the Pico 2
board/target configuration and mock IMU/GNSS bindings. That product description
is analogous to a Zephyr board/overlay selection; it is not a global runtime HAL
abstraction.

## Portability invariant

The target invariant is:

> Portable application/service source must compile and behave against compatible
> capability-provider selections without naming or branching on provider
> identity.

Platform differences may change device wiring, OS calls, resource limits,
readiness implementation, physical timing, or configuration data. They must not
force product policy to import concrete backend packages.

## Current migration state

- IMU/GNSS services depend on `rustcam-imu` and `rustcam-gnss`; their mock
  providers are selected by build profiles.
- app/rustcam depends on `rustcam-camera`, `rustcam-storage`, and
  `rustcam-transport`; the native providers are selected by the build.
- the former global `rustcam-hal` / `hal/platform` package has been removed.
- low-level provider qualification tests may still depend on a provider directly,
  because the provider itself is what those tests are qualifying.

The next architectural work is execution/readiness and cross-thread payload
ownership, not another provider registry.
