# Customer Release Install

This is the customer-facing distribution shape. Customers receive one install
command and do not need access to the source/build repository.

## Install Latest

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-daemon-releases/releases/latest/download/install.sh | sudo bash
```

The installer downloads `manifest.json` from the latest GitHub release, verifies
each asset hash declared by the manifest, installs the daemon runtime, installs
pack projects and toolchains, writes `lap.service`, and optionally pairs the
daemon during the same flow.

## Pin A Version

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-daemon-releases/releases/latest/download/install.sh \
  | sudo env LAP_DAEMON_VERSION=v0.1.0 bash
```

`LAP_DAEMON_VERSION` changes the manifest URL to:

```text
https://github.com/omni-stack-gen/lap-daemon-releases/releases/download/<version>/manifest.json
```

## Custom Release Repo

Use this only for internal testing or private customer mirrors:

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-daemon-releases/releases/latest/download/install.sh \
  | sudo env LAP_RELEASE_REPO=<org>/<repo> bash
```

For non-GitHub mirrors, override the base URL directly:

```bash
curl -fsSL <mirror>/install.sh \
  | sudo env LAP_RELEASE_BASE_URL=<mirror>/<version> bash
```

## What Customers Can See

Customers can see whatever is inside release assets after installation:

- daemon binary under the selected install root
- pack projects under `/data/lap-packages`
- toolchains under the selected toolchain directory
- generated systemd unit and install report

They do not need the private source/build repository. If any scripts or build
logic inside pack projects are sensitive, move that logic into compiled helpers
or into a service-controlled path before shipping.

## Expected Release Assets

Each customer release should publish:

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

## Operator Checks

After install:

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
sudo cat /data/lap/install-report.json
```
