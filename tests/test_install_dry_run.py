from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import tarfile
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
EXAMPLE = ROOT / "examples" / "manifest.example.json"


class InstallDryRunTests(unittest.TestCase):
    def test_installer_fetches_default_manifest_from_saas_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_dir = tmp_path / "v1" / "assets" / "lap-release"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "manifest.json").write_text(
                EXAMPLE.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            class QuietHandler(SimpleHTTPRequestHandler):
                def log_message(self, _format: str, *_args: object) -> None:
                    return

            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                partial(QuietHandler, directory=tmp),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                saas_url = f"http://127.0.0.1:{server.server_port}"
                env = {
                    **os.environ,
                    "LAP_INSTALL_DRY_RUN": "1",
                    "LAP_SAAS_URL": saas_url,
                    "SUDO_USER": os.environ.get("USER", "laptest"),
                }
                # Prompts: SaaS URL, user, install root, state dir, workspace,
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
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            f"release manifest: {saas_url}/v1/assets/lap-release/manifest.json",
            result.stdout,
        )
        self.assertIn("DRY RUN complete", result.stdout)

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
        self.assertIn("dry run: would write /home/", result.stdout)
        self.assertIn("lap-pack-projects (pack_projects v0.1.1-example) ->", result.stdout)
        self.assertIn("[on demand]", result.stdout)
        self.assertIn("lazy asset lap-toolchains", result.stdout)

    def test_installer_slint_preview_opt_in(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_INSTALL_SLINT_PREVIEW": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
        # Same 8 answers as the default flow — opt-in is env-gated, no new prompt.
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
        self.assertIn("slint preview enabled: added GUI/font packages", result.stdout)
        self.assertIn("would provision slint-viewer", result.stdout)
        self.assertIn("slint preview:    enabled", result.stdout)
        # No prebuilt URL → cargo build deps are added so the fallback
        # `cargo install slint-viewer` can compile from source.
        self.assertIn("added cargo build deps", result.stdout)

    def test_installer_slint_preview_prebuilt_url_skips_build_deps(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_INSTALL_SLINT_PREVIEW": "1",
            "LAP_SLINT_VIEWER_URL": "https://example.invalid/slint-viewer.tar.gz",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
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
        self.assertIn("slint preview enabled: added GUI/font packages", result.stdout)
        # A prebuilt binary is supplied → no need for cargo build deps.
        self.assertNotIn("added cargo build deps", result.stdout)

    def test_installer_slint_preview_off_by_default(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
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
        # Headless default: no slint-viewer provisioning, no extra prompt/output.
        self.assertNotIn("slint-viewer", result.stdout)
        self.assertNotIn("slint preview", result.stdout)

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
            "http://127.0.0.1:18000/v1/assets/lap-release/manifest.json",
        )

    def test_installer_uses_configured_saas_url_for_default_manifest(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_SAAS_URL": "http://192.168.1.108:18000/",
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
            "http://192.168.1.108:18000/v1/assets/lap-release/manifest.json",
        )

    def test_installer_pair_default_can_be_separate_from_asset_url(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "LAP_PAIR_API_URL": "http://192.168.1.108:38082/",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
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
        self.assertIn("default pair URL: http://192.168.1.108:38082", result.stdout)

    def test_installer_can_pin_release_tag(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_DAEMON_VERSION": "v1.2.3",
            "LAP_RELEASE_SOURCE": "github",
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

    def test_installer_gitee_source_uses_gitee_mirror(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_SOURCE": "gitee",
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
            "https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.2/manifest.json",
        )

    def test_installer_gitee_source_with_pinned_version(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_SOURCE": "gitee",
            "LAP_RELEASE_VERSION": "v0.1.2",
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
            "https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.2/manifest.json",
        )

    def test_installer_rejects_unknown_release_source(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_SOURCE": "bogus",
            "SUDO_USER": os.environ.get("USER", "laptest"),
        }
        # release_base_url is the top-level command here, so its `|| die` runs in
        # this shell and aborts; via manifest_url it would be nested in $(...).
        result = subprocess.run(
            ["bash", "-c", f"source {INSTALLER}; release_base_url"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown LAP_RELEASE_SOURCE", result.stderr + result.stdout)

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

    def test_systemd_unit_allows_configured_asset_root_extra_binds(self) -> None:
        installer_text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            "Environment=LAP_BASH_ALLOWED_EXTRA_BIND_PREFIXES=$PACKAGES_ROOT,$TOOLCHAIN_ROOT",
            installer_text,
        )
        self.assertIn("Environment=LAP_RELEASE_MANIFEST_URL=$release_manifest_url", installer_text)
        self.assertIn("Environment=LAP_RELEASE_MANIFEST_PATH=$release_manifest_path", installer_text)
        self.assertIn("Environment=LAP_ASSET_CACHE_DIR=$asset_cache", installer_text)

    def test_installer_persists_runtime_asset_roots_and_owns_no_registry(self) -> None:
        installer_text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("LAP_PACKAGES_ROOT=$PACKAGES_ROOT", installer_text)
        self.assertIn("LAP_TOOLCHAINS_ROOT=$TOOLCHAIN_ROOT", installer_text)
        self.assertIn("LAP_EXPECTED_UID=$DAEMON_UID", installer_text)
        self.assertNotIn("write_toolchains_registry", installer_text)

    def test_daemon_runtime_upgrade_preserves_lazy_asset_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_root = root / "lap"
            old_lap = install_root / "bin" / "lap"
            old_lap.parent.mkdir(parents=True)
            old_lap.write_text("old runtime\n", encoding="utf-8")
            old_lap.chmod(0o755)
            (install_root / ".venv").mkdir()
            (install_root / ".venv" / "old-only").write_text("old", encoding="utf-8")

            packages = root / "packages"
            pack_marker = packages / "Pack_FD_F1" / "pack.sh"
            pack_marker.parent.mkdir(parents=True)
            pack_marker.write_text("pack", encoding="utf-8")
            toolchains = root / "toolchains"
            toolchains.mkdir()
            registry = toolchains / "toolchains.toml"
            registry.write_text("[toolchains.F1]\nroot='keep'\n", encoding="utf-8")

            runtime_source = root / "runtime-source"
            new_lap = runtime_source / "bin" / "lap"
            new_lap.parent.mkdir(parents=True)
            new_lap.write_text("new runtime\n", encoding="utf-8")
            new_lap.chmod(0o755)
            (runtime_source / ".venv").mkdir()
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for path in sorted(runtime_source.rglob("*")):
                    tf.add(path, arcname=path.relative_to(runtime_source))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "lap-daemon-runtime",
                                "kind": "daemon_runtime",
                                "version": "v-next",
                                "url": archive.as_uri(),
                                "sha256": digest,
                                "archive": "tar.gz",
                                "target": "install_root",
                                "strip_components": 0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            scratch = root / "scratch"
            scratch.mkdir()
            user = os.environ.get("USER", "laptest")
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={user}
DAEMON_GROUP={user}
INSTALL_ROOT={install_root}
PACKAGES_ROOT={packages}
TOOLCHAIN_ROOT={toolchains}
preflight_paths
install_assets {manifest} {scratch}
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(old_lap.read_text(encoding="utf-8"), "new runtime\n")
            self.assertFalse((install_root / ".venv" / "old-only").exists())
            self.assertEqual(pack_marker.read_text(encoding="utf-8"), "pack")
            self.assertEqual(
                registry.read_text(encoding="utf-8"),
                "[toolchains.F1]\nroot='keep'\n",
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
