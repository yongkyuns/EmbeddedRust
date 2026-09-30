#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cargo +1.90.0 build --locked \
  -p nxrs-event-demo -p nxrs-imu -p nxrs-gnss \
  --features nxrs-imu/mock,nxrs-gnss/mock \
  --bin event-demo

TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/target}"
exec "$TARGET_DIR/debug/event-demo" "$@"
