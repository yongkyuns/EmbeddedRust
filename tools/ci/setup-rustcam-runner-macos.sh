#!/usr/bin/env bash
# Bootstrap a repository-scoped rustcam GitHub Actions runner inside an
# isolated Ubuntu 24.04 Lima VM on macOS.
#
# Security properties:
# - the GitHub runner is scoped only to yongkyuns/rustcam;
# - the runner executes inside a Linux VM, not directly on macOS;
# - Lima is created with --plain, so the Mac home/project filesystem is not mounted;
# - the registration token is obtained locally with gh and is never committed;
# - the runner service runs as the unprivileged Lima guest user.
set -euo pipefail

REPO="${RUSTCAM_REPO:-yongkyuns/rustcam}"
VM="${RUSTCAM_RUNNER_VM:-rustcam-ci}"
RUNNER_NAME="${RUSTCAM_RUNNER_NAME:-yongkyuns-mac-rustcam-vm}"
RUNNER_VERSION="2.337.0"

case "$(uname -s)" in
  Darwin) ;;
  *) echo "This bootstrap is for macOS." >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64)
    LIMA_ARCH="x86_64"
    RUNNER_ARCH="x64"
    RUNNER_SHA256="70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"
    ;;
  arm64)
    LIMA_ARCH="aarch64"
    RUNNER_ARCH="arm64"
    RUNNER_SHA256="9b1dc70626422526e3c94767cf024896beb15da5342a3f4819bf2feac13e0393"
    ;;
  *)
    echo "Unsupported Mac architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it first, then rerun this script." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  brew install gh
fi
if ! command -v limactl >/dev/null 2>&1; then
  brew install lima
fi

gh auth status --hostname github.com >/dev/null
echo "Obtaining a one-hour repository runner registration token through local gh auth..."
REG_TOKEN="$(gh api --method POST "repos/$REPO/actions/runners/registration-token" --jq .token)"
test -n "$REG_TOKEN"

if limactl list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qx "$VM"; then
  echo "Using existing Lima VM: $VM"
  limactl start "$VM" >/dev/null
else
  echo "Creating isolated Ubuntu 24.04 VM: $VM"
  # --plain intentionally disables host mounts, port forwarding and containerd.
  # No Mac home directory is exposed to CI.
  limactl start     --name="$VM"     --vm-type=vz     --arch="$LIMA_ARCH"     --cpus=4     --memory=8     --disk=40     --plain     template:ubuntu-24.04
fi

echo "Verifying the VM has no Mac home mount..."
HOST_HOME="$HOME"
if limactl shell "$VM" sh -lc "mount | grep -F -- '$HOST_HOME'"; then
  echo "Refusing to continue: host home is mounted inside the CI VM." >&2
  exit 1
fi

echo "Staging the short-lived registration token inside the VM..."
printf '%s' "$REG_TOKEN" | limactl shell "$VM" sh -c '
  umask 077
  cat > /tmp/rustcam-runner-registration-token
'
unset REG_TOKEN

limactl shell "$VM" bash -s --   "$REPO" "$RUNNER_NAME" "$RUNNER_VERSION" "$RUNNER_ARCH" "$RUNNER_SHA256" <<'GUEST'
set -euo pipefail
REPO="$1"
RUNNER_NAME="$2"
RUNNER_VERSION="$3"
RUNNER_ARCH="$4"
RUNNER_SHA256="$5"
TOKEN_FILE=/tmp/rustcam-runner-registration-token
trap 'rm -f "$TOKEN_FILE"' EXIT

USER_NAME="$(id -un)"
RUNNER_DIR="$HOME/actions-runner-rustcam"
ARCHIVE="/tmp/actions-runner-${RUNNER_VERSION}.tar.gz"
URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"

sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl git

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ ! -x ./config.sh ]]; then
  curl --fail --location --retry 3 "$URL" -o "$ARCHIVE"
  echo "${RUNNER_SHA256}  ${ARCHIVE}" | sha256sum --check --status
  tar xzf "$ARCHIVE"
  rm -f "$ARCHIVE"
fi

if [[ ! -f .runner ]]; then
  TOKEN="$(cat "$TOKEN_FILE")"
  ./config.sh     --unattended     --url "https://github.com/$REPO"     --token "$TOKEN"     --name "$RUNNER_NAME"     --labels "rustcam,nuttx,isolated"     --work "_work"     --replace
  unset TOKEN
else
  echo "Runner is already configured in $RUNNER_DIR"
fi

if [[ ! -f .service ]]; then
  sudo ./svc.sh install "$USER_NAME"
fi
sudo ./svc.sh start
sudo ./svc.sh status
GUEST

echo
echo "rustcam self-hosted runner is configured."
echo "VM:       $VM"
echo "Runner:   $RUNNER_NAME"
echo "Labels:   self-hosted, Linux, rustcam, nuttx, isolated"
echo
echo "Useful commands:"
echo "  limactl stop $VM"
echo "  limactl start $VM"
echo "  limactl shell $VM -- bash -lc 'cd ~/actions-runner-rustcam && sudo ./svc.sh status'"
