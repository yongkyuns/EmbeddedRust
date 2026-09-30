#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cargo +1.90.0 build --locked \
  -p rustcam-dual-imu-demo -p rustcam-imu \
  --features rustcam-imu/mock \
  --bin dual-imu-demo

TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/target}"
exec "$TARGET_DIR/debug/dual-imu-demo" "$@"
