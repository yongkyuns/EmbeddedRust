#!/usr/bin/env bash
# Full ESP32-S3 NuttX integration using the qualified ordinary Rust std path.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/target/nuttx-qemu"

# Tool archives/environment are installed by tools/install-qemu-tools.sh.
test -f "$ROOT/target/qemu-tools/environment.sh" || {
  echo "Missing pinned QEMU/Rust/GCC tools; run tools/install-qemu-tools.sh" >&2
  exit 1
}

cd "$ROOT"
NUTTX_STD_COMPAT_FIXES=1 bash tests/nuttx-std/build.sh integration-esp32s3

source "$ROOT/target/qemu-tools/environment.sh"
xtensa-esp32s3-elf-nm "$OUT/nuttx/nuttx" > "$OUT/symbols.txt"
xtensa-esp32s3-elf-readelf -h -l -d "$OUT/nuttx/nuttx" > "$OUT/elf.txt"
xtensa-esp32s3-elf-objdump -dr "$OUT/nuttx/nuttx" > "$OUT/disassembly.txt"
python3 "$ROOT/tests/host/check-nuttx-qemu-link.py" "$OUT"

git -C "$ROOT" archive HEAD Cargo.toml Cargo.lock rust-toolchain.toml tools platform app service hal tests driver > "$OUT/harness-source.tar"
echo "ESP32-S3 std integration image: $OUT/nuttx/nuttx.merged.bin"
