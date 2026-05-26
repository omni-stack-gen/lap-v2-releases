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
        # Prompts: user, install root, state dir, workspace, packages,
        # toolchains, proceed, pair now.
        answers = "\n\n\n\n\n\ny\nn\n"
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

    def test_installer_defaults_to_release_only_manifest_url(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_PACKAGE_BASE": "http://gitlab.example.com/api/v4/projects/5/packages/generic/lap-v2-release",
            "LAP_DAEMON_VERSION": "v1.2.3",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
        result = subprocess.run(
            ["bash", "-c", f"source {INSTALLER}; manifest_url"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            result.stdout.strip(),
            "http://gitlab.example.com/api/v4/projects/5/packages/generic/lap-v2-release/v1.2.3/manifest.json",
        )

    def test_installer_rejects_typo_home_path(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": "dpower",
        }
        # Prompts: user, install root, state dir. State dir intentionally
        # points at a misspelled home directory.
        answers = "dpower\n\n/home/dopwer/lap_workspace/\n"
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            input=answers,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("State dir points under /home/dopwer", result.stderr)
        self.assertIn("Did you mean /home/dpower", result.stderr)

    def test_installer_normalizes_trailing_slash_defaults(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": "dpower",
        }
        answers = (
            "dpower\n"
            "\n"
            "/home/dpower/lap_workspace/\n"
            "\n"
            "/home/dpower/lap-packages/\n"
            "\n"
            "y\n"
            "n\n"
        )
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
        self.assertIn("state dir:        /home/dpower/lap_workspace", result.stdout)
        self.assertIn(
            "workspace root:   /home/dpower/lap_workspace/workspace",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
