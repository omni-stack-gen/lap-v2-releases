---
date: 2026-05-26
topic: lap-daemon-installer-v1
---

# LAP Daemon Installer V1

## Summary

Build a production-VM-focused interactive installer for `lap daemon`. The installer uses one fixed release manifest to download daemon runtime, pack projects, and toolchains, then writes `lap.service`, optionally pairs the daemon, starts it under systemd, and leaves a machine-readable install report.

---

## Problem Frame

Today the daemon host reaches a working state through several manual steps: placing pack projects under `/data/lap-packages`, preparing toolchains, choosing state/workspace paths, pairing the daemon, and writing a systemd unit. That process is easy to reproduce for one known VM, but too fragile for a real operator handoff.

The target operator should be able to run one installer, answer a small number of prompts with sensible defaults, and end with a daemon host that resembles the currently validated manual setup. Failure modes should stop before destructive changes and explain what the operator needs to fix.

---

## Actors

- A1. Operator: Runs the installer on the Ubuntu daemon VM and answers path, user, and pairing prompts.
- A2. Release maintainer: Publishes the manifest and assets consumed by the installer.
- A3. LAP daemon service: Runs under systemd after installation and owns local hardware/tool execution.
- A4. Windows host operator: For VMware/WSL deployments, handles `usbipd-win` device sharing outside the Linux installer.

---

## Key Flows

- F1. Fresh Linux production VM install
  - **Trigger:** Operator runs the installer on Ubuntu with root privileges.
  - **Actors:** A1, A2, A3
  - **Steps:** Installer loads manifest, prompts for daemon user and paths, downloads all manifest assets, verifies SHA256, extracts assets, writes `lap.service`, asks whether to pair, starts the service if paired, and writes an install report.
  - **Outcome:** The daemon host has installed runtime, pack projects, toolchains, state/workspace directories, and systemd configuration.
  - **Covered by:** R1, R2, R3, R4, R5, R6, R7

- F2. Existing path protection
  - **Trigger:** Installer finds a non-empty install root, toolchain directory, or pack directory.
  - **Actors:** A1
  - **Steps:** Installer stops before download/extract, explains which path is already populated, and tells the operator to back up or remove it before retrying.
  - **Outcome:** Existing pack projects/toolchains/runtime are not overwritten by accident.
  - **Covered by:** R8, R9

- F3. Pair during install
  - **Trigger:** Assets and service unit are ready and the operator chooses to pair now.
  - **Actors:** A1, A3
  - **Steps:** Installer prompts for pair code and SaaS URL, defaulting the URL from the manifest, runs `lap pair` as the daemon user, starts/enables `lap.service`, and records `proxy_id`.
  - **Outcome:** The daemon connects using the paired identity and the operator sees service status/log commands.
  - **Covered by:** R10, R11, R12

- F4. USB onboarding for Windows-hosted lab deployments
  - **Trigger:** Daemon runtime is inside a VM/WSL environment and board USB devices originate on a Windows host.
  - **Actors:** A1, A4
  - **Steps:** Documentation guides `usbipd-win` install, BUSID discovery, bind/attach, Linux `vhci-hcd` checks, and separate handling for board USB versus USB serial adapters.
  - **Outcome:** Operators understand what the Linux installer can check and what must be configured from Windows.
  - **Covered by:** R13, R14, R15

---

## Requirements

**Interactive installation**
- R1. The Linux installer must be interactive in v1 and allow the operator to accept defaults by pressing Enter.
- R2. The installer must require root privileges for system paths, user creation, package installation, and systemd unit writes.
- R3. The installer must default the daemon user from `$SUDO_USER`, allow a different username, and offer to create the user if it does not exist.
- R4. The installer must prompt for install root, state directory, project workspace root, pack projects directory, and toolchain directory.
- R5. Default paths must be derived as: install root `/home/<daemon_user>/lap`, state directory `/data/lap`, workspace root `/data/lap/workspace`, pack projects `/data/lap-packages`, and toolchains `/home/<daemon_user>/toolchains`.

**Manifest and assets**
- R6. The installer must load one release manifest and use it as the source of truth for daemon runtime, pack projects, toolchains, resource versions, SHA256 hashes, and default SaaS URL.
- R7. The installer must download and install every pack/toolchain resource listed in the manifest; v1 does not offer board/profile selection.
- R8. Downloaded assets must be verified against manifest SHA256 before extraction or installation.
- R9. Manifest authenticity in v1 relies on a fixed HTTPS release URL; manifest signing is deferred.

**Filesystem safety**
- R10. The installer must stop instead of overwriting non-empty install root, toolchain directory, or pack projects directory.
- R11. The installer must create or reuse `/data/lap` and `/data/lap/workspace`, but must never clear `/data/lap` automatically.
- R12. The installer must write a complete install report to `/data/lap/install-report.json`.

**Systemd and pairing**
- R13. The installer must write `lap.service` for the selected daemon user and configure it with the selected state, workspace, pack, and toolchain paths.
- R14. The installer must default to pairing during install, using the manifest's SaaS URL as the default prompt value.
- R15. The installer must allow the operator to skip pairing and leave clear follow-up commands for pairing and starting the service later.
- R16. If pairing succeeds, the installer must enable and start `lap.service`, then print service status and log commands.

**USB and serial onboarding**
- R17. The Linux installer must install or check Linux-side USB prerequisites where appropriate, including USB/IP kernel support, ADB, serial tooling, and libusb dependencies.
- R18. The install docs must make clear that Windows `usbipd-win` install, BUSID selection, and device bind/attach happen outside the Linux installer.
- R19. The install docs must distinguish board USB devices from USB serial adapters such as CH340 (`1a86:7523`); serial adapters are separate devices and must not be folded into board ADB/RDM VID/PID config.

---

## Acceptance Examples

- AE1. **Covers R1, R3, R4, R5.** Given an operator runs the installer with sudo, when they press Enter through all path prompts, the daemon user defaults from `$SUDO_USER` and the paths use the documented defaults.
- AE2. **Covers R6, R7, R8.** Given the manifest lists daemon runtime, two pack projects, and a toolchain, when install proceeds, every listed asset is downloaded and must pass SHA256 before extraction.
- AE3. **Covers R10, R11.** Given `/data/lap-packages` is non-empty, when the installer reaches preflight, it stops with a clear message and does not modify that directory.
- AE4. **Covers R14, R15, R16.** Given the operator has a pair code, when they choose to pair during install, the installer runs pairing as the daemon user, starts the service, and prints `proxy_id` plus log commands.
- AE5. **Covers R18, R19.** Given a Windows host shows CH340 devices in `usbipd list`, when the operator reads the USB docs, they are instructed to attach those serial BUSIDs separately from board USB.

---

## Success Criteria

- A new Ubuntu daemon VM can be brought to a service-managed LAP daemon state with one interactive installer and a release manifest.
- Operators can see exactly where runtime, state, workspace, pack projects, and toolchains were installed.
- Existing installations are not silently overwritten.
- Pairing and service startup leave enough terminal output and report data for remote support.
- Planning can proceed without inventing installer scope, path defaults, or overwrite behavior.

---

## Scope Boundaries

- V1 does not provide non-interactive/batch install flags.
- V1 does not provide board/profile selection; all manifest resources are installed.
- V1 does not sign or verify the manifest itself.
- V1 does not control Windows USB devices directly; Windows bootstrapper work is separate.
- V1 does not implement Podman-based runtime packaging.

---

## Key Decisions

- Production VM first: The primary installer path should end in `systemctl`-managed daemon service.
- Release manifest first: One manifest provides asset URLs, versions, hashes, and default SaaS URL.
- Runtime tarball: The daemon runtime ships as a prebuilt tarball rather than source installed on the target host.
- Conservative reinstall: Existing non-empty runtime/toolchain/pack paths stop the installer.
- Windows USB is guided separately: `usbipd-win` is accepted as a required Windows-side dependency for VM/WSL deployments.

---

## Dependencies / Assumptions

- Release assets will be published from this repository or its release process.
- The daemon runtime tarball exposes a `bin/lap` entrypoint relative to the install root.
- Pack projects currently need to recreate the validated shape under `/data/lap-packages`, including `pack.sh`, `Pack_FD_F1_R88R30_ADB_SPINOR`, and `Pack_RL_F1s_DV10_2_SPINOR`.
- The target Linux host is Ubuntu-like and uses systemd.
- Windows bootstrapper work may later reuse this release manifest, but is not part of v1.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R6][Technical] Final manifest URL and release tag naming.
- [Affects R13][Technical] Exact environment variables the current daemon/pack skills will consume for pack and toolchain roots.
- [Affects R17][Needs research] Whether Linux-side USB/IP helper service should be installed by the Linux installer or kept as documentation-only for v1.
