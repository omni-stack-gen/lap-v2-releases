#!/usr/bin/env python3
"""Validate a LAP v2 release manifest.

This helper is intentionally small and dependency-free so release jobs can run
it anywhere Python 3 is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TARGETS = {"install_root", "packages_root", "toolchain_root"}
_ARCHIVES = {"tar.gz", "tgz"}


def _err(message: str) -> str:
    return f"manifest error: {message}"


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if data.get("schema_version") != 1:
        errors.append(_err("schema_version must be 1"))

    release = data.get("release")
    if not isinstance(release, dict) or not release.get("version"):
        errors.append(_err("release.version is required"))

    defaults = data.get("defaults")
    if not isinstance(defaults, dict) or not defaults.get("saas_url"):
        errors.append(_err("defaults.saas_url is required"))

    assets = data.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append(_err("assets must be a non-empty list"))
        return errors

    seen_ids: set[str] = set()
    seen_kinds: set[str] = set()
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            errors.append(_err(f"assets[{index}] must be an object"))
            continue

        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(_err(f"assets[{index}].id is required"))
        elif asset_id in seen_ids:
            errors.append(_err(f"duplicate asset id {asset_id!r}"))
        else:
            seen_ids.add(asset_id)

        kind = asset.get("kind")
        if not isinstance(kind, str) or not kind:
            errors.append(_err(f"assets[{index}].kind is required"))
        else:
            seen_kinds.add(kind)

        for field in ("version",):
            if not isinstance(asset.get(field), str) or not asset[field]:
                errors.append(_err(f"assets[{index}].{field} is required"))

        has_url = isinstance(asset.get("url"), str) and bool(asset["url"])
        parts = asset.get("parts", [])
        has_parts = isinstance(parts, list) and bool(parts)
        if not has_url and not has_parts:
            errors.append(_err(f"assets[{index}] must define url or parts"))
        if has_parts:
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict):
                    errors.append(_err(f"assets[{index}].parts[{part_index}] must be an object"))
                    continue
                for field in ("name", "url", "sha256"):
                    if not isinstance(part.get(field), str) or not part[field]:
                        errors.append(
                            _err(f"assets[{index}].parts[{part_index}].{field} is required")
                        )
                part_sha256 = part.get("sha256")
                if isinstance(part_sha256, str) and not _SHA256_RE.match(part_sha256):
                    errors.append(
                        _err(
                            f"assets[{index}].parts[{part_index}].sha256 must be 64 lowercase hex chars"
                        )
                    )

        sha256 = asset.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            errors.append(_err(f"assets[{index}].sha256 must be 64 lowercase hex chars"))

        archive = asset.get("archive")
        if archive not in _ARCHIVES:
            errors.append(_err(f"assets[{index}].archive must be one of {sorted(_ARCHIVES)}"))

        target = asset.get("target")
        if target not in _TARGETS:
            errors.append(_err(f"assets[{index}].target must be one of {sorted(_TARGETS)}"))

        strip_components = asset.get("strip_components", 0)
        if not isinstance(strip_components, int) or strip_components < 0:
            errors.append(_err(f"assets[{index}].strip_components must be a non-negative integer"))

    required_kinds = {"daemon_runtime", "pack_projects", "toolchain"}
    missing = required_kinds - seen_kinds
    if missing:
        errors.append(_err(f"missing required asset kinds: {sorted(missing)}"))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"manifest error: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print("manifest error: root must be an object", file=sys.stderr)
        return 2

    errors = validate(data)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2

    print(f"manifest ok: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
