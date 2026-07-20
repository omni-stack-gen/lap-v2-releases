#!/usr/bin/env python3
"""Build LAP v2 release assets and manifest.

The builder consumes a release config, packages each configured source
directory into a tarball, computes SHA256 hashes, and writes a manifest that
the interactive installer can consume.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tarfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_KINDS = {"daemon_runtime", "pack_projects", "toolchain"}
VALID_TARGETS = {"install_root", "packages_root", "toolchain_root"}


class BuildConfigError(ValueError):
    """Release config is invalid."""


@dataclass(frozen=True)
class AssetConfig:
    id: str
    kind: str
    version: str
    source_dir: Path
    archive_name: str
    target: str
    required_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseConfig:
    version: str
    default_saas_url: str
    asset_base_url: str
    assets: tuple[AssetConfig, ...]


def _require_str(obj: dict[str, Any], key: str, *, ctx: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise BuildConfigError(f"{ctx}.{key} is required")
    return value


def load_config(path: Path) -> ReleaseConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BuildConfigError("config root must be an object")

    version = _require_str(data, "version", ctx="config")
    default_saas_url = _require_str(data, "default_saas_url", ctx="config")
    asset_base_url = _require_str(data, "asset_base_url", ctx="config")

    raw_assets = data.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise BuildConfigError("config.assets must be a non-empty list")

    seen_ids: set[str] = set()
    seen_kinds: set[str] = set()
    assets: list[AssetConfig] = []
    for index, raw in enumerate(raw_assets):
        ctx = f"assets[{index}]"
        if not isinstance(raw, dict):
            raise BuildConfigError(f"{ctx} must be an object")

        asset_id = _require_str(raw, "id", ctx=ctx)
        if asset_id in seen_ids:
            raise BuildConfigError(f"duplicate asset id: {asset_id}")
        seen_ids.add(asset_id)

        kind = _require_str(raw, "kind", ctx=ctx)
        if kind not in VALID_KINDS:
            raise BuildConfigError(f"{ctx}.kind must be one of {sorted(VALID_KINDS)}")
        seen_kinds.add(kind)

        target = _require_str(raw, "target", ctx=ctx)
        if target not in VALID_TARGETS:
            raise BuildConfigError(f"{ctx}.target must be one of {sorted(VALID_TARGETS)}")

        required_paths = raw.get("required_paths", [])
        if not isinstance(required_paths, list) or not all(
            isinstance(item, str) and item for item in required_paths
        ):
            raise BuildConfigError(f"{ctx}.required_paths must be a list of strings")

        archive_name = _require_str(raw, "archive_name", ctx=ctx)
        if not archive_name.endswith((".tar.gz", ".tgz")):
            raise BuildConfigError(f"{ctx}.archive_name must end with .tar.gz or .tgz")
        if "/" in archive_name or archive_name in {".", ".."}:
            raise BuildConfigError(f"{ctx}.archive_name must be a basename")

        assets.append(
            AssetConfig(
                id=asset_id,
                kind=kind,
                version=_require_str(raw, "version", ctx=ctx),
                source_dir=Path(_require_str(raw, "source_dir", ctx=ctx)),
                archive_name=archive_name,
                target=target,
                required_paths=tuple(required_paths),
            )
        )

    # Public bootstrap releases only require the daemon runtime. Board Pack and
    # toolchain assets are selected and served by SaaS/PocketBase after pairing.
    missing = {"daemon_runtime"} - seen_kinds
    if missing:
        raise BuildConfigError(f"missing required asset kinds: {sorted(missing)}")

    return ReleaseConfig(
        version=version,
        default_saas_url=default_saas_url,
        asset_base_url=asset_base_url,
        assets=tuple(assets),
    )


def validate_sources(config: ReleaseConfig) -> None:
    for asset in config.assets:
        if not asset.source_dir.is_dir():
            raise BuildConfigError(f"{asset.id}: source_dir is not a directory: {asset.source_dir}")
        for required in asset.required_paths:
            if required.startswith("/") or ".." in Path(required).parts:
                raise BuildConfigError(f"{asset.id}: invalid required path: {required}")
            candidate = asset.source_dir / required
            if not candidate.exists():
                raise BuildConfigError(
                    f"{asset.id}: required path missing under source_dir: {required}"
                )


def _iter_archive_paths(root: Path) -> list[Path]:
    paths = [
        path
        for path in root.rglob("*")
        if path.is_dir() or path.is_file() or path.is_symlink()
    ]
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def make_tarball(source_dir: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as raw:
        # Keep mirror builds byte-identical: gzip otherwise embeds the current
        # timestamp and tar members inherit mutable source-tree mtimes.
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tf:
                for path in _iter_archive_paths(source_dir):
                    rel = path.relative_to(source_dir).as_posix()
                    info = tf.gettarinfo(str(path), arcname=rel)
                    # Preserve executable mode bits while normalizing metadata.
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if path.is_symlink():
                        tf.addfile(info)
                    elif path.is_dir():
                        tf.addfile(info)
                    else:
                        with path.open("rb") as fh:
                            tf.addfile(info, fh)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_url(base_url: str, dist_dir: Path, archive_name: str) -> str:
    if "{dist_dir}" in base_url:
        resolved = base_url.replace("{dist_dir}", str(dist_dir.resolve()))
    else:
        resolved = base_url.rstrip("/")
    return f"{resolved.rstrip('/')}/{archive_name}"


def with_release_version(config: ReleaseConfig, version: str) -> ReleaseConfig:
    return replace(
        config,
        version=version,
        assets=tuple(replace(asset, version=version) for asset in config.assets),
    )


def write_sha256sums(paths: list[Path], dest: Path) -> None:
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(paths, key=lambda p: p.name)]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_release(config: ReleaseConfig, out_dir: Path, installer: Path) -> Path:
    dist_dir = out_dir / config.version
    dist_dir.mkdir(parents=True, exist_ok=True)

    manifest_assets: list[dict[str, Any]] = []
    release_files: list[Path] = []
    for asset in config.assets:
        archive_path = dist_dir / asset.archive_name
        make_tarball(asset.source_dir, archive_path)
        release_files.append(archive_path)
        manifest_assets.append(
            {
                "id": asset.id,
                "kind": asset.kind,
                "version": asset.version,
                "url": asset_url(config.asset_base_url, dist_dir, asset.archive_name),
                "sha256": sha256_file(archive_path),
                "archive": "tar.gz",
                "target": asset.target,
                "strip_components": 0,
                "required_paths": list(asset.required_paths),
            }
        )

    manifest = {
        "schema_version": 1,
        "release": {
            "version": config.version,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "defaults": {
            "saas_url": config.default_saas_url,
        },
        "assets": manifest_assets,
    }
    manifest_path = dist_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    release_files.append(manifest_path)

    installer_dest = dist_dir / "install.sh"
    shutil.copy2(installer, installer_dest)
    installer_dest.chmod(0o755)
    release_files.append(installer_dest)

    write_sha256sums(release_files, dist_dir / "SHA256SUMS")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--installer",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "install.sh",
        help="Installer script to copy into the release directory.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate config shape only; do not require source dirs or write files.",
    )
    parser.add_argument(
        "--validate-sources",
        action="store_true",
        help="Validate source dirs and required paths without writing tarballs.",
    )
    parser.add_argument(
        "--asset-base-url",
        help=(
            "Override config.asset_base_url in the generated manifest. "
            "Use this when serving a test release over HTTP from another host."
        ),
    )
    parser.add_argument(
        "--default-saas-url",
        help="Override config.default_saas_url in the generated manifest.",
    )
    parser.add_argument(
        "--release-version",
        help="Override config.version and the generated manifest release.version.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        if args.release_version:
            config = with_release_version(config, args.release_version)
        if args.asset_base_url:
            config = replace(config, asset_base_url=args.asset_base_url)
        if args.default_saas_url:
            config = replace(config, default_saas_url=args.default_saas_url)
        if args.check_only:
            print(f"release config ok: {args.config}")
            return 0
        validate_sources(config)
        if args.validate_sources:
            print(f"release sources ok: {args.config}")
            return 0
        if not args.installer.is_file():
            raise BuildConfigError(f"installer is not a file: {args.installer}")
        manifest_path = build_release(config, args.out_dir, args.installer)
    except (OSError, json.JSONDecodeError, BuildConfigError) as exc:
        print(f"release build error: {exc}", file=os.sys.stderr)
        return 2

    print(f"release built: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
