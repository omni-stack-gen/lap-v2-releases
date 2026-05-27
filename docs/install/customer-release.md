# Customer Release Install

This is the customer-facing distribution shape. Customers receive one install
command and do not need access to the source/build repository.

## Install Latest

```bash
curl -fsSL http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh | sudo bash
```

The installer downloads `manifest.json` from the same GitLab Generic Package
Registry version, verifies each asset hash declared by the manifest, installs
the daemon runtime, installs pack projects and toolchains, writes `lap.service`,
and optionally pairs the daemon during the same flow.

The installer also prepares the daemon user's systemd user manager by enabling
linger and starting `user@<uid>.service`; `lap.service` receives the matching
`XDG_RUNTIME_DIR` and D-Bus address so LAP can run scoped tasks.

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
curl -fsSL http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh \
  | sudo env LAP_DAEMON_VERSION=v0.1.0 bash
```

`LAP_DAEMON_VERSION` changes the manifest URL to:

```text
http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/<version>/manifest.json
```

## Custom Package Base

Use this only for internal testing or private customer mirrors:

```bash
curl -fsSL http://<gitlab-host>/api/v4/projects/<project-id>/packages/generic/<package>/latest/install.sh \
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
- pack projects under `/data/lap-packages`
- toolchains under the selected toolchain directory
- generated systemd unit and install report

They do not need the private source/build repository. If any scripts or build
logic inside pack projects are sensitive, move that logic into compiled helpers
or into a service-controlled path before shipping.

## Expected Release Assets

Each customer release version should publish:

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

For a moving "latest" install command, publish the same files under package
version `latest`. If GitLab rejects overwriting existing package files, delete
the old `latest` package first, then upload the new files.

GitLab Release asset download URLs are intentionally not used for the
one-command installer here: when a Release asset link points at Package Registry
or project uploads, GitLab returns an HTML redirect-confirmation page, which is
not compatible with `curl | bash`.

## Operator Checks

After install:

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
sudo cat /data/lap/install-report.json
```
