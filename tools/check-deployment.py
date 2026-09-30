#!/usr/bin/env python3
"""Validate build-selected provider features on capability-local HAL facades."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib


def load(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate(
    app_manifest: Path,
    hal_features: list[str],
    execution_platform: str,
) -> dict:
    app_manifest = app_manifest.resolve()
    root = app_manifest.parents[2]
    hal_root = root / "hal"
    app = load(app_manifest)

    for alias, dep in app.get("dependencies", {}).items():
        if not isinstance(dep, dict) or "path" not in dep:
            continue
        target = (app_manifest.parent / dep["path"]).resolve()
        if not is_within(target, hal_root):
            continue
        relative = target.relative_to(hal_root)
        is_portable_hal = (
            relative.parts == ("common",)
            or len(relative.parts) == 1
            or (len(relative.parts) == 2 and relative.parts[1] == "api")
        )
        if not is_portable_hal:
            raise ValueError(
                f"application dependency {alias} selects concrete HAL implementation "
                f"{relative}; apps may access capability facades/contracts but not providers"
            )

    facades = {}
    for manifest in hal_root.glob("*/Cargo.toml"):
        data = load(manifest)
        package = data.get("package", {})
        metadata = package.get("metadata", {}).get("nxrs", {})
        if metadata.get("kind") == "hal-capability":
            facades[package.get("name")] = (manifest, data)

    evidence = []
    capabilities = set()
    for selection in hal_features:
        if "/" not in selection:
            raise ValueError(f"HAL feature must be package/feature: {selection}")
        package_name, feature_name = selection.split("/", 1)
        if package_name not in facades:
            raise ValueError(f"not a HAL capability facade: {package_name}")
        manifest, facade = facades[package_name]
        capability = manifest.parent.name
        if capability in capabilities:
            raise ValueError(f"multiple provider selections for capability {capability}")
        capabilities.add(capability)

        declared = (
            facade.get("package", {})
            .get("metadata", {})
            .get("nxrs", {})
            .get("provider-features", [])
        )
        if feature_name not in declared:
            raise ValueError(f"feature is not a declared provider selection: {selection}")
        values = facade.get("features", {}).get(feature_name)
        if values is None:
            raise ValueError(f"missing provider feature: {selection}")
        aliases = [value.removeprefix("dep:") for value in values if value.startswith("dep:")]
        if len(aliases) != 1:
            raise ValueError(f"provider feature must select exactly one provider: {selection}")

        alias = aliases[0]
        dep = facade.get("dependencies", {}).get(alias)
        if not isinstance(dep, dict) or not dep.get("optional") or "path" not in dep:
            raise ValueError(f"{selection} must select one optional local provider")
        provider_manifest = (manifest.parent / dep["path"] / "Cargo.toml").resolve()
        provider = load(provider_manifest)
        package = provider.get("package", {})
        expected_package = dep.get("package", alias)
        if package.get("name") != expected_package:
            raise ValueError(f"{selection} package/path mismatch")

        relative = provider_manifest.parent.relative_to(hal_root)
        if relative.parts != (capability, feature_name):
            raise ValueError(
                f"{selection} provider must live at hal/{capability}/{feature_name}"
            )
        metadata = package.get("metadata", {}).get("nxrs", {})
        platforms = metadata.get("platforms", [])
        if execution_platform not in platforms:
            raise ValueError(
                f"{selection} provider {expected_package} does not declare execution platform "
                f"{execution_platform}"
            )
        evidence.append({
            "capability": capability,
            "feature": feature_name,
            "package": expected_package,
            "manifest": str(provider_manifest),
            "mode": metadata.get("mode"),
            "platforms": platforms,
        })

    return {
        "app_manifest": str(app_manifest),
        "app_package": app.get("package", {}).get("name"),
        "execution_platform": execution_platform,
        "hal_features": hal_features,
        "providers": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-manifest", type=Path, required=True)
    parser.add_argument("--hal-feature", action="append", default=[])
    parser.add_argument("--execution-platform", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        result = validate(args.app_manifest, args.hal_feature, args.execution_platform)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error

    encoded = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
