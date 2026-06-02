# lap-v2-release

Release assets and installers for LAP v2 daemon deployments.

This repository owns the release manifest, Linux production VM installer,
release builder, and operator-facing install docs for turning a fresh daemon
host into the expected LAP v2 runtime shape:

- daemon runtime installed under the selected daemon user's home
- state and project workspace under `/data/lap`
- pack projects under `/data/lap-packages`
- `lap.service` managed by systemd

For the current LAN test stack, keep these endpoints distinct:

- pair HTTP URL: `http://192.168.1.108:38082`
- daemon WebSocket endpoint returned after pairing: `ws://192.168.1.108:38081/v2/wss`
- MCP HTTP endpoint for `lap_agent`: `http://192.168.1.108:38080/mcp`

## LAN test: install → pair → restart → logs

### 1. Install the daemon (one command)

From the LAN GitLab package registry (no internet needed). `LAP_RELEASE_PACKAGE_BASE`
makes the installer fetch the manifest + assets from the same LAN host:

```bash
curl -fsSL "http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh" \
  | sudo env LAP_RELEASE_PACKAGE_BASE="http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

If the host has internet, the public default (GitHub) needs no override:

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.1/install.sh \
  | sudo env LAP_INSTALL_SLINT_PREVIEW=1 bash
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
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.1/install.sh | sudo bash
```

The customer-facing release project should only expose install docs and release
artifacts. Source code and raw build inputs stay in private/internal repos.

Optional Slint preview support (render generated `.slint` live on a daemon host
with a display) is **off by default**; enable with `LAP_INSTALL_SLINT_PREVIEW=1`
— see [Slint preview support](docs/install/slint-preview.md).

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
