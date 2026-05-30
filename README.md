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

Customer-facing install shape:

```bash
curl -fsSL https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.0/install.sh | sudo bash
```

The customer-facing release project should only expose install docs and release
artifacts. Source code and raw build inputs stay in private/internal repos.

Start here:

- [Customer release install guide](docs/install/customer-release.md)
- [Linux installer requirements](docs/requirements/2026-05-26-lap-daemon-installer-v1.md)
- [Linux install guide](docs/install/linux-production-vm.md)
- [Cross-machine test release guide](docs/install/cross-machine-test.md)
- [Windows USB notes](docs/install/windows-usbipd-notes.md)

Development checks:

```bash
bash -n install.sh
python3 scripts/validate_manifest.py examples/manifest.example.json
python3 scripts/build_release.py --config examples/release-config.example.json --check-only
python3 -m unittest discover -s tests
```
