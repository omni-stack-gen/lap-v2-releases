# Customer Release Install

This is the customer-facing distribution shape. Customers receive one install
command and do not need access to the source/build repository.

## Install v0.1.2

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_SAAS_URL=http://<saas-host>:18000 bash
```

If the pair API is served from a different host or port, also set
`LAP_PAIR_API_URL=http://<pair-host>:38082`; this only changes the default shown
when pairing, not the asset manifest URL.

The installer script comes from the GitHub release. By default it downloads
`manifest.json` from the SaaS asset endpoint:

```text
http://<saas-host>:18000/v1/assets/lap-release/manifest.json
```

The SaaS manifest points back to SaaS download URLs for daemon runtime, pack
projects, and toolchains. The installer installs the daemon runtime, caches the
manifest path/URL in the LAP service environment, writes `lap.service`, and
optionally pairs the daemon during the same flow. Pack projects and toolchains
remain on-demand assets: runtime flows download the one required by the
connected board or compile target instead of installing every board package up
front.

Operators may proactively materialize or inspect one asset with the installed
CLI. These commands must run as the daemon user:

```bash
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --soc F1
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --board <manifest.project>
sudo -u <daemon-user> -H <install-root>/bin/lap assets status --soc F1 --json
```

The CLI reads the asset URL, roots, and expected UID persisted by the installer
in `<state-dir>/release-source.env`. Set `LAP_STATE_DIR=<state-dir>` when a
non-default state directory was selected.

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

During pairing, enter the SaaS pair HTTP URL, not the daemon WebSocket URL. In
the current LAN test stack:

```text
SaaS HTTP URL:          http://192.168.1.108:38082
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
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github LAP_DAEMON_VERSION=v0.1.2 bash
```

When `LAP_RELEASE_SOURCE=github`, `LAP_DAEMON_VERSION` changes the manifest URL to:

```text
https://github.com/omni-stack-gen/lap-v2-releases/releases/download/<version>/manifest.json
```

## Custom Package Base

Use this only for internal testing or private customer mirrors:

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.1/install.sh \
  | sudo env LAP_RELEASE_PACKAGE_BASE=http://<gitlab-host>/api/v4/projects/<project-id>/packages/generic/<package> bash
```

For other mirrors, override the exact release directory URL directly:

```bash
curl -fsSL <mirror>/install.sh \
  | sudo env LAP_RELEASE_BASE_URL=<mirror>/<version> bash
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
manifest:

```text
install.sh
manifest.json
SHA256SUMS
lap-daemon-runtime.tar.gz
lap-pack-projects.tar.gz
lap-toolchains.tar.gz
```

`manifest.json` is the installer's source of truth for asset URLs and hashes.
`SHA256SUMS` is included for manual verification and release auditing.

For a moving install command, publish the intended Gitee Release and upload the
same asset names there.

## Operator Checks

After install:

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
sudo cat /data/lap/install-report.json
```
