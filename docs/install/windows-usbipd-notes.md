# Windows USB/IP Notes

This is not part of the Linux installer v1. It documents what a future Windows
bootstrapper should automate and what operators can do manually today.

## Host Setup

On Windows, install `usbipd-win` from an Administrator PowerShell:

```powershell
winget install --interactive --exact dorssel.usbipd-win
```

List devices:

```powershell
usbipd list
```

Bind the selected BUSID:

```powershell
usbipd bind --busid <BUSID>
```

Attach it to the WSL distro used by LAP:

```powershell
usbipd attach --wsl OmniLap --busid <BUSID>
```

## Device Categories

Treat board USB and serial adapters as separate devices:

- Board ADB/RDM USB: selected from board VID/PID listed by the board profile.
- CH340 serial adapters: `1a86:7523`, often shown as `USB-SERIAL CH340`.
- CP210x serial adapters: commonly `10c4:ea60`.
- FTDI serial adapters: commonly `0403:6001` or `0403:6015`.

Do not mix CH340 serial adapters into board ADB/RDM VID/PID config. A serial
adapter must be attached separately so the Linux runtime sees `/dev/ttyUSB*` or
`/dev/serial/by-id/*`.

## Linux Verification

Inside the Linux runtime:

```bash
lsusb
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
adb devices
```

Then run daemon-side checks:

```bash
lap doctor
```
