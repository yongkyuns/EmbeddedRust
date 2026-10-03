#!/usr/bin/env bash
# Reproduce the checked-in PX4 reference SVGs. D2 v0.9.0, ELK, 16 px padding.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
D2="${D2:-d2}"
command -v "$D2" >/dev/null 2>&1 || { echo 'Install D2 v0.9.0 or set D2 to its executable path.' >&2; exit 1; }
version="$("$D2" --version)"
[[ "$version" == *0.9.0* ]] || { echo "Expected D2 v0.9.0, got: $version" >&2; exit 1; }
for name in architecture execution-contexts uorb-delivery topic-retention imu-acquisition estimator-inputs outer-control fast-control nxrs-direction execution-map; do
  "$D2" --layout=elk --theme=0 --pad=16 "$name.d2" "$name.svg"
done
python3 check.py
