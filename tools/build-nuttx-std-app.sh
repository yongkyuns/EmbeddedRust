#!/usr/bin/env bash
# Common ordinary-Rust-std NuttX application builder.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat >&2 <<'EOF'
usage: build-nuttx-std-app.sh \
  --app-manifest <path> --app-package <package> --bin <bin> \
  --command <nuttx-command> --priority <n> --stack-size <bytes> \
  --platform <name> --out <path> [--abi-profile active|minimal]
EOF
}

NXRS_APP_MANIFEST=
NXRS_APP_PACKAGE=
NXRS_APP_BIN=
NXRS_APP_COMMAND=
NXRS_APP_PRIORITY=
NXRS_APP_STACKSIZE=
NXRS_PLATFORM=
OUT_ARG=
NXRS_ABI_PROFILE=active

while test "$#" -gt 0; do
  case "$1" in
    --app-manifest) NXRS_APP_MANIFEST="${2:-}"; shift 2 ;;
    --app-package) NXRS_APP_PACKAGE="${2:-}"; shift 2 ;;
    --bin) NXRS_APP_BIN="${2:-}"; shift 2 ;;
    --command) NXRS_APP_COMMAND="${2:-}"; shift 2 ;;
    --priority) NXRS_APP_PRIORITY="${2:-}"; shift 2 ;;
    --stack-size) NXRS_APP_STACKSIZE="${2:-}"; shift 2 ;;
    --platform) NXRS_PLATFORM="${2:-}"; shift 2 ;;
    --out) OUT_ARG="${2:-}"; shift 2 ;;
    --abi-profile) NXRS_ABI_PROFILE="${2:-}"; shift 2 ;;
    *) echo "Unknown firmware backend argument: $1" >&2; usage; exit 2 ;;
  esac
done

for name in NXRS_APP_MANIFEST NXRS_APP_PACKAGE NXRS_APP_BIN \
  NXRS_APP_COMMAND NXRS_APP_PRIORITY NXRS_APP_STACKSIZE \
  NXRS_PLATFORM OUT_ARG; do
  test -n "${!name:-}" || { echo "Missing required argument for $name" >&2; usage; exit 2; }
done

[[ "$NXRS_PLATFORM" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  echo "Invalid platform name: $NXRS_PLATFORM" >&2
  exit 1
}
[[ "$NXRS_APP_PRIORITY" =~ ^[0-9]+$ && "$NXRS_APP_STACKSIZE" =~ ^[0-9]+$ ]] || {
  echo "Priority and stack size must be positive integers" >&2
  exit 1
}
test "$NXRS_APP_PRIORITY" -gt 0 && test "$NXRS_APP_STACKSIZE" -gt 0 || {
  echo "Priority and stack size must be positive integers" >&2
  exit 1
}
case "$NXRS_ABI_PROFILE" in
  active|minimal) ;;
  *) echo "Invalid ABI profile: $NXRS_ABI_PROFILE" >&2; exit 1 ;;
esac

[[ "$NXRS_APP_MANIFEST" = /* ]] || NXRS_APP_MANIFEST="$ROOT/$NXRS_APP_MANIFEST"
test -f "$NXRS_APP_MANIFEST" || {
  echo "Missing app manifest: $NXRS_APP_MANIFEST" >&2
  exit 1
}
[[ "$OUT_ARG" = /* ]] && OUT="$OUT_ARG" || OUT="$ROOT/$OUT_ARG"
NXRS_DEPLOYMENT="$NXRS_APP_BIN-$NXRS_PLATFORM"

PLATFORM_PATH="$ROOT/platform/nuttx/platforms/$NXRS_PLATFORM.toml"
test -f "$PLATFORM_PATH" || {
  echo "Unknown NuttX platform: $NXRS_PLATFORM ($PLATFORM_PATH)" >&2
  exit 1
}
command -v python3 >/dev/null || {
  echo "Missing prerequisite: python3" >&2
  exit 1
}

# Platform descriptions are declarative TOML. Python's standard tomllib is used
# only to translate trusted repository data into shell variables for the common
# NuttX backend; product profiles themselves contain no executable shell.
eval "$(
python3 - "$PLATFORM_PATH" <<'PY_PLATFORM'
import shlex
import sys
import tomllib

path = sys.argv[1]
with open(path, "rb") as stream:
    data = tomllib.load(stream)

def scalar(key, env):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{path}: {key} must be a non-empty string")
    print(f"{env}={shlex.quote(value)}")

def array(values, key, env, *, nonempty=False):
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise SystemExit(f"{path}: {key} must be an array of non-empty strings")
    if nonempty and not values:
        raise SystemExit(f"{path}: {key} must not be empty")
    print(f"{env}=(" + " ".join(shlex.quote(v) for v in values) + ")")

scalar("board", "NUTTX_BOARD")
scalar("target", "NUTTX_TARGET")
scalar("crossdev", "NUTTX_CROSSDEV")
scalar("machine", "NUTTX_MACHINE")
scalar("image", "NUTTX_IMAGE_NAME")
array(data.get("hal-features"), "hal-features", "NXRS_HAL_FEATURES", nonempty=True)

kconfig = data.get("kconfig")
if not isinstance(kconfig, dict):
    raise SystemExit(f"{path}: missing [kconfig] table")
array(kconfig.get("enable", []), "kconfig.enable", "NUTTX_ENABLE")
array(kconfig.get("disable", []), "kconfig.disable", "NUTTX_DISABLE")
array(kconfig.get("set", []), "kconfig.set", "NUTTX_SET")
array(kconfig.get("require", []), "kconfig.require", "NUTTX_REQUIRE")
forbid = kconfig.get("forbid-regex", "")
if not isinstance(forbid, str):
    raise SystemExit(f"{path}: kconfig.forbid-regex must be a string")
print(f"NUTTX_FORBID_REGEX={shlex.quote(forbid)}")
PY_PLATFORM
)"

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo "NuttX std deployments currently require Linux x86_64." >&2
  exit 1
}

TOOLCHAIN_KIND=
SDK=
SOURCE_RUSTC=
CARGO_BIN=
NUTTX_IMAGE_NAME="${NUTTX_IMAGE_NAME:-}"
EXTRA_HOST_TOOLS=()

case "$NUTTX_TARGET" in
  xtensa-esp32s3-nuttx)
    TOOLCHAIN_KIND=esp32s3
    SDK=esp-1.90.0.0
    TOOLS="$ROOT/target/qemu-tools"
    test -f "$TOOLS/environment.sh" || {
      echo "Missing pinned ESP32-S3 tools; run tools/install-qemu-tools.sh" >&2
      exit 1
    }
    # shellcheck disable=SC1090
    source "$TOOLS/environment.sh"
    export RUSTC_BOOTSTRAP=1
    SOURCE_RUSTC="$RUSTC"
    CARGO_BIN="$(rustup which --toolchain 1.90.0 cargo)"
    : "${NUTTX_IMAGE_NAME:=nuttx.merged.bin}"
    EXTRA_HOST_TOOLS=(qemu-system-xtensa esptool.py)
    ;;
  thumbv8m.main-nuttx-eabi)
    TOOLCHAIN_KIND=armv8m
    SDK=nightly-2025-09-15
    export RUSTUP_TOOLCHAIN="$SDK"
    SOURCE_RUSTC="$(rustup which --toolchain "$SDK" rustc)"
    CARGO_BIN="$(rustup which --toolchain "$SDK" cargo)"
    : "${NUTTX_IMAGE_NAME:=nuttx.bin}"
    ;;
  *)
    echo "Unsupported NuttX std target: $NUTTX_TARGET" >&2
    exit 1
    ;;
esac

for command in cargo git make kconfig-tweak python3 rustup \
  "${NUTTX_CROSSDEV}gcc" "${NUTTX_CROSSDEV}ld" "${NUTTX_CROSSDEV}objcopy" \
  "${NUTTX_CROSSDEV}readelf" "${NUTTX_CROSSDEV}nm" "${NUTTX_CROSSDEV}size" \
  "${EXTRA_HOST_TOOLS[@]}"; do
  command -v "$command" >/dev/null || { echo "Missing prerequisite: $command" >&2; exit 1; }
done

mkdir -p "$OUT"
rm -rf "$OUT/nuttx" "$OUT/apps" "$OUT/cargo" "$OUT/toolchain"
rm -f "$OUT"/*.json "$OUT"/*.jsonl "$OUT"/*.txt "$OUT"/*.patch "$OUT"/*.sha256
mkdir -p "$OUT/nuttx" "$OUT/apps"

for pair in nuttx:nuttx nuttx-apps:apps; do
  source_name=${pair%:*}
  destination=${pair#*:}
  expected=$(git -C "$ROOT" rev-parse "HEAD:external/$source_name")
  actual=$(git -C "$ROOT/external/$source_name" rev-parse HEAD)
  test "$expected" = "$actual" || { echo "Unpinned $source_name" >&2; exit 1; }
  git -C "$ROOT/external/$source_name" archive "$expected" | tar -x -C "$OUT/$destination"
  if test "$source_name" = nuttx; then
    python3 "$ROOT/tools/apply-nuttx-patches.py" \
      --source "$OUT/nuttx" --revision "$expected" --record "$OUT/nuttx-patches.json"
  fi
done

APP="$OUT/apps/examples/nxrs_std_app"
mkdir -p "$APP"
cp "$ROOT/platform/nuttx/std-app/"* "$APP/"

cd "$OUT/nuttx"
./tools/configure.sh -l "$NUTTX_BOARD"

for symbol in EXAMPLES_HELLO TESTING_OSTEST TESTING_GETPRIME ARCH_FPU SIG_DEFAULT; do
  kconfig-tweak --disable "CONFIG_$symbol"
done
for symbol in "${NUTTX_ENABLE[@]:-}"; do
  test -n "$symbol" && kconfig-tweak --enable "CONFIG_$symbol"
done
for symbol in "${NUTTX_DISABLE[@]:-}"; do
  test -n "$symbol" && kconfig-tweak --disable "CONFIG_$symbol"
done
for assignment in "${NUTTX_SET[@]:-}"; do
  test -n "$assignment" || continue
  kconfig-tweak --set-val "CONFIG_${assignment%%=*}" "${assignment#*=}"
done

for symbol in EXAMPLES_NXRS_STD_APP SYSTEM_TIME64 FS_LARGEFILE DEV_URANDOM   SCHED_WAITPID SCHED_HAVE_PARENT SCHED_CHILD_STATUS NSH_DISABLEBG NSH_ARGCAT; do
  kconfig-tweak --enable "CONFIG_$symbol"
done
kconfig-tweak --enable CONFIG_TLS_GLOBAL_KEYS
kconfig-tweak --set-val CONFIG_TLS_NELEM 16
kconfig-tweak --set-val CONFIG_TLS_NCLEANUP 16
kconfig-tweak --set-val CONFIG_RR_INTERVAL 10
make olddefconfig
cp .config "$OUT/resolved.config"

for required in "${NUTTX_REQUIRE[@]:-}"; do
  test -n "$required" || continue
  grep -qx "$required" .config || {
    echo "Deployment $NXRS_DEPLOYMENT unresolved requirement: $required" >&2
    exit 1
  }
done
for required in   CONFIG_BUILD_FLAT=y CONFIG_EXAMPLES_NXRS_STD_APP=y CONFIG_SYSTEM_TIME64=y   CONFIG_FS_LARGEFILE=y CONFIG_TLS_GLOBAL_KEYS=y CONFIG_TLS_NELEM=16 CONFIG_TLS_NCLEANUP=16   CONFIG_SCHED_WAITPID=y CONFIG_SCHED_HAVE_PARENT=y CONFIG_SCHED_CHILD_STATUS=y   CONFIG_NSH_DISABLEBG=y CONFIG_NSH_ARGCAT=y CONFIG_RR_INTERVAL=10; do
  grep -qx "$required" .config || { echo "Unresolved std requirement: $required" >&2; exit 1; }
done
if [[ -n "${NUTTX_FORBID_REGEX:-}" ]] && grep -Eq "$NUTTX_FORBID_REGEX" .config; then
  echo "Deployment $NXRS_DEPLOYMENT enabled a forbidden NuttX option" >&2
  grep -E "$NUTTX_FORBID_REGEX" .config >&2
  exit 1
fi
if grep -qx 'CONFIG_SIG_DEFAULT=y' .config; then
  echo "Unqualified SIG_DEFAULT configuration" >&2
  exit 1
fi

cd "$ROOT"
CHECK_DEPLOYMENT=(--app-manifest "$NXRS_APP_MANIFEST" --execution-platform std)
for feature in "${NXRS_HAL_FEATURES[@]}"; do
  CHECK_DEPLOYMENT+=(--hal-feature "$feature")
done
python3 tools/check-deployment.py "${CHECK_DEPLOYMENT[@]}" --out "$OUT/provider-selection.json"
HAL_FEATURES_CSV="$(IFS=,; echo "${NXRS_HAL_FEATURES[*]}")"
HAL_PACKAGES=()
for feature in "${NXRS_HAL_FEATURES[@]}"; do
  package="${feature%%/*}"
  HAL_PACKAGES+=(-p "$package")
done

python3 tests/nuttx-std/prepare-std.py \
  --source "$("$SOURCE_RUSTC" --print sysroot)" \
  --output "$OUT" \
  --sdk "$SDK"
export NUTTX_STD_SYSROOT="$OUT/toolchain"
export RUSTC="$NUTTX_STD_SYSROOT/bin/rustc"
export CARGO_BUILD_RUSTC="$RUSTC"
test "$("$RUSTC" --print sysroot)" = "$NUTTX_STD_SYSROOT"

TARGET_ARG="$NUTTX_TARGET"
ABI_ARGS=()
if test "$TOOLCHAIN_KIND" = esp32s3; then
  export NUTTX_STD_GNU_LINKER="$(command -v xtensa-esp32s3-elf-ld)"
  "$RUSTC" -Z unstable-options --print target-spec-json \
    --target xtensa-esp32s3-none-elf > "$OUT/xtensa-bare-target.json"
  python3 - "$OUT" "$NXRS_DEPLOYMENT" <<'PY_TARGET'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
deployment = sys.argv[2]
target = json.loads((out / "xtensa-bare-target.json").read_text())
assert target["arch"] == "xtensa" and target["cpu"] == "esp32s3"
assert str(target["target-pointer-width"]) == "32"
assert target.get("max-atomic-width") == 32
target.update(os="nuttx", **{
    "target-family": ["unix"], "executables": True, "has-thread-local": False,
    "linker-flavor": "ld", "linker": "xtensa-esp32s3-elf-ld",
    "relocation-model": "static",
})
for key in ("pre-link-args", "late-link-args", "post-link-args"):
    target.pop(key, None)
target["metadata"] = {"description": f"Nxrs deployment {deployment}", "std": True}
(out / "xtensa-esp32s3-nuttx.json").write_text(json.dumps(target, indent=2) + "\n")
PY_TARGET
  TARGET_ARG="$OUT/$NUTTX_TARGET.json"
  ABI_ARGS=(--target-spec "$TARGET_ARG")
  cp "$TOOLS/downloads.sha256" "$OUT/downloads.sha256"
fi
export NXRS_APP_COMMAND NXRS_APP_PRIORITY NXRS_APP_STACKSIZE
export CARGO_TARGET_DIR="$OUT/cargo"
export CARGO_PROFILE_RELEASE_LTO=false
export CARGO_PROFILE_RELEASE_STRIP=none
export CARGO_PROFILE_RELEASE_DEBUG=1
export NUTTX_STD_LINK_LOG="$OUT/rust-link.json"
export RUSTFLAGS="-C panic=abort -C linker=$ROOT/tests/nuttx-std/link.py"
if [[ "${NXRS_NUTTX_DIAGNOSTIC_UNWIND:-0}" == 1 ]]; then
  # The MPS2 ARM EHABI backtracer needs unwind entries in Rust code too.
  # Keep this opt-in: extra tables change the ordinary firmware image.
  export RUSTFLAGS="$RUSTFLAGS -C force-unwind-tables=yes"
fi

"$CARGO_BIN" build --locked --release \
  -p "$NXRS_APP_PACKAGE" "${HAL_PACKAGES[@]}" \
  --features "$HAL_FEATURES_CSV" --bin "$NXRS_APP_BIN" \
  --target "$TARGET_ARG" -Zbuild-std=std,panic_abort \
  --message-format=json-render-diagnostics | tee "$OUT/cargo-messages.jsonl"

python3 - "$OUT" <<'PY_SOURCE'
import json, os, pathlib, sys
out = pathlib.Path(sys.argv[1])
messages = [json.loads(line) for line in (out / "cargo-messages.jsonl").read_text().splitlines()]
std = [m for m in messages if m.get("reason") == "compiler-artifact"
       and m["target"]["name"] == "std" and "rlib" in m["target"]["crate_types"]]
assert len(std) == 1, f"expected one std artifact, found {len(std)}"
actual = pathlib.Path(std[0]["target"]["src_path"]).resolve()
expected = pathlib.Path(os.environ["NUTTX_STD_SYSROOT"]) / "lib/rustlib/src/rust/library/std/src/lib.rs"
proof = {
    "std_source": str(actual),
    "expected_source": str(expected.resolve()),
    "rustc": os.environ["RUSTC"],
    "selected_source_matches": actual == expected.resolve(),
}
(out / "std-source.json").write_text(json.dumps(proof, indent=2) + "\n")
assert proof["selected_source_matches"], "Cargo selected the wrong standard-library source"
PY_SOURCE

ELF="$CARGO_TARGET_DIR/$NUTTX_TARGET/release/$NXRS_APP_BIN"
"${NUTTX_CROSSDEV}readelf" -h "$ELF" > "$OUT/rust-elf-header.txt"
grep -q 'REL (Relocatable file)' "$OUT/rust-elf-header.txt"
grep -Eq "Machine: +$NUTTX_MACHINE$" "$OUT/rust-elf-header.txt"
"${NUTTX_CROSSDEV}nm" "$ELF" > "$OUT/rust-symbols.txt"
grep -Eq ' T main$' "$OUT/rust-symbols.txt"
if test "$NXRS_ABI_PROFILE" = active; then
  for symbol in pthread_create pthread_join clock_gettime; do
    grep -Eq " U $symbol$" "$OUT/rust-symbols.txt" || {
      echo "Active std app missing expected import $symbol" >&2
      exit 1
    }
  done
fi
python3 tests/nuttx-std/check-abi.py --check-imports "$OUT/rust-symbols.txt"

unset RUSTFLAGS
MAKE_ARGS=(
  "CROSSDEV=$NUTTX_CROSSDEV"
  "NXRS_STD_ELF=$ELF"
  "NXRS_APP_COMMAND=$NXRS_APP_COMMAND"
  "NXRS_APP_PRIORITY=$NXRS_APP_PRIORITY"
  "NXRS_APP_STACKSIZE=$NXRS_APP_STACKSIZE"
)
if test "$TOOLCHAIN_KIND" = esp32s3; then
  MAKE_ARGS+=(ESPTOOL_BINDIR=.)
fi
make -C "$OUT/nuttx" -j4 "${MAKE_ARGS[@]}"

python3 tests/nuttx-std/check-abi.py --self-test
python3 tests/nuttx-std/check-abi.py \
  --out "$OUT" --target "$NUTTX_TARGET" "${ABI_ARGS[@]}"

"${NUTTX_CROSSDEV}nm" "$OUT/nuttx/nuttx" > "$OUT/symbols.txt"
FINAL_REQUIRED=("${NXRS_APP_COMMAND}_main" nx_start)
if test "$NXRS_ABI_PROFILE" = active; then
  FINAL_REQUIRED+=(pthread_create pthread_join clock_gettime)
fi
for symbol in "${FINAL_REQUIRED[@]}"; do
  grep -Eq " [TtWw] $symbol$" "$OUT/symbols.txt" || {
    echo "Final NuttX image missing $symbol" >&2
    exit 1
  }
done

"${NUTTX_CROSSDEV}size" -A "$OUT/nuttx/nuttx" > "$OUT/image-size.txt"
"${NUTTX_CROSSDEV}readelf" -h -l -A "$OUT/nuttx/nuttx" > "$OUT/image-layout.txt"
NUTTX_IMAGE="$OUT/nuttx/$NUTTX_IMAGE_NAME"
test -s "$NUTTX_IMAGE"

{
  echo "deployment=$NXRS_DEPLOYMENT"
  echo "nxrs=$(git rev-parse HEAD)"
  echo "nuttx=$(git rev-parse HEAD:external/nuttx)"
  echo "apps=$(git rev-parse HEAD:external/nuttx-apps)"
  echo "app_package=$NXRS_APP_PACKAGE"
  echo "app_bin=$NXRS_APP_BIN"
  echo "platform=$NXRS_PLATFORM"
  echo "platform_profile=${PLATFORM_PATH#$ROOT/}"
  echo "hal_features=$HAL_FEATURES_CSV"
  echo "app_command=$NXRS_APP_COMMAND"
  echo "abi_profile=$NXRS_ABI_PROFILE"
  echo "target=$NUTTX_TARGET"
  echo "board=$NUTTX_BOARD"
  "$RUSTC" --version --verbose
  "${NUTTX_CROSSDEV}gcc" --version | head -n 1
  if test "$TOOLCHAIN_KIND" = esp32s3; then
    qemu-system-xtensa --version | head -n 1
  fi
} > "$OUT/provenance.txt"

HASH_INPUTS=("$OUT/nuttx/nuttx" "$NUTTX_IMAGE" "$ELF" "$NXRS_APP_MANIFEST" "$PLATFORM_PATH")
if test "$TOOLCHAIN_KIND" = esp32s3; then
  HASH_INPUTS+=("$TARGET_ARG")
fi
sha256sum "${HASH_INPUTS[@]}" > "$OUT/binaries.sha256"

echo "NuttX std deployment image: $NUTTX_IMAGE"
