from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_manifest.py"
EXAMPLE = ROOT / "examples" / "manifest.example.json"


class ManifestValidatorTests(unittest.TestCase):
    def test_example_manifest_is_valid(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(EXAMPLE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manifest ok", result.stdout)

    def test_toolchain_asset_is_optional(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["assets"] = [
            asset for asset in data["assets"] if asset["kind"] != "toolchain"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pack_project_asset_is_managed_outside_bootstrap_manifest(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["assets"] = [
            asset for asset in data["assets"] if asset["kind"] == "daemon_runtime"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
