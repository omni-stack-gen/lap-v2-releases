from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_release.py"
VALIDATOR = ROOT / "scripts" / "validate_manifest.py"


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_source_tree(root: Path) -> tuple[Path, Path, Path]:
    runtime = root / "runtime"
    pack = root / "lap-packages"
    toolchains = root / "toolchains"

    _write(runtime / "bin" / "lap", "#!/bin/sh\n")
    (runtime / "bin" / "lap").chmod(0o755)

    _write(pack / "pack.sh", "#!/bin/sh\n")
    (pack / "pack.sh").chmod(0o755)
    (pack / ".venv").mkdir(parents=True)
    (pack / "Pack_FD_F1_R88R30_ADB_SPINOR").mkdir()
    (pack / "Pack_RL_F1s_DV10_2_SPINOR").mkdir()

    _write(toolchains / "bin" / "cc", "#!/bin/sh\n")
    return runtime, pack, toolchains


def _config(path: Path, runtime: Path, pack: Path, toolchains: Path) -> Path:
    config = {
        "version": "v-test",
        "default_saas_url": "https://api.omnistack.io",
        "asset_base_url": "file://{dist_dir}",
        "assets": [
            {
                "id": "lap-daemon-runtime",
                "kind": "daemon_runtime",
                "version": "v-test",
                "source_dir": str(runtime),
                "archive_name": "lap-daemon-runtime.tar.gz",
                "target": "install_root",
                "required_paths": ["bin/lap"],
            },
            {
                "id": "lap-pack-projects",
                "kind": "pack_projects",
                "version": "v-test",
                "source_dir": str(pack),
                "archive_name": "lap-pack-projects.tar.gz",
                "target": "packages_root",
                "required_paths": [
                    ".venv",
                    "pack.sh",
                    "Pack_FD_F1_R88R30_ADB_SPINOR",
                    "Pack_RL_F1s_DV10_2_SPINOR",
                ],
            },
            {
                "id": "lap-toolchains",
                "kind": "toolchain",
                "version": "v-test",
                "source_dir": str(toolchains),
                "archive_name": "lap-toolchains.tar.gz",
                "target": "toolchain_root",
                "required_paths": [],
            },
        ],
    }
    config_path = path / "release-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


class BuildReleaseTests(unittest.TestCase):
    def test_build_release_writes_manifest_and_tarballs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runtime, pack, toolchains = _make_source_tree(tmp_path / "src")
            config_path = _config(tmp_path, runtime, pack, toolchains)
            out_dir = tmp_path / "dist"

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    "--config",
                    str(config_path),
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            manifest = out_dir / "v-test" / "manifest.json"
            self.assertTrue(manifest.exists())
            self.assertTrue((out_dir / "v-test" / "lap-pack-projects.tar.gz").exists())

            validate = subprocess.run(
                [sys.executable, str(VALIDATOR), str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)

            with tarfile.open(out_dir / "v-test" / "lap-pack-projects.tar.gz") as tf:
                names = set(tf.getnames())
            self.assertIn("pack.sh", names)
            self.assertIn("Pack_FD_F1_R88R30_ADB_SPINOR", names)

    def test_validate_sources_rejects_wrong_pack_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runtime, pack, toolchains = _make_source_tree(tmp_path / "src")
            (pack / "pack.sh").unlink()
            config_path = _config(tmp_path, runtime, pack, toolchains)
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    "--config",
                    str(config_path),
                    "--validate-sources",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("required path missing", result.stderr)
            self.assertIn("pack.sh", result.stderr)

    def test_build_release_allows_url_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runtime, pack, toolchains = _make_source_tree(tmp_path / "src")
            config_path = _config(tmp_path, runtime, pack, toolchains)
            out_dir = tmp_path / "dist"

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    "--config",
                    str(config_path),
                    "--out-dir",
                    str(out_dir),
                    "--asset-base-url",
                    "http://192.0.2.10:18080",
                    "--default-saas-url",
                    "http://192.0.2.20:38080",
                    "--release-version",
                    "v-override",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            manifest = json.loads((out_dir / "v-override" / "manifest.json").read_text())
            self.assertEqual(manifest["release"]["version"], "v-override")
            self.assertEqual(manifest["defaults"]["saas_url"], "http://192.0.2.20:38080")
            self.assertEqual(
                manifest["assets"][0]["url"],
                "http://192.0.2.10:18080/lap-daemon-runtime.tar.gz",
            )


if __name__ == "__main__":
    unittest.main()
