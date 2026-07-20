# lap-v2-release

**English** · [简体中文](README.zh-CN.md)

Release assets and installers for LAP v2 daemon deployments.

This repository owns the release manifest, Linux production VM installer,
release builder, and operator-facing install docs for turning a fresh daemon
host into the expected LAP v2 runtime shape:

- daemon runtime installed under the selected daemon user's home
- state and project workspace under `/data/lap`
- on-demand pack project cache under `/data/lap-packages`
- on-demand SoC toolchains under the selected toolchain root
- `lap.service` managed by systemd

For the current LAN test stack, the installer operator only needs the pair HTTP
URL. The pair response advertises and persists the asset and WebSocket endpoints:

- install/pair endpoint: `http://192.168.1.108:38082`
- SaaS asset HTTP URL returned by pair JSON: `http://192.168.1.108:18000`
- daemon WebSocket endpoint returned by pair JSON: `ws://192.168.1.108:38081/v2/wss`
- MCP HTTP endpoint for `lap_agent`: `http://192.168.1.108:38080/mcp`

## LAN test: install → pair → restart → logs

### 1. Install the daemon (one command)

The recommended flow downloads the installer, bootstrap manifest, and daemon
runtime from the GitHub release. The command has one LAN address: the pair
endpoint.

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github \
             LAP_PAIR_API_URL="http://192.168.1.108:38082" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

Do not set `LAP_SAAS_URL` for this flow. `POST /v1/pair` returns the canonical
`asset_base_url`; LAP stores it in the identity and prefers it for later Pack
and toolchain downloads. The pair endpoint is only the pre-pair compatibility
fallback.

In China (or when GitHub is slow/blocked), fetch the daemon bootstrap from the
Gitee mirror with `LAP_RELEASE_SOURCE=gitee`. Runtime Pack and toolchain bytes
still come through the SaaS asset facade:

```bash
curl -fsSL https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_SOURCE=gitee \
             LAP_PAIR_API_URL="http://192.168.1.108:38082" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

For legacy LAN package registries, `LAP_RELEASE_PACKAGE_BASE` still overrides
the daemon bootstrap manifest and archive base URL:

```bash
curl -fsSL "http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh" \
  | sudo env LAP_RELEASE_PACKAGE_BASE="http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release" \
             LAP_PAIR_API_URL="http://192.168.1.108:38082" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

When the installer asks whether to pair, answer **n** to skip and pair later.

### 2. Get a pair code

Run on any machine that can reach the pair API (`:38082`):

```bash
curl -sX POST http://192.168.1.108:38082/v1/pair-requests \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"ce-plan-test","device_name":"office-board-1"}'
# -> {"pair_code":"XXXX-XXXX","pair_url":"http://192.168.1.108:38082", ...}
```

### 3. Pair the daemon

On the **daemon host**, use the installer-generated helper (writes identity,
applies the `ws://` override, starts the service). `<daemon_user>` is the user
the daemon runs as (e.g. `dpower`):

```bash
sudo /home/<daemon_user>/lap/bin/lap-pair <PAIR_CODE> --saas-url http://192.168.1.108:38082
# example:
sudo /home/dpower/lap/bin/lap-pair 4HAQ-64J2 --saas-url http://192.168.1.108:38082
```

> The web UI prints this same `lap-pair` command. **Avoid the raw
> `sudo …/lap pair <code>`** — run as root it writes `/data/lap/identity.json`
> as root (mode 0600), and `lap.service` (which runs as the daemon user) then
> can't read it ("permission denied"). `lap-pair` runs the pair as the daemon
> user, so the owner is correct.

> Paste the **pair HTTP URL** (`:38082`), not the daemon WebSocket URL. The
> `ws://…:38081/v2/wss` endpoint comes back from the pair API and is written into
> the identity automatically.

### 4. Restart / verify / logs

```bash
sudo systemctl restart lap.service
sudo systemctl status lap.service --no-pager -l
sudo cat /data/lap/identity.json          # paired identity (state dir = /data/lap)
sudo journalctl -u lap.service -f         # live logs
```

Customer-facing install shape:

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.4/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github \
             LAP_PAIR_API_URL=http://<omnistack-host>:38082 bash
```

The customer-facing release project should only expose install docs and release
artifacts. Source code and raw build inputs stay in private/internal repos.

Optional Slint preview support (render generated `.slint` live on a daemon host
with a display) is **off by default**; enable with `LAP_INSTALL_SLINT_PREVIEW=1`
— see [Slint preview support](docs/install/slint-preview.md).

## Toolchain Asset Layout

Each toolchain archive contains only its own directory and package-local
metadata. It must not carry the global `toolchains.toml`. In the SaaS lazy
asset flow, the installer does not download all `kind=toolchain` assets up
front; the same metadata is used when a compile flow materializes a needed
toolchain on the LAP host and refreshes `$TOOLCHAIN_ROOT/toolchains.toml`.

Example archive layout:

```text
riscv64-linux-x86_64-20210512/
|-- .omnistack-toolchain.toml
|-- bin/
|-- sysroot/
`-- ...
```

Example `.omnistack-toolchain.toml`:

```toml
profile = "F1"
target = "riscv64gc-unknown-linux-gnu"
bin = ["bin"]
cc = "bin/riscv64-unknown-linux-gnu-gcc"
ar = "bin/riscv64-unknown-linux-gnu-ar"
linker = "bin/riscv64-unknown-linux-gnu-gcc"
```

One LAP host can hold multiple SoC toolchains at the same time; each archive
contributes a distinct `profile`, and the local registry is built from the
toolchains that have actually been materialized.

## Managed Runtime Assets

A normal install creates the cache, Pack, and toolchain roots but leaves them
empty. The installer downloads only `kind=daemon_runtime`; a live operation or
an operator command later asks the SaaS manifest for exactly one selector:

| Selector | Managed asset | Local compatibility output |
|---|---|---|
| `--soc F1` | F1 cross-toolchain | `<toolchain-root>/toolchains.toml` plus an immutable version directory |
| `--board FD_F1_...` | `Pack_FD_F1_...` project | `<packages-root>/Pack_FD_F1_...` pointing at an immutable version |

Each Pack archive is self-contained below its own `Pack_<project>` directory,
including `pack.sh` and its dependencies. There is no shared top-level
`pack.sh` or `.venv` contract.

The installer persists these values in `<state-dir>/release-source.env` and
also writes them into `lap.service`:

```text
LAP_RELEASE_SAAS_URL=<reachable SaaS base URL>
LAP_RELEASE_MANIFEST_URL=<SaaS base URL>/v1/assets/lap-release/manifest.json
LAP_ASSET_CACHE_DIR=<state-dir>/assets
LAP_PACKAGES_ROOT=<packages-root>
LAP_TOOLCHAINS_ROOT=<toolchain-root>
LAP_EXPECTED_UID=<daemon uid>
```

The daemon user owns all three roots. The generated sandbox allowlist includes
only the configured Pack and toolchain roots required by compile/package
tasks. Reinstalling the daemon runtime preserves installed assets and unrelated
toolchain profiles.

Operators can prefetch or inspect the same managed assets as the daemon. Run
the command as the daemon user so installed files keep one owner:

```bash
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --soc F1
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --board FD_F1_R88R30_ADB_SPINOR
sudo -u <daemon-user> -H <install-root>/bin/lap assets status --soc F1 --json
```

With a non-default state directory, also pass `LAP_STATE_DIR=<state-dir>` so
the CLI can load the installer-persisted asset settings.

`ensure` checks the current SaaS descriptor every time, then reports the exact
identity, version, SHA256, immutable path, and whether the local bytes were
reused. `status` is local-only and reports `ready`, `missing`, or `invalid`.
Neither command contacts PocketBase directly. Run mutating commands as the
daemon user; another identity is rejected before asset roots are created.

Manifest, download, digest, extraction, activation, or readiness failure stops
that operation. A previous valid version remains on disk but is not used as a
fallback; correct the cause and start the command or web action again.

Start here:

- [Customer release install guide](docs/install/customer-release.md)
- [Linux installer requirements](docs/requirements/2026-05-26-lap-daemon-installer-v1.md)
- [Linux install guide](docs/install/linux-production-vm.md)
- [Cross-machine test release guide](docs/install/cross-machine-test.md)
- [Slint preview support (optional)](docs/install/slint-preview.md)
- [Windows USB notes](docs/install/windows-usbipd-notes.md)

Development checks:

```bash
bash -n install.sh
python3 scripts/validate_manifest.py examples/manifest.example.json
python3 scripts/build_release.py --config examples/release-config.example.json --check-only
python3 -m unittest discover -s tests
```
