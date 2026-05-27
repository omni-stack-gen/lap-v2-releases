# Linux Production VM Install Guide

This guide covers the v1 Linux installer path for Ubuntu daemon hosts.

## Quick Start

Production-style install, after a release is published:

```bash
curl -fsSL http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh | sudo bash
```

Pinned version:

```bash
curl -fsSL http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh \
  | sudo env LAP_DAEMON_VERSION=v0.1.0 bash
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

Use the SaaS pair HTTP URL at the `SaaS HTTP URL` prompt. Do not enter the
daemon WebSocket endpoint there. For the current LAN test stack:

```text
SaaS HTTP URL:          http://192.168.1.108:38082
Daemon WebSocket URL:   ws://192.168.1.108:38081/v2/wss
lap_agent MCP URL:      http://192.168.1.108:38080/mcp
```

The pair server returns the WebSocket endpoint after a successful pair. If that
endpoint is `ws://`, the installer updates `lap.service` with
`LAP_ALLOW_INSECURE_WS=1` for the local test deployment.

If skipped, run later:

```bash
sudo -u <daemon_user> LAP_STATE_DIR=/data/lap /home/<daemon_user>/lap/bin/lap pair <PAIR_CODE> --saas-url <SAAS_HTTP_URL>
sudo systemctl enable --now lap.service
```

## Logs

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
```
