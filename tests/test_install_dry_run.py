from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
EXAMPLE = ROOT / "examples" / "manifest.example.json"


class InstallDryRunTests(unittest.TestCase):
    def test_installer_dry_run_accepts_defaults_and_skips_pair(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
        # Prompts: manifest URL, user, install root, state dir, workspace,
        # packages, toolchains, proceed, pair now.
        answers = "\n\n\n\n\n\n\ny\nn\n"
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            input=answers,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("DRY RUN complete", result.stdout)
        self.assertIn("lap-daemon-runtime", result.stdout)
        self.assertIn("pair status:      skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
