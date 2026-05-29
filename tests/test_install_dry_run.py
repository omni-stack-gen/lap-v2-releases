from __future__ import annotations

import os
import subprocess
import tempfile
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
        self.assertIn("dry run: would prepare bwrap user namespace sysctls", result.stdout)
        self.assertIn("dry run: would configure serial/USB permissions", result.stdout)
        self.assertIn("dry run: would enable linger", result.stdout)

    def test_installer_defaults_to_release_only_manifest_url(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
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
            "https://github.com/omni-stack-gen/lap-v2-releases/releases/latest/download/manifest.json",
        )

    def test_installer_can_pin_github_release_tag(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
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
            "https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v1.2.3/manifest.json",
        )

    def test_installer_keeps_package_base_override_for_internal_mirrors(self) -> None:
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

    def test_installer_rejects_websocket_saas_url(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": "dpower",
        }
        # Prompts: user, install root, state dir, workspace, packages,
        # toolchains, proceed, pair now, pair code, SaaS HTTP URL.
        answers = (
            "dpower\n"
            "\n"
            "/home/dpower/lap_workspace\n"
            "\n"
            "/home/dpower/lap-packages\n"
            "\n"
            "y\n"
            "y\n"
            "DEV-12345\n"
            "ws://192.168.1.108:38081/v2/wss\n"
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
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SaaS URL must be an HTTP pair API base URL", result.stderr)

    def test_installer_treats_no_as_pair_code_skip(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": "dpower",
        }
        # If the user accidentally enters n at the pair-code prompt, treat it as
        # an intent to skip instead of sending "n" to the pair API.
        answers = (
            "dpower\n"
            "\n"
            "/home/dpower/lap_workspace\n"
            "\n"
            "/home/dpower/lap-packages\n"
            "\n"
            "y\n"
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
        self.assertIn("pair code 'n' means skip", result.stdout)
        self.assertIn("pair status:      skipped", result.stdout)

    def test_skipped_pair_summary_uses_state_bound_pair_helper(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": "dpower",
        }
        answers = (
            "dpower\n"
            "\n"
            "/home/dpower/lap_workspace\n"
            "\n"
            "/home/dpower/lap-packages\n"
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
        self.assertIn(
            "sudo /home/dpower/lap/bin/lap-pair <PAIR_CODE> --saas-url <SAAS_HTTP_URL>",
            result.stdout,
        )
        self.assertNotIn("sudo -u dpower LAP_STATE_DIR=", result.stdout)

    def test_systemd_unit_allows_configured_pack_root_extra_binds(self) -> None:
        installer_text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            "Environment=LAP_BASH_ALLOWED_EXTRA_BIND_PREFIXES=$PACKAGES_ROOT",
            installer_text,
        )

    def test_installer_configures_lap_device_permissions(self) -> None:
        installer_text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("udev", installer_text)
        self.assertIn("/etc/udev/rules.d/70-lap-devices.rules", installer_text)
        self.assertIn("usermod -aG dialout,plugdev", installer_text)
        self.assertIn('ATTRS{idVendor}=="1a86"', installer_text)
        self.assertIn('ATTRS{idProduct}=="7523"', installer_text)
        self.assertIn('ATTRS{idVendor}=="33c3"', installer_text)
        self.assertIn('ENV{ID_USB_INTERFACES}=="*:ff4201:*"', installer_text)
        self.assertIn("udevadm control --reload-rules", installer_text)

    def test_write_pair_helper_bakes_installer_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            install_root = tmp_path / "lap"
            state_dir = tmp_path / "lap-workspace"
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={os.environ.get("USER", "laptest")}
DAEMON_GROUP={os.environ.get("USER", "laptest")}
DAEMON_UID=1234
INSTALL_ROOT={install_root}
STATE_DIR={state_dir}
write_pair_helper http://192.168.1.108:38082
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            helper = install_root / "bin" / "lap-pair"
            helper_text = helper.read_text(encoding="utf-8")
            syntax = subprocess.run(
                ["bash", "-n", str(helper)],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr + syntax.stdout)

            self.assertIn("DAEMON_UID=1234", helper_text)
            self.assertIn(f"STATE_DIR={state_dir}", helper_text)
            self.assertIn('env LAP_STATE_DIR="$STATE_DIR"', helper_text)
            self.assertIn("identity_file=\"$STATE_DIR/identity.json\"", helper_text)
            self.assertIn('loginctl enable-linger "$DAEMON_USER"', helper_text)
            self.assertIn('systemctl start "user@$DAEMON_UID.service"', helper_text)
            self.assertIn('bus_path="$runtime_dir/bus"', helper_text)
            self.assertIn("LAP_ALLOW_INSECURE_WS=1", helper_text)
            self.assertIn("systemctl enable --now lap.service", helper_text)


if __name__ == "__main__":
    unittest.main()
