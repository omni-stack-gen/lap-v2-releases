# lap-v2-release

Release assets and installers for LAP v2 daemon deployments.

This repository owns the release manifest, Linux production VM installer, and
operator-facing install docs for turning a fresh daemon host into the expected
LAP v2 runtime shape:

- daemon runtime installed under the selected daemon user's home
- state and project workspace under `/data/lap`
- pack projects under `/data/lap-packages`
- toolchains under the selected daemon user's home
- `lap.service` managed by systemd

Start here:

- [Linux installer requirements](docs/requirements/2026-05-26-lap-daemon-installer-v1.md)
- [Linux install guide](docs/install/linux-production-vm.md)
- [Windows USB notes](docs/install/windows-usbipd-notes.md)

Development checks:

```bash
bash -n install.sh
python3 scripts/validate_manifest.py examples/manifest.example.json
python3 scripts/build_release.py --config examples/release-config.example.json --check-only
python3 -m unittest discover -s tests
```
