# Customer Release Install

This is the customer-facing distribution shape. Customers receive one install
command and do not need access to the source/build repository.

## Install v0.1.4

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github \
             LAP_PAIR_API_URL=http://<omnistack-host>:38082 bash
```

This command exposes one customer-specific endpoint: the pair API. Do not set
`LAP_SAAS_URL` in the normal public-release flow.

The installer script, bootstrap manifest, and daemon runtime come from the
GitHub release. During pairing, `POST /v1/pair` returns both the daemon
WebSocket endpoint and the OmniStack managed-asset facade:

```text
asset_base_url=http://<omnistack-host>:18000
```

LAP persists that value in `identity.json` and prefers it over the install-time
fallback for Pack and toolchain downloads. The installer installs the daemon
runtime, caches the bootstrap manifest, writes `lap.service`, and optionally
pairs the daemon during the same flow. Pack projects and toolchains remain
on-demand assets.

The daemon bootstrap source and runtime asset source are separate. GitHub,
Gitee, or a private release mirror may provide `install.sh` and the daemon
runtime archive. After pairing, selector-specific Pack and toolchain metadata
and bytes use the facade advertised by the pair response:

```text
<SaaS base URL>/v1/assets/lap-release/manifest.json
```

Operators may proactively materialize or inspect one asset with the installed
CLI. These commands must run as the daemon user:

```bash
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --soc F1
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --board <manifest.project>
sudo -u <daemon-user> -H <install-root>/bin/lap assets status --soc F1 --json
```

The CLI first reads the paired asset URL from `<state-dir>/identity.json`.
Install-time values in `<state-dir>/release-source.env` remain a compatibility
fallback for older pair servers. Set `LAP_STATE_DIR=<state-dir>` when a
non-default state directory was selected.

`--soc` resolves one SoC toolchain. `--board` accepts the board manifest's
`project` value, with or without the `Pack_` prefix, and resolves one
self-contained `Pack_<project>` directory. Human output and `--json` both
include the selected identity, server version, SHA256, and exact local path.
`status` reads only local installed state and reports `ready`, `missing`, or
`invalid`; LAP never calls PocketBase directly.

The installer creates `<state-dir>/assets`, the Pack root, and the toolchain
root with daemon-user ownership, but leaves the Pack/toolchain roots empty on a
fresh install. It configures both asset roots as the only additional sandbox
bind prefixes needed by compile/package tasks. Re-running the installer
replaces the daemon runtime while preserving installed Packs, toolchains, and
unrelated `toolchains.toml` profiles.

An authoritative manifest, transfer, digest, extraction, activation, or local
readiness failure stops the current operation. Older valid bytes remain on
disk, but LAP does not use them as an offline fallback. Correct the failure and
start a fresh operation.

The installer also prepares the daemon user's systemd user manager by enabling
linger and starting `user@<uid>.service`; `lap.service` receives the matching
`XDG_RUNTIME_DIR` and D-Bus address so LAP can run scoped tasks.

On Ubuntu 24.04, the installer may prompt to allow bwrap user namespaces. LAP
uses bwrap for command sandboxing, so `kernel.apparmor_restrict_unprivileged_userns`
must allow unprivileged user namespaces before the daemon can connect.

The installer also configures Linux-side device permissions for serial and USB
access: it adds the daemon user to `dialout` and `plugdev`, writes
`/etc/udev/rules.d/70-lap-devices.rules`, and reloads udev. This covers common
USB serial adapters, board USB/RDM VID `33c3`, and Android ADB interface
classes. Windows or VM USB passthrough still has to expose the devices to Linux
first.

During pairing, enter the pair HTTP URL, not the daemon WebSocket URL. In
the current LAN test stack:

```text
Pair HTTP URL:          http://192.168.1.108:38082
Asset URL from JSON:    http://192.168.1.108:18000
Daemon WebSocket URL:   ws://192.168.1.108:38081/v2/wss
lap_agent MCP URL:      http://192.168.1.108:38080/mcp
```

The WebSocket URL is returned by the pair API and written into the daemon
identity. Do not paste it into the installer prompt.

If pairing is skipped during install, the installer prints a follow-up command
using the generated helper:

```bash
sudo /home/<daemon_user>/lap/bin/lap-pair <PAIR_CODE> --saas-url <SAAS_HTTP_URL>
```

This helper writes identity data into the same state directory used by
`lap.service`, applies the local `ws://` override when needed, and starts the
service.

## Pin A Version

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github \
             LAP_DAEMON_VERSION=v0.1.4 \
             LAP_PAIR_API_URL=http://<omnistack-host>:38082 bash
```

When `LAP_RELEASE_SOURCE=github`, `LAP_DAEMON_VERSION` changes the manifest URL to:

```text
https://github.com/omni-stack-gen/lap-v2-releases/releases/download/<version>/manifest.json
```

## Custom Package Base

Use this only for internal testing or private customer mirrors:

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_PACKAGE_BASE=http://<gitlab-host>/api/v4/projects/<project-id>/packages/generic/<package> \
             LAP_PAIR_API_URL=http://<omnistack-host>:38082 bash
```

For other mirrors, override the exact release directory URL directly:

```bash
curl -fsSL <mirror>/install.sh \
  | sudo env LAP_RELEASE_BASE_URL=<mirror>/<version> \
             LAP_PAIR_API_URL=http://<omnistack-host>:38082 bash
```

## What Customers Can See

Customers can see whatever is inside release assets after installation:

- daemon runtime wrapper and Python venv under the selected install root
- cached release manifest under the selected state dir
- pack projects under `/data/lap-packages` after the first project that needs them
- toolchain bundles under the selected toolchain root after the first compile that needs them
- generated `toolchains.toml` after toolchains have been materialized
- generated systemd unit and install report

They do not need the private source/build repository. If any scripts or build
logic inside pack projects are sensitive, move that logic into compiled helpers
or into a service-controlled path before shipping.

## Expected Release Assets

Each customer release version should publish or serve through the SaaS asset
bootstrap path:

```text
install.sh
manifest.json
SHA256SUMS
lap-daemon-runtime.tar.gz
```

`manifest.json` is the installer's source of truth for asset URLs and hashes.
`SHA256SUMS` is included for manual verification and release auditing.
Selector-specific Pack and toolchain archives are managed independently by the
SaaS asset catalog; they are not eagerly installed from this bootstrap set.

For a moving install command, publish the intended Gitee Release and upload the
same asset names there.

## Operator Checks

After install:

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
sudo cat /data/lap/install-report.json
```
