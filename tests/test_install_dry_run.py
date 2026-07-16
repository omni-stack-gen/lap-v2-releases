from __future__ import annotations

import hashlib
import io
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
    def test_minimal_system_bootstraps_python_before_manifest_processing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "apt.log"
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
command() {{
  if [[ "$1" == "-v" ]]; then
    case "$2" in
      python3) return 1 ;;
      apt-get|curl|tar|sha256sum) return 0 ;;
    esac
  fi
  builtin command "$@"
}}
apt-get() {{ printf '%s\\n' "$*" >> {calls}; }}
bootstrap_required_commands
"""
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                ["update", "install -y --no-install-recommends python3"],
            )

    def test_fresh_install_materializes_only_daemon_runtime_and_empty_asset_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_source = root / "runtime-source"
            runtime_bin = runtime_source / "bin" / "lap"
            runtime_bin.parent.mkdir(parents=True)
            runtime_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            runtime_bin.chmod(0o755)
            (runtime_source / ".venv").mkdir()

            runtime_archive = root / "runtime.tar.gz"
            with tarfile.open(runtime_archive, "w:gz") as tf:
                for path in sorted(runtime_source.rglob("*")):
                    tf.add(path, arcname=path.relative_to(runtime_source))
            runtime_digest = hashlib.sha256(runtime_archive.read_bytes()).hexdigest()

            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "lap-daemon-runtime",
                                "kind": "daemon_runtime",
                                "version": "v-next",
                                "url": runtime_archive.as_uri(),
                                "sha256": runtime_digest,
                                "archive": "tar.gz",
                                "target": "install_root",
                                "strip_components": 0,
                            },
                            {
                                "id": "lap-pack-projects",
                                "kind": "pack_projects",
                                "version": "v-pack",
                                "url": "https://example.invalid/never-download-pack.tar.gz",
                                "sha256": "1" * 64,
                                "archive": "tar.gz",
                                "target": "packages_root",
                                "strip_components": 0,
                            },
                            {
                                "id": "lap-toolchains",
                                "kind": "toolchain",
                                "version": "v-toolchain",
                                "url": "https://example.invalid/never-download-toolchain.tar.gz",
                                "sha256": "2" * 64,
                                "archive": "tar.gz",
                                "target": "toolchain_root",
                                "strip_components": 0,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            install_root = root / "lap"
            state_dir = root / "state"
            workspace_root = root / "workspace"
            packages_root = root / "packages"
            toolchains_root = root / "toolchains"
            scratch = root / "scratch"
            scratch.mkdir()
            daemon_user = os.environ.get("USER", "laptest")
            saas_url = "http://192.168.252.152:18000"
            manifest_url = f"{saas_url}/v1/assets/lap-release/manifest.json"
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={daemon_user}
DAEMON_GROUP={daemon_user}
DAEMON_UID={os.geteuid()}
INSTALL_ROOT={install_root}
STATE_DIR={state_dir}
WORKSPACE_ROOT={workspace_root}
PACKAGES_ROOT={packages_root}
TOOLCHAIN_ROOT={toolchains_root}
create_dirs
write_release_manifest_cache {manifest} {manifest_url} {saas_url}
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
            self.assertTrue((install_root / "bin" / "lap").is_file())
            self.assertEqual(list(packages_root.iterdir()), [])
            self.assertEqual(list(toolchains_root.iterdir()), [])
            self.assertEqual(list((state_dir / "assets").iterdir()), [])
            self.assertEqual(packages_root.stat().st_uid, os.geteuid())
            self.assertEqual(toolchains_root.stat().st_uid, os.geteuid())
            self.assertEqual((state_dir / "assets").stat().st_uid, os.geteuid())
            source_env = (state_dir / "release-source.env").read_text(encoding="utf-8")
            self.assertIn(f"LAP_RELEASE_MANIFEST_URL={manifest_url}\n", source_env)
            self.assertIn(f"LAP_RELEASE_SAAS_URL={saas_url}\n", source_env)
            self.assertIn(f"LAP_ASSET_CACHE_DIR={state_dir / 'assets'}\n", source_env)
            self.assertIn(f"LAP_PACKAGES_ROOT={packages_root}\n", source_env)
            self.assertIn(f"LAP_TOOLCHAINS_ROOT={toolchains_root}\n", source_env)
            self.assertIn(f"LAP_EXPECTED_UID={os.geteuid()}\n", source_env)
            self.assertIn("lap-pack-projects", result.stdout)
            self.assertIn("lap-toolchains", result.stdout)
            self.assertNotIn("never-download", result.stdout)

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
                explicit_env = {
                    **os.environ,
                    "LAP_INSTALL_DRY_RUN": "1",
                    "LAP_RELEASE_MANIFEST_URL": (
                        f"{saas_url}/v1/assets/lap-release/manifest.json"
                    ),
                    "SUDO_USER": os.environ.get("USER", "laptest"),
                }
                explicit_result = subprocess.run(
                    ["bash", str(INSTALLER)],
                    input=answers,
                    capture_output=True,
                    text=True,
                    env=explicit_env,
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
        self.assertEqual(
            explicit_result.returncode,
            0,
            explicit_result.stderr + explicit_result.stdout,
        )
        self.assertIn(f"default SaaS URL: {saas_url}", explicit_result.stdout)
        self.assertIn(
            "runtime asset manifest: "
            f"{saas_url}/v1/assets/lap-release/manifest.json",
            explicit_result.stdout,
        )

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

    def test_installer_separates_release_bootstrap_from_runtime_asset_manifest(
        self,
    ) -> None:
        saas_url = "http://192.168.252.152:18000"
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_RELEASE_MANIFEST_URL": f"file://{EXAMPLE}",
            "LAP_SAAS_URL": saas_url,
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
        self.assertIn(f"release manifest: file://{EXAMPLE}", result.stdout)
        self.assertIn(
            "runtime asset manifest: "
            f"{saas_url}/v1/assets/lap-release/manifest.json",
            result.stdout,
        )
        self.assertIn(f"default SaaS URL: {saas_url}", result.stdout)

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
            "https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.3/manifest.json",
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

    def test_installer_rejects_saas_url_with_whitespace(self) -> None:
        env = {
            **os.environ,
            "LAP_INSTALL_DRY_RUN": "1",
            "LAP_TEST_URL": "http://192.168.1.108:18000\nInjected=value",
        }
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source {INSTALLER}; validate_saas_url "$LAP_TEST_URL"',
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SaaS URL must not contain whitespace", result.stderr)

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
            "Environment=LAP_BASH_ALLOWED_EXTRA_RO_BIND_PREFIXES=$PACKAGES_ROOT,$TOOLCHAIN_ROOT",
            installer_text,
        )
        self.assertIn(
            "Environment=LAP_RELEASE_MANIFEST_URL=$runtime_asset_manifest_url",
            installer_text,
        )
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
            self.assertIn("systemctl enable lap.service", helper_text)
            self.assertIn("systemctl restart lap.service", helper_text)

    def test_runtime_archive_rejects_links_before_replacing_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_root = root / "lap"
            (install_root / "bin").mkdir(parents=True)
            (install_root / "bin" / "lap").write_text("old\n", encoding="utf-8")
            (install_root / "bin" / "lap").chmod(0o755)
            (install_root / ".venv").mkdir()
            archive = root / "malicious.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                lap = tarfile.TarInfo("bin/lap")
                payload = b"new\n"
                lap.size = len(payload)
                lap.mode = 0o755
                tf.addfile(lap, io.BytesIO(payload))
                venv = tarfile.TarInfo(".venv")
                venv.type = tarfile.DIRTYPE
                tf.addfile(venv)
                link = tarfile.TarInfo(".venv/escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../escaped"
                tf.addfile(link)

            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={os.environ.get("USER", "laptest")}
DAEMON_GROUP={os.environ.get("USER", "laptest")}
INSTALL_ROOT={install_root}
RUNTIME_PREVIOUS_PATH=""
install_daemon_runtime_archive {archive} 0
"""
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink target escapes runtime root", result.stderr)
            self.assertEqual(
                (install_root / "bin" / "lap").read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertFalse((root / "escaped").exists())

    def test_runtime_archive_allows_internal_relative_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for directory in ("bin", ".venv", ".venv/lib"):
                    info = tarfile.TarInfo(directory)
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tf.addfile(info)
                lap = tarfile.TarInfo("bin/lap")
                payload = b"#!/bin/sh\n"
                lap.size = len(payload)
                lap.mode = 0o755
                tf.addfile(lap, io.BytesIO(payload))
                link = tarfile.TarInfo(".venv/lib64")
                link.type = tarfile.SYMTYPE
                link.linkname = "lib"
                tf.addfile(link)

            install_root = root / "lap"
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={os.environ.get("USER", "laptest")}
DAEMON_GROUP={os.environ.get("USER", "laptest")}
INSTALL_ROOT={install_root}
RUNTIME_PREVIOUS_PATH=""
install_daemon_runtime_archive {archive} 0
"""
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((install_root / ".venv" / "lib64").is_symlink())
            self.assertEqual(os.readlink(install_root / ".venv" / "lib64"), "lib")

    def test_runtime_activation_can_atomically_roll_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_root = root / "lap"
            (install_root / "bin").mkdir(parents=True)
            old_lap = install_root / "bin" / "lap"
            old_lap.write_text("old\n", encoding="utf-8")
            old_lap.chmod(0o755)
            (install_root / ".venv").mkdir()

            source = root / "source"
            (source / "bin").mkdir(parents=True)
            new_lap = source / "bin" / "lap"
            new_lap.write_text("new\n", encoding="utf-8")
            new_lap.chmod(0o755)
            (source / ".venv").mkdir()
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for path in sorted(source.rglob("*")):
                    tf.add(path, arcname=path.relative_to(source), recursive=False)

            script = f"""
set -Eeuo pipefail
source {INSTALLER}
chown() {{ :; }}
DAEMON_USER={os.environ.get("USER", "laptest")}
DAEMON_GROUP={os.environ.get("USER", "laptest")}
INSTALL_ROOT={install_root}
RUNTIME_PREVIOUS_PATH=""
install_daemon_runtime_archive {archive} 0
[[ "$(cat {install_root / 'bin' / 'lap'})" == "new" ]]
rollback_runtime_upgrade
[[ "$(cat {install_root / 'bin' / 'lap'})" == "old" ]]
"""
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_active_service_is_restarted_without_repairing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "systemctl.log"
            script = f"""
set -Eeuo pipefail
source {INSTALLER}
systemctl() {{ printf '%s\\n' "$*" >> {calls}; return 0; }}
SERVICE_STARTED=false
restart_active_service
[[ "$SERVICE_STARTED" == "true" ]]
"""
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("is-active --quiet lap.service", calls.read_text())
            self.assertIn("restart lap.service", calls.read_text())


if __name__ == "__main__":
    unittest.main()
