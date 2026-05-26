# Linux Production VM Install Guide

This guide covers the v1 Linux installer path for Ubuntu daemon hosts.

## Quick Start

Production-style install, after a release is published:

```bash
curl -fsSLO https://github.com/<org>/<repo>/releases/download/<version>/install.sh
sudo bash install.sh
```

Fast path:

```bash
curl -fsSL https://github.com/<org>/<repo>/releases/download/<version>/install.sh | sudo bash
```

The installer is interactive. Press Enter to accept defaults.

## Defaults

The daemon user defaults to `$SUDO_USER`. Paths are derived from that user:

```text
install root:       /home/<daemon_user>/lap
state dir:          /data/lap
project workspace:  /data/lap/workspace
pack projects:      /data/lap-packages
toolchains:         /home/<daemon_user>/toolchains
systemd unit:       /etc/systemd/system/lap.service
install report:     /data/lap/install-report.json
```

## Pairing

The installer asks whether to pair during install. Pairing is recommended.

If skipped, run later:

```bash
sudo -u <daemon_user> LAP_STATE_DIR=/data/lap /home/<daemon_user>/lap/bin/lap pair <PAIR_CODE> --saas-url <SAAS_URL>
sudo systemctl enable --now lap.service
```

## Logs

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
```
