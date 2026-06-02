# Optional: Slint preview support (slint-viewer)

The LAP daemon can render generated `.slint` UIs **live on this host's display**
via `lap_agent.preview()` (no cross-compile, no flash). This is **off by
default** — most daemon hosts are headless production VMs. Enable it only on a
daemon host that has a graphical session (X/Wayland), e.g. a dev/preview box.

## What it provisions

When enabled, the installer:

1. Adds GUI runtime libs + a CJK font (`fonts-noto-cjk`, `libfontconfig1`,
   `libxcb*`, `libxkbcommon*`, `libgl1`/`libegl1`, `libwayland-*`, …) to the apt
   set — the generated UI is Chinese, so a CJK font is required.
2. Installs a `slint-viewer` binary into `<install_root>/bin/slint-viewer` and
   symlinks it to `/usr/local/bin/slint-viewer` so the daemon's bash tool
   resolves a bare `slint-viewer` on `PATH`.

## Enable it

```bash
# 1) provide a prebuilt slint-viewer tarball (built once from the slint fork),
#    matching the project's slint 1.16:
export LAP_INSTALL_SLINT_PREVIEW=1
export LAP_SLINT_VIEWER_URL="https://<your-release-host>/slint-viewer-1.16-x86_64-linux.tar.gz"
export LAP_SLINT_VIEWER_SHA256="<sha256-of-the-tarball>"   # optional but recommended

curl -fsSL https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.0/install.sh | sudo -E bash
```

`sudo -E` preserves the `LAP_*` env. The tarball must be a `.tar.gz` containing
a `slint-viewer` executable (anywhere inside; the installer finds it).

### Binary source precedence

1. `LAP_SLINT_VIEWER_URL` — download + extract (preferred; reproducible).
2. `cargo` **if already present** — `cargo install slint-viewer --version '~1.16'`.
   Heavy/slow; only used when no URL is given and Rust is installed.
3. Neither — the installer prints a non-fatal warning and continues; preview
   stays unavailable until you install `slint-viewer` onto `PATH` yourself.

## Building the slint-viewer tarball (release engineering)

Build once from the slint fork so it matches the on-board renderer's version,
then host it and point `LAP_SLINT_VIEWER_URL` at it:

```bash
# stock crates.io (usually fine for design preview):
cargo install slint-viewer --version '~1.16' --root /tmp/sv
# or exact fork parity:
cargo install slint-viewer --git http://192.168.253.238/wshl/slint-swash.git --root /tmp/sv
tar -C /tmp/sv/bin -czf slint-viewer-1.16-x86_64-linux.tar.gz slint-viewer
sha256sum slint-viewer-1.16-x86_64-linux.tar.gz
```

## Caveats

- **Display required**: the host must have a live X/Wayland session for the
  DISPLAY the preview uses (default `:0`). No display → the viewer launches but
  renders nowhere; `preview()` reports it exited immediately.
- **Sandbox X access**: the daemon runs bash in a bwrap sandbox. If the sandbox
  does not expose the X socket (`/tmp/.X11-unix`) / `DISPLAY` to the viewer
  process, the window will not appear even though the binary is on `PATH`. This
  is a daemon sandbox-config concern, separate from installing the binary.
- **Headless production daemons**: leave this disabled. Cross-compile + flash is
  unaffected.

See also: `lap_agent.preview()` and the `lap: preview slint` task in the
`saas_container` dev environment.
