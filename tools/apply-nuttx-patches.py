#!/usr/bin/env python3
"""Apply the tracked NuttX patch series to an archived build copy only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "platform/nuttx/patches"
SERIES = ("0001-flat-build-global-pthread-keys.patch",)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_env(source):
    # A build archive may live under the nxrs checkout. Prevent git apply from
    # treating its paths as relative to that unrelated outer repository.
    return {**os.environ, "GIT_CEILING_DIRECTORIES": str(source.parent)}


def run_git_apply(source, *options, patch):
    return subprocess.run(
        ["git", "apply", *options, str(patch)],
        cwd=source, env=git_env(source), text=True, capture_output=True,
    )


def apply(source, revision, record):
    source = Path(source).resolve(strict=True)
    if (source / ".git").exists():
        raise ValueError("refusing to patch a Git checkout; use an archived build copy")
    if not (source / "libs/libc/tls/Kconfig").is_file():
        raise ValueError("not a NuttX source archive")

    provenance = {"schema": 1, "nuttx_revision": revision, "patches": []}
    for name in SERIES:
        patch = PATCH_DIR / name
        paths = [line.split("\t", 2)[2] for line in subprocess.check_output(
            ["git", "apply", "--numstat", str(patch)],
            cwd=source, env=git_env(source), text=True,
        ).splitlines()]
        if not paths or any(not (source / path).is_file() for path in paths):
            raise ValueError(f"patch {name} references missing source files")
        check = run_git_apply(source, "--check", "--whitespace=error", patch=patch)
        if check.returncode:
            raise ValueError(f"patch {name} is incompatible or already applied: {check.stderr.strip()}")
        before = {path: sha256(source / path) for path in paths}
        result = run_git_apply(source, "--whitespace=error", patch=patch)
        if result.returncode:
            raise RuntimeError(f"failed to apply {name}: {result.stderr.strip()}")
        provenance["patches"].append({
            "name": name,
            "sha256": sha256(patch),
            "files": {path: {"before": before[path], "after": sha256(source / path)}
                      for path in paths},
        })
    Path(record).write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()
    apply(args.source, args.revision, args.record)
