#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_VERSION="0.1.1-dev"
# Release asset download hosts. The default source is the OmniStack SaaS asset
# endpoint entered during install. LAP_RELEASE_SOURCE=github|gitee keeps the old
# GitHub-style release layout as an explicit fallback. An explicit
# LAP_RELEASE_MANIFEST_URL, LAP_RELEASE_BASE_URL, or LAP_RELEASE_PACKAGE_BASE
# still overrides the source selection.
GITHUB_RELEASE_BASE="https://github.com/omni-stack-gen/lap-v2-releases/releases/download"
GITEE_RELEASE_BASE="https://gitee.com/lch8/lap-v2-releases/releases/download"
DEFAULT_RELEASE_VERSION="v0.1.2"
DEFAULT_SAAS_URL="http://127.0.0.1:18000"
APT_PACKAGES=(
  ca-certificates
  curl
  tar
  gzip
  python3
  sudo
  procps
  dbus-user-session
  android-tools-adb
  usbutils
  udev
  linux-tools-generic
  hwdata
  bubblewrap
  util-linux
  ripgrep
  libusb-1.0-0-dev
)

# Extra runtime libs + CJK font for the OPTIONAL slint-viewer preview support
# (lap_agent.preview() renders generated .slint live on this daemon host's
# display). Only appended to the apt set when LAP_INSTALL_SLINT_PREVIEW=1, so
# headless production daemons are unaffected. These are runtime .so libs (the
# slint-viewer binary is prebuilt), covering winit X11/Wayland + GL backends.
SLINT_PREVIEW_APT_PACKAGES=(
  fonts-noto-cjk
  libfontconfig1
  libfreetype6
  libxkbcommon0
  libxkbcommon-x11-0
  libxcb1
  libxcb-render0
  libxcb-shape0
  libxcb-xfixes0
  libx11-6
  libxcursor1
  libxi6
  libxrandr2
  libgl1
  libegl1
  libgles2
  libwayland-client0
  libwayland-cursor0
  libwayland-egl1
)

# Build deps for compiling slint-viewer from source via cargo. Only added to the
# apt set when slint preview is enabled AND no prebuilt LAP_SLINT_VIEWER_URL is
# given (see provision_slint_preview).
SLINT_BUILD_APT_PACKAGES=(
  build-essential
  pkg-config
  curl
  libfontconfig1-dev
)

log() {
  printf '[lap-install] %s\n' "$*"
}

die() {
  printf '[lap-install] ERROR: %s\n' "$*" >&2
  exit 1
}

is_dry_run() {
  [[ "${LAP_INSTALL_DRY_RUN:-0}" == "1" ]]
}

read_prompt_line() {
  local prompt="$1"
  local answer
  local tty_fd
  if { [[ -t 1 ]] || [[ -t 2 ]]; } && { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then
    printf '%s' "$prompt" >&"$tty_fd"
    IFS= read -r answer <&"$tty_fd" || {
      exec {tty_fd}>&-
      return 1
    }
    exec {tty_fd}>&-
  else
    IFS= read -r -p "$prompt" answer || return 1
  fi
  printf '%s' "$answer"
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local answer
  if ! answer="$(read_prompt_line "$prompt [$default]: ")"; then
    answer=""
  fi
  if [[ -z "$answer" ]]; then
    printf '%s' "$default"
  else
    printf '%s' "$answer"
  fi
}

prompt_yes_no() {
  local prompt="$1"
  local default="$2"
  local answer suffix
  case "$default" in
    y|Y) suffix="Y/n" ;;
    n|N) suffix="y/N" ;;
    *) die "invalid yes/no default: $default" ;;
  esac
  while true; do
    if ! answer="$(read_prompt_line "$prompt [$suffix]: ")"; then
      answer="$default"
    else
      answer="${answer:-$default}"
    fi
    case "$answer" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) printf 'Please answer y or n.\n' >&2 ;;
    esac
  done
}

release_package_base() {
  printf '%s' "${LAP_RELEASE_PACKAGE_BASE:-}"
}

release_version_pin() {
  printf '%s' "${LAP_DAEMON_VERSION:-${LAP_RELEASE_VERSION:-}}"
}

release_source_kind() {
  printf '%s' "${LAP_RELEASE_SOURCE:-saas}"
}

validate_release_source() {
  case "$(release_source_kind)" in
    saas | SaaS | SAAS | github | GitHub | GITHUB | gitee | Gitee | GITEE) return 0 ;;
    *) return 1 ;;
  esac
}

release_source_base() {
  # Prints the chosen mirror base, or returns 1 (caller dies) on an unknown
  # source. Returning rather than calling die() here matters: this runs inside a
  # "$(...)" command substitution, where a die/exit would only kill the subshell
  # and bash's set -e would not abort the parent.
  case "$(release_source_kind)" in
    github | GitHub | GITHUB) printf '%s' "$GITHUB_RELEASE_BASE" ;;
    gitee | Gitee | GITEE) printf '%s' "$GITEE_RELEASE_BASE" ;;
    *) return 1 ;;
  esac
}

release_base_url() {
  if [[ -n "${LAP_RELEASE_BASE_URL:-}" ]]; then
    printf '%s' "${LAP_RELEASE_BASE_URL%/}"
    return
  fi

  local package_base version source_base
  package_base="$(release_package_base)"
  package_base="${package_base%/}"
  version="$(release_version_pin)"
  if [[ -n "$package_base" && -n "$version" ]]; then
    printf '%s/%s' "$package_base" "$version"
  elif [[ -n "$package_base" ]]; then
    printf '%s/latest' "$package_base"
  else
    source_base="$(release_source_base)" ||
      die "unknown LAP_RELEASE_SOURCE '${LAP_RELEASE_SOURCE:-}' (expected: github | gitee)"
    if [[ -n "$version" ]]; then
      printf '%s/%s' "$source_base" "$version"
    else
      printf '%s/%s' "$source_base" "$DEFAULT_RELEASE_VERSION"
    fi
  fi
}

release_uses_saas_manifest() {
  [[ -z "${LAP_RELEASE_MANIFEST_URL:-}" ]] || return 1
  [[ -z "${LAP_RELEASE_BASE_URL:-}" ]] || return 1
  [[ -z "$(release_package_base)" ]] || return 1
  case "$(release_source_kind)" in
    saas | SaaS | SAAS) return 0 ;;
    *) return 1 ;;
  esac
}

default_install_saas_url() {
  printf '%s' "${LAP_SAAS_URL:-$DEFAULT_SAAS_URL}"
}

default_pair_api_url() {
  local fallback="$1"
  printf '%s' "${LAP_PAIR_API_URL:-$fallback}"
}

saas_release_manifest_url() {
  local saas_url="${1:-$(default_install_saas_url)}"
  saas_url="${saas_url%/}"
  printf '%s/v1/assets/lap-release/manifest.json' "$saas_url"
}

manifest_url() {
  if [[ -n "${LAP_RELEASE_MANIFEST_URL:-}" ]]; then
    printf '%s' "$LAP_RELEASE_MANIFEST_URL"
    return
  fi
  if release_uses_saas_manifest; then
    saas_release_manifest_url "${1:-}"
    return
  fi
  printf '%s/manifest.json' "$(release_base_url)"
}

require_no_args() {
  if [[ "$#" -ne 0 ]]; then
    die "v1 installer is interactive and accepts no command-line arguments"
  fi
}

require_root_unless_dry_run() {
  if is_dry_run; then
    log "dry run enabled; root-only operations will be skipped"
    return
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    die "run as root, for example: sudo bash install.sh"
  fi
}

require_commands() {
  local missing=()
  local cmd
  for cmd in python3 curl tar sha256sum; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done
  if ((${#missing[@]})); then
    die "missing required command(s): ${missing[*]}"
  fi
}

validate_abs_path() {
  local name="$1"
  local path="$2"
  [[ "$path" == /* ]] || die "$name must be an absolute path: $path"
  [[ "$path" != *[$'\t\r\n ']* ]] || die "$name must not contain whitespace: $path"
}

normalize_abs_path() {
  local path="$1"
  python3 - "$path" <<'PY'
import os
import sys

print(os.path.normpath(sys.argv[1]))
PY
}

validate_home_owner_path() {
  local name="$1"
  local path="$2"
  local user="$3"
  local home_user

  case "$path" in
    /home/*/*|/home/*)
      home_user="${path#/home/}"
      home_user="${home_user%%/*}"
      if [[ "$home_user" != "$user" ]]; then
        die "$name points under /home/$home_user, but daemon user is '$user'. Did you mean /home/$user?"
      fi
      ;;
  esac
}

validate_install_path() {
  local name="$1"
  local path="$2"
  validate_abs_path "$name" "$path"
  validate_home_owner_path "$name" "$path" "$DAEMON_USER"
}

validate_saas_url() {
  local url="$1"
  case "$url" in
    http://*|https://*) ;;
    ws://*|wss://*)
      die "SaaS URL must be an HTTP pair API base URL, not a WebSocket endpoint. Use http://host:port for pairing; the daemon receives ws_endpoint after pairing."
      ;;
    *)
      die "SaaS URL must start with http:// or https://: $url"
      ;;
  esac
  case "$url" in
    */v2/wss|*/v2/wss/|*/mcp|*/mcp/)
      die "SaaS URL must be the HTTP pair API base URL, not a daemon WebSocket or MCP endpoint: $url"
      ;;
  esac
}

dir_nonempty() {
  local path="$1"
  [[ -d "$path" ]] || return 1
  shopt -s nullglob dotglob
  local entries=("$path"/*)
  shopt -u nullglob dotglob
  ((${#entries[@]} > 0))
}

download_file() {
  local url="$1"
  local dest="$2"
  if [[ "$url" == file://* ]]; then
    cp -- "${url#file://}" "$dest"
  elif [[ "$url" == http://* || "$url" == https://* ]]; then
    # --progress-bar: show a download bar (the asset tarballs are big and the
    # plain -s made it look hung). --speed-limit/--speed-time: abort a stalled
    # transfer (<1KB/s for 30s) so --retry kicks in instead of hanging forever.
    curl -fL --progress-bar --retry 3 --connect-timeout 20 \
      --speed-limit 1024 --speed-time 30 --output "$dest" "$url"
  elif [[ "$url" == /* || "$url" == ./* || "$url" == ../* ]]; then
    cp -- "$url" "$dest"
  else
    die "unsupported asset URL: $url"
  fi
}

fetch_manifest() {
  local url="$1"
  local dest="$2"
  log "fetching manifest: $url"
  download_file "$url" "$dest"
}

manifest_value() {
  local manifest="$1"
  local path="$2"
  python3 - "$manifest" "$path" <<'PY'
import json
import sys

manifest, dotted = sys.argv[1], sys.argv[2]
with open(manifest, encoding="utf-8") as fh:
    data = json.load(fh)
value = data
for part in dotted.split("."):
    value = value[part]
print(value)
PY
}

manifest_assets_tsv() {
  local manifest="$1"
  python3 - "$manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for asset in data["assets"]:
    fields = [
        asset["id"],
        asset["kind"],
        asset["version"],
        asset.get("url", ""),
        asset["sha256"],
        asset.get("archive", "tar.gz"),
        asset["target"],
        str(asset.get("strip_components", 0)),
    ]
    print("\t".join(fields))
PY
}

manifest_asset_parts_tsv() {
  local manifest="$1"
  local asset_id="$2"
  python3 - "$manifest" "$asset_id" <<'PY'
import json
import sys

manifest, asset_id = sys.argv[1], sys.argv[2]
with open(manifest, encoding="utf-8") as fh:
    data = json.load(fh)
for asset in data["assets"]:
    if asset.get("id") != asset_id:
        continue
    for part in asset.get("parts", []):
        print("\t".join([part["name"], part["url"], part["sha256"]]))
    break
PY
}

validate_manifest() {
  local manifest="$1"
  python3 - "$manifest" <<'PY'
import json
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

errors = []
sha_re = re.compile(r"^[0-9a-f]{64}$")
targets = {"install_root", "packages_root", "toolchain_root"}
archives = {"tar.gz", "tgz"}

if data.get("schema_version") != 1:
    errors.append("schema_version must be 1")
if not isinstance(data.get("release"), dict) or not data["release"].get("version"):
    errors.append("release.version is required")
if not isinstance(data.get("defaults"), dict) or not data["defaults"].get("saas_url"):
    errors.append("defaults.saas_url is required")
assets = data.get("assets")
if not isinstance(assets, list) or not assets:
    errors.append("assets must be a non-empty list")
else:
    seen_ids = set()
    seen_kinds = set()
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            errors.append(f"assets[{index}] must be an object")
            continue
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(f"assets[{index}].id is required")
        elif asset_id in seen_ids:
            errors.append(f"duplicate asset id {asset_id!r}")
        else:
            seen_ids.add(asset_id)
        kind = asset.get("kind")
        if not isinstance(kind, str) or not kind:
            errors.append(f"assets[{index}].kind is required")
        else:
            seen_kinds.add(kind)
        for field in ("version",):
            if not isinstance(asset.get(field), str) or not asset[field]:
                errors.append(f"assets[{index}].{field} is required")
        has_url = isinstance(asset.get("url"), str) and bool(asset["url"])
        parts = asset.get("parts", [])
        has_parts = isinstance(parts, list) and bool(parts)
        if not has_url and not has_parts:
            errors.append(f"assets[{index}] must define url or parts")
        if has_parts:
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict):
                    errors.append(f"assets[{index}].parts[{part_index}] must be an object")
                    continue
                for field in ("name", "url", "sha256"):
                    if not isinstance(part.get(field), str) or not part[field]:
                        errors.append(f"assets[{index}].parts[{part_index}].{field} is required")
                if isinstance(part.get("sha256"), str) and not sha_re.match(part["sha256"]):
                    errors.append(f"assets[{index}].parts[{part_index}].sha256 must be 64 lowercase hex chars")
        if not isinstance(asset.get("sha256"), str) or not sha_re.match(asset["sha256"]):
            errors.append(f"assets[{index}].sha256 must be 64 lowercase hex chars")
        if asset.get("archive") not in archives:
            errors.append(f"assets[{index}].archive must be one of {sorted(archives)}")
        if asset.get("target") not in targets:
            errors.append(f"assets[{index}].target must be one of {sorted(targets)}")
        strip = asset.get("strip_components", 0)
        if not isinstance(strip, int) or strip < 0:
            errors.append(f"assets[{index}].strip_components must be a non-negative integer")
    missing = {"daemon_runtime"} - seen_kinds
    if missing:
        errors.append(f"missing required asset kinds: {sorted(missing)}")

if errors:
    for error in errors:
        print(f"manifest error: {error}", file=sys.stderr)
    sys.exit(2)
PY
}

resolve_target() {
  local token="$1"
  case "$token" in
    install_root) printf '%s' "$INSTALL_ROOT" ;;
    packages_root) printf '%s' "$PACKAGES_ROOT" ;;
    toolchain_root) printf '%s' "$TOOLCHAIN_ROOT" ;;
    *) die "unknown manifest target: $token" ;;
  esac
}

ensure_user() {
  local user="$1"
  if id "$user" >/dev/null 2>&1; then
    return
  fi
  if is_dry_run; then
    log "dry run: would create user $user"
    return
  fi
  if prompt_yes_no "User '$user' does not exist. Create it" "y"; then
    useradd -m -s /bin/bash "$user"
  else
    die "daemon user does not exist: $user"
  fi
}

primary_group() {
  local user="$1"
  id -gn "$user" 2>/dev/null || printf '%s' "$user"
}

uid_for_user() {
  local user="$1"
  if id -u "$user" >/dev/null 2>&1; then
    id -u "$user"
    return
  fi
  if is_dry_run; then
    printf '1000'
    return
  fi
  die "daemon user does not exist: $user"
}

home_for_user() {
  local user="$1"
  local home
  home="$(getent passwd "$user" 2>/dev/null | awk -F: '{print $6}' || true)"
  if [[ -n "$home" ]]; then
    printf '%s' "$home"
  else
    printf '/home/%s' "$user"
  fi
}

install_apt_packages() {
  if is_dry_run; then
    log "dry run: would install apt packages: ${APT_PACKAGES[*]}"
    return
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get not found; skipping apt package install"
    return
  fi
  log "installing apt packages"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
}

# True on WSL (WSL1/WSL2). On WSL the daemon drives the Windows-side
# slint-viewer.exe, so we never build/install a Linux slint-viewer here.
# Detection prefers /proc (always readable under sudo, where the WSL_* env vars
# are usually lost). Force with LAP_FORCE_WSL=1 (skip) / LAP_FORCE_WSL=0 (install).
is_wsl() {
  case "${LAP_FORCE_WSL:-}" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  grep -qiE 'microsoft|wsl' /proc/sys/kernel/osrelease 2>/dev/null && return 0
  grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null && return 0
  [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]]
}

# slint-viewer is installed only when explicitly opted in
# (LAP_INSTALL_SLINT_PREVIEW=1) AND not on WSL (see is_wsl) — gates the apt build
# deps AND provision_slint_preview in one place.
slint_preview_enabled() {
  [[ "${LAP_INSTALL_SLINT_PREVIEW:-0}" == "1" ]] && ! is_wsl
}

# Ensure the daemon user has a cargo toolchain so `cargo install slint-viewer`
# can build from source. If cargo is missing, install Rust via rustup (minimal
# profile, no PATH edits — provision_slint_preview sets PATH explicitly).
ensure_cargo() {
  local dhome
  dhome="$(home_for_user "$DAEMON_USER")"
  if [[ -x "$dhome/.cargo/bin/cargo" ]] || command -v cargo >/dev/null 2>&1; then
    return 0
  fi
  log "cargo not found — installing Rust toolchain via rustup for $DAEMON_USER (minimal)"
  sudo -u "$DAEMON_USER" env "HOME=$dhome" bash -c \
    'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path' \
    || die "rustup install failed; install Rust manually or set LAP_SLINT_VIEWER_URL to a prebuilt slint-viewer"
}

# Optional: provision slint-viewer so lap_agent.preview() can render generated
# .slint UIs live on THIS daemon host's display (Option A). Opt-in via
# LAP_INSTALL_SLINT_PREVIEW=1 (default off — most daemon hosts are headless
# production VMs with no display). Binary source precedence:
#   1. LAP_SLINT_VIEWER_URL    — a .tar.gz containing a `slint-viewer` binary
#      (build once from the slint fork; optional LAP_SLINT_VIEWER_SHA256 to pin).
#   2. otherwise — `cargo install slint-viewer`, auto-installing the Rust
#      toolchain via rustup first when cargo is missing (slow; builds from source).
# The binary lands in $INSTALL_ROOT/bin and is symlinked into /usr/local/bin so
# the daemon's bash tool resolves a bare `slint-viewer` on PATH.
provision_slint_preview() {
  slint_preview_enabled || return 0
  local bin_dir="$INSTALL_ROOT/bin"
  local dest="$bin_dir/slint-viewer"
  local link="/usr/local/bin/slint-viewer"
  if is_dry_run; then
    log "dry run: would provision slint-viewer into $dest and symlink $link"
    return 0
  fi
  mkdir -p "$bin_dir"
  local url="${LAP_SLINT_VIEWER_URL:-}"
  if [[ -n "$url" ]]; then
    log "provisioning slint-viewer from $url"
    local tarball="$INSTALL_TMP_DIR/slint-viewer.tar.gz"
    download_file "$url" "$tarball"
    if [[ -n "${LAP_SLINT_VIEWER_SHA256:-}" ]]; then
      printf '%s  %s\n' "$LAP_SLINT_VIEWER_SHA256" "$tarball" | sha256sum -c -
    fi
    local extract="$INSTALL_TMP_DIR/slint-viewer-extract"
    mkdir -p "$extract"
    tar -xzf "$tarball" -C "$extract"
    local found
    found="$(find "$extract" -type f -name slint-viewer -print -quit)"
    [[ -n "$found" ]] || die "slint-viewer binary not found inside $url"
    install -m 0755 "$found" "$dest"
  else
    ensure_cargo
    local dhome
    dhome="$(home_for_user "$DAEMON_USER")"
    log "LAP_SLINT_VIEWER_URL not set; building slint-viewer via cargo (slow; from source)"
    sudo -u "$DAEMON_USER" env "HOME=$dhome" \
      "PATH=$dhome/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
      cargo install slint-viewer --version '~1.16' --root "$INSTALL_ROOT" \
      || die "cargo install slint-viewer failed; set LAP_SLINT_VIEWER_URL to a prebuilt tarball instead"
  fi
  chown "$DAEMON_USER:$DAEMON_GROUP" "$dest" 2>/dev/null || true
  ln -sf "$dest" "$link"
  log "slint-viewer installed: $dest (symlinked $link)"
}

prepare_device_permissions() {
  local rules_file="/etc/udev/rules.d/70-lap-devices.rules"
  if is_dry_run; then
    log "dry run: would configure serial/USB permissions for $DAEMON_USER (dialout, plugdev, udev rules)"
    return
  fi

  log "configuring serial/USB permissions for $DAEMON_USER"
  groupadd -f dialout
  groupadd -f plugdev
  usermod -aG dialout,plugdev "$DAEMON_USER"

  cat > "$rules_file" <<'EOF'
# OmniStack LAP device permissions.
#
# Serial consoles commonly used with LAP boards.
SUBSYSTEM=="tty", KERNEL=="ttyUSB[0-9]*", GROUP="dialout", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", KERNEL=="ttyACM[0-9]*", GROUP="dialout", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", GROUP="dialout", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", GROUP="dialout", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", GROUP="dialout", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", GROUP="dialout", MODE="0660", TAG+="uaccess"

# Board USB/RDM and Android ADB interfaces.
SUBSYSTEM=="usb", ATTRS{idVendor}=="33c3", GROUP="plugdev", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:ff4201:*", GROUP="plugdev", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:ff4203:*", GROUP="plugdev", MODE="0660", TAG+="uaccess"
EOF
  chmod 0644 "$rules_file"

  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || log "warning: failed to reload udev rules"
    udevadm trigger --subsystem-match=tty || true
    udevadm trigger --subsystem-match=usb || true
  else
    log "warning: udevadm not found; replug devices or reboot to apply udev rules"
  fi
  log "wrote $rules_file"
}

preflight_paths() {
  if is_dry_run; then
    log "dry run: would refuse non-empty install directory"
    return
  fi
  local path
  for path in "$INSTALL_ROOT"; do
    if dir_nonempty "$path"; then
      if [[ -x "$path/bin/lap" && -d "$path/.venv" ]]; then
        log "existing LAP runtime detected at $path; daemon runtime will be replaced"
      else
        die "refusing to overwrite unrecognized non-empty directory: $path. Back it up or remove it, then rerun."
      fi
    fi
  done
}

create_dirs() {
  if is_dry_run; then
    log "dry run: would create state/workspace directories and asset targets"
    return
  fi
  mkdir -p "$STATE_DIR" "$WORKSPACE_ROOT" "$INSTALL_ROOT" "$TOOLCHAIN_ROOT" "$PACKAGES_ROOT" "$(asset_cache_dir)"
  chown -R "$DAEMON_USER:$DAEMON_GROUP" "$STATE_DIR" "$INSTALL_ROOT" "$TOOLCHAIN_ROOT" "$PACKAGES_ROOT"
  chmod 0700 "$STATE_DIR"
  chmod 0755 "$WORKSPACE_ROOT" "$PACKAGES_ROOT"
}

release_manifest_cache_path() {
  printf '%s/release-manifest.json' "$STATE_DIR"
}

release_source_env_path() {
  printf '%s/release-source.env' "$STATE_DIR"
}

asset_cache_dir() {
  printf '%s/assets' "$STATE_DIR"
}

write_release_manifest_cache() {
  local manifest="$1"
  local manifest_url="$2"
  local saas_url="$3"
  local manifest_cache source_env cache_dir
  manifest_cache="$(release_manifest_cache_path)"
  source_env="$(release_source_env_path)"
  cache_dir="$(asset_cache_dir)"
  if is_dry_run; then
    log "dry run: would cache release manifest at $manifest_cache"
    return
  fi

  mkdir -p "$cache_dir"
  cp -- "$manifest" "$manifest_cache"
  cat > "$source_env" <<EOF
LAP_RELEASE_MANIFEST_URL=$manifest_url
LAP_RELEASE_MANIFEST_PATH=$manifest_cache
LAP_RELEASE_SAAS_URL=$saas_url
LAP_ASSET_CACHE_DIR=$cache_dir
LAP_PACKAGES_ROOT=$PACKAGES_ROOT
LAP_TOOLCHAINS_ROOT=$TOOLCHAIN_ROOT
LAP_EXPECTED_UID=$DAEMON_UID
EOF
  chown "$DAEMON_USER:$DAEMON_GROUP" "$manifest_cache" "$source_env"
  chmod 0644 "$manifest_cache" "$source_env"
}

prepare_sandbox_userns() {
  if is_dry_run; then
    log "dry run: would prepare bwrap user namespace sysctls"
    return
  fi
  command -v sysctl >/dev/null 2>&1 || die "sysctl not found; install procps first"

  local apparmor_path="/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
  local userns_path="/proc/sys/kernel/unprivileged_userns_clone"
  local sysctl_conf="/etc/sysctl.d/60-lap-userns.conf"
  local apparmor_value="" userns_value=""
  local desired_lines=()

  if [[ -r "$apparmor_path" ]]; then
    apparmor_value="$(tr -d '[:space:]' < "$apparmor_path")"
    if [[ "$apparmor_value" != "0" ]]; then
      if ! prompt_yes_no "Ubuntu AppArmor blocks bwrap user namespaces. Set kernel.apparmor_restrict_unprivileged_userns=0" "y"; then
        die "bwrap user namespaces are required; enable kernel.apparmor_restrict_unprivileged_userns=0 or rerun and accept the prompt"
      fi
      log "setting kernel.apparmor_restrict_unprivileged_userns=0"
      sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 >/dev/null
    fi
    desired_lines+=("kernel.apparmor_restrict_unprivileged_userns = 0")
  fi

  if [[ -r "$userns_path" ]]; then
    userns_value="$(tr -d '[:space:]' < "$userns_path")"
    if [[ "$userns_value" != "1" ]]; then
      if ! prompt_yes_no "Enable unprivileged user namespaces with kernel.unprivileged_userns_clone=1" "y"; then
        die "unprivileged user namespaces are required; enable kernel.unprivileged_userns_clone=1 or rerun and accept the prompt"
      fi
      log "setting kernel.unprivileged_userns_clone=1"
      sysctl -w kernel.unprivileged_userns_clone=1 >/dev/null
    fi
    desired_lines+=("kernel.unprivileged_userns_clone = 1")
  fi

  if ((${#desired_lines[@]})); then
    printf '%s\n' "${desired_lines[@]}" > "$sysctl_conf"
    log "wrote $sysctl_conf"
  fi
}

prepare_user_manager() {
  if is_dry_run; then
    log "dry run: would enable linger and start user@$DAEMON_UID.service for $DAEMON_USER"
    return
  fi
  command -v loginctl >/dev/null 2>&1 || die "loginctl not found; systemd user manager is required"
  command -v systemctl >/dev/null 2>&1 || die "systemctl not found; systemd is required"

  log "enabling linger for $DAEMON_USER"
  loginctl enable-linger "$DAEMON_USER" || die "failed to enable linger for $DAEMON_USER"

  log "starting user@$DAEMON_UID.service"
  systemctl start "user@$DAEMON_UID.service" || die "failed to start user@$DAEMON_UID.service"

  local runtime_dir="/run/user/$DAEMON_UID"
  local bus_path="$runtime_dir/bus"
  [[ -d "$runtime_dir" ]] || die "user runtime dir is not available: $runtime_dir"
  [[ -S "$bus_path" ]] || die "user D-Bus socket is not available: $bus_path"
}

install_daemon_runtime_archive() {
  local archive="$1"
  local strip="$2"
  local parent stage backup="" had_previous="false"
  parent="$(dirname "$INSTALL_ROOT")"
  mkdir -p "$parent"
  stage="$(mktemp -d "$parent/.lap-runtime-stage.XXXXXX")"
  if ! tar -xzf "$archive" -C "$stage" --strip-components "$strip"; then
    rm -rf "$stage"
    die "failed to extract daemon runtime"
  fi
  if [[ ! -x "$stage/bin/lap" || ! -d "$stage/.venv" ]]; then
    rm -rf "$stage"
    die "daemon runtime archive is missing executable bin/lap or .venv"
  fi
  if ! chown -R "$DAEMON_USER:$DAEMON_GROUP" "$stage"; then
    rm -rf "$stage"
    die "failed to set daemon runtime ownership"
  fi

  if dir_nonempty "$INSTALL_ROOT"; then
    backup="$(mktemp -d "$parent/.lap-runtime-backup.XXXXXX")"
    rmdir "$backup"
    mv "$INSTALL_ROOT" "$backup"
    had_previous="true"
  elif [[ -d "$INSTALL_ROOT" ]]; then
    rmdir "$INSTALL_ROOT"
  fi

  if ! mv "$stage" "$INSTALL_ROOT"; then
    rm -rf "$stage"
    if [[ "$had_previous" == "true" ]]; then
      mv "$backup" "$INSTALL_ROOT" ||
        die "daemon runtime replacement failed and rollback also failed: $backup"
    fi
    die "failed to activate daemon runtime"
  fi
  if [[ "$had_previous" == "true" ]]; then
    rm -rf "$backup"
  fi
}

install_assets() {
  local manifest="$1"
  local tmp_dir="$2"
  local id kind version url sha archive target_token strip target_path asset_file
  local parts_file part_count part_name part_url part_sha part_file

  while IFS=$'\t' read -r id kind version url sha archive target_token strip; do
    target_path="$(resolve_target "$target_token")"
    if [[ "$kind" != "daemon_runtime" ]]; then
      log "lazy asset $id ($kind $version) -> $target_path (downloaded on demand)"
      continue
    fi
    log "asset $id ($kind $version) -> $target_path"
    parts_file="$tmp_dir/$id.parts"
    manifest_asset_parts_tsv "$manifest" "$id" > "$parts_file"
    part_count="$(wc -l < "$parts_file" | tr -d '[:space:]')"
    if is_dry_run; then
      if [[ "$part_count" -gt 0 ]]; then
        log "dry run: would download $part_count parts for $id"
      else
        log "dry run: would download $url"
      fi
      continue
    fi
    asset_file="$tmp_dir/$id.asset"
    if [[ "$part_count" -gt 0 ]]; then
      : > "$asset_file"
      while IFS=$'\t' read -r part_name part_url part_sha; do
        part_file="$tmp_dir/$id.$part_name"
        log "downloading $id part $part_name"
        download_file "$part_url" "$part_file"
        printf '%s  %s\n' "$part_sha" "$part_file" | sha256sum -c -
        cat "$part_file" >> "$asset_file"
      done < "$parts_file"
    else
      download_file "$url" "$asset_file"
    fi
    printf '%s  %s\n' "$sha" "$asset_file" | sha256sum -c -
    install_daemon_runtime_archive "$asset_file" "$strip"
  done < <(manifest_assets_tsv "$manifest")
}

write_systemd_unit() {
  local release_manifest_url="$1"
  local default_saas_url="$2"
  local unit="/etc/systemd/system/lap.service"
  local lap_bin="$INSTALL_ROOT/bin/lap"
  local release_manifest_path asset_cache
  release_manifest_path="$(release_manifest_cache_path)"
  asset_cache="$(asset_cache_dir)"
  local insecure_ws_line=""
  if [[ "${ALLOW_INSECURE_WS:-false}" == "true" ]]; then
    insecure_ws_line="Environment=LAP_ALLOW_INSECURE_WS=1"
  fi
  if is_dry_run; then
    log "dry run: would write $unit with ExecStart=$lap_bin run"
    return
  fi
  cat > "$unit" <<EOF
# lap.service - generated by lap-v2-release install.sh

[Unit]
Description=OmniStack Local Agent Proxy (lap v2)
After=network-online.target user@$DAEMON_UID.service
Wants=network-online.target user@$DAEMON_UID.service

[Service]
Type=notify
NotifyAccess=all
WatchdogSec=30s
ExecStart=$lap_bin run
Restart=on-failure
RestartSec=5s
User=$DAEMON_USER
Group=$DAEMON_GROUP
WorkingDirectory=$INSTALL_ROOT
Environment=LAP_STATE_DIR=$STATE_DIR
Environment=LAP_WORKSPACE_ROOT=$WORKSPACE_ROOT
Environment=LAP_PACKAGES_ROOT=$PACKAGES_ROOT
Environment=LAP_BASH_ALLOWED_EXTRA_BIND_PREFIXES=$PACKAGES_ROOT,$TOOLCHAIN_ROOT
Environment=LAP_TOOLCHAINS_ROOT=$TOOLCHAIN_ROOT
Environment=LAP_RELEASE_MANIFEST_URL=$release_manifest_url
Environment=LAP_RELEASE_MANIFEST_PATH=$release_manifest_path
Environment=LAP_RELEASE_SAAS_URL=$default_saas_url
Environment=LAP_ASSET_CACHE_DIR=$asset_cache
Environment=LAP_EXPECTED_UID=$DAEMON_UID
Environment=XDG_RUNTIME_DIR=/run/user/$DAEMON_UID
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$DAEMON_UID/bus
$insecure_ws_line
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lap
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
}

write_pair_helper() {
  local default_saas_url="$1"
  local helper="$INSTALL_ROOT/bin/lap-pair"
  if is_dry_run; then
    log "dry run: would write $helper"
    return
  fi

  mkdir -p "$(dirname "$helper")"
  cat > "$helper" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

DAEMON_USER=$(printf '%q' "$DAEMON_USER")
DAEMON_GROUP=$(printf '%q' "$DAEMON_GROUP")
DAEMON_UID=$(printf '%q' "$DAEMON_UID")
STATE_DIR=$(printf '%q' "$STATE_DIR")
INSTALL_ROOT=$(printf '%q' "$INSTALL_ROOT")
DEFAULT_SAAS_URL=$(printf '%q' "$default_saas_url")

die() {
  printf '[lap-pair] ERROR: %s\n' "\$*" >&2
  exit 1
}

validate_saas_url() {
  local url="\$1"
  case "\$url" in
    http://*|https://*) ;;
    ws://*|wss://*)
      die "SaaS URL must be an HTTP pair API base URL, not a WebSocket endpoint. Use http://host:port for pairing; the daemon receives ws_endpoint after pairing."
      ;;
    *)
      die "SaaS URL must start with http:// or https://: \$url"
      ;;
  esac
  case "\$url" in
    */v2/wss|*/v2/wss/|*/mcp|*/mcp/)
      die "SaaS URL must be the HTTP pair API base URL, not a daemon WebSocket or MCP endpoint: \$url"
      ;;
  esac
}

ensure_user_manager() {
  command -v loginctl >/dev/null 2>&1 || die "loginctl not found; systemd user manager is required"
  command -v systemctl >/dev/null 2>&1 || die "systemctl not found; systemd is required"

  loginctl enable-linger "\$DAEMON_USER" || die "failed to enable linger for \$DAEMON_USER"
  systemctl start "user@\$DAEMON_UID.service" || die "failed to start user@\$DAEMON_UID.service"

  runtime_dir="/run/user/\$DAEMON_UID"
  bus_path="\$runtime_dir/bus"
  [[ -d "\$runtime_dir" ]] || die "user runtime dir is not available: \$runtime_dir"
  [[ -S "\$bus_path" ]] || die "user D-Bus socket is not available: \$bus_path"
}

usage() {
  printf 'Usage:\n'
  printf '  sudo %s <PAIR_CODE> [--saas-url <SAAS_HTTP_URL>]\n\n' "\$0"
  cat <<'USAGE'
Pairs the daemon into the installer-selected state directory, writes any
required local WebSocket systemd override, then enables and starts lap.service.
USAGE
}

pair_code=""
saas_url="\$DEFAULT_SAAS_URL"
while [[ "\$#" -gt 0 ]]; do
  case "\$1" in
    --saas-url)
      [[ "\$#" -ge 2 ]] || die "--saas-url requires a value"
      saas_url="\$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown option: \$1"
      ;;
    *)
      [[ -z "\$pair_code" ]] || die "unexpected extra argument: \$1"
      pair_code="\$1"
      shift
      ;;
  esac
done
while [[ "\$#" -gt 0 ]]; do
  [[ -z "\$pair_code" ]] || die "unexpected extra argument: \$1"
  pair_code="\$1"
  shift
done

[[ -n "\$pair_code" ]] || die "PAIR_CODE is required"
saas_url="\${saas_url%/}"
validate_saas_url "\$saas_url"

if [[ "\$(id -u)" -ne 0 ]]; then
  die "run as root, for example: sudo \$0 <PAIR_CODE> --saas-url \$saas_url"
fi

lap_bin="\$INSTALL_ROOT/bin/lap"
[[ -x "\$lap_bin" ]] || die "lap binary is not executable: \$lap_bin"

mkdir -p "\$STATE_DIR"
chown "\$DAEMON_USER:\$DAEMON_GROUP" "\$STATE_DIR"
chmod 0700 "\$STATE_DIR"

pair_output="\$(sudo -u "\$DAEMON_USER" env LAP_STATE_DIR="\$STATE_DIR" "\$lap_bin" pair "\$pair_code" --saas-url "\$saas_url" 2>&1)" || {
  printf '%s\n' "\$pair_output"
  die "pairing failed"
}
printf '%s\n' "\$pair_output"

identity_file="\$STATE_DIR/identity.json"
[[ -f "\$identity_file" ]] || die "pair succeeded but identity file was not written: \$identity_file"

read -r proxy_id ws_endpoint < <(python3 - "\$identity_file" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
print(data.get("proxy_id", ""), data.get("ws_endpoint", ""))
PY
)
[[ -n "\$proxy_id" ]] || die "identity file is missing proxy_id: \$identity_file"
[[ -n "\$ws_endpoint" ]] || die "identity file is missing ws_endpoint: \$identity_file"

if [[ "\$ws_endpoint" == ws://* ]]; then
  override_dir="/etc/systemd/system/lap.service.d"
  mkdir -p "\$override_dir"
  cat > "\$override_dir/10-local-ws.conf" <<'UNIT'
[Service]
Environment=LAP_ALLOW_INSECURE_WS=1
UNIT
fi

ensure_user_manager
systemctl daemon-reload
if ! systemctl enable --now lap.service; then
  systemctl status lap.service --no-pager -l || true
  journalctl -u lap.service -n 80 --no-pager -l || true
  die "failed to enable/start lap.service"
fi

printf 'identity=%s\n' "\$identity_file"
printf 'proxy_id=%s\n' "\$proxy_id"
printf 'ws_endpoint=%s\n' "\$ws_endpoint"
printf 'service=lap.service started\n'
EOF
  chmod 0755 "$helper"
  chown "$DAEMON_USER:$DAEMON_GROUP" "$helper"
}

pair_and_start() {
  local saas_url="$1"
  PAIR_STATUS="skipped"
  PROXY_ID=""
  SERVICE_STARTED="false"
  PAIR_WS_ENDPOINT=""

  if ! prompt_yes_no "Pair daemon now (enter n here to skip)" "y"; then
    return
  fi

  local pair_code
  if ! pair_code="$(read_prompt_line "Pair code (leave empty to skip): ")"; then
    pair_code=""
  fi
  if [[ -z "$pair_code" ]]; then
    log "empty pair code; skipping pairing"
    return
  fi
  case "$pair_code" in
    n|N|no|NO)
      log "pair code '$pair_code' means skip; pairing skipped"
      return
      ;;
  esac
  saas_url="$(prompt_default "Pair HTTP URL" "$saas_url")"
  saas_url="${saas_url%/}"
  validate_saas_url "$saas_url"

  if is_dry_run; then
    PAIR_STATUS="dry_run"
    PROXY_ID="lap-dryrun"
    SERVICE_STARTED="dry_run"
    log "dry run: would run $INSTALL_ROOT/bin/lap-pair and start lap.service"
    return
  fi

  local pair_helper="$INSTALL_ROOT/bin/lap-pair"
  [[ -x "$pair_helper" ]] || die "lap-pair helper is not executable: $pair_helper"

  local pair_output
  set +e
  pair_output="$("$pair_helper" "$pair_code" --saas-url "$saas_url" 2>&1)"
  local status=$?
  set -e
  printf '%s\n' "$pair_output"
  if [[ "$status" -ne 0 ]]; then
    PAIR_STATUS="failed"
    die "pairing failed"
  fi
  PAIR_STATUS="paired"
  PROXY_ID="$(printf '%s\n' "$pair_output" | sed -n 's/^paired\. proxy_id=//p' | tail -1)"
  PAIR_WS_ENDPOINT="$(printf '%s\n' "$pair_output" | sed -n 's/^ws_endpoint=//p' | tail -1)"
  SERVICE_STARTED="true"
}

write_report() {
  local manifest="$1"
  local report_path="$STATE_DIR/install-report.json"
  local manifest_cache asset_cache
  manifest_cache="$(release_manifest_cache_path)"
  asset_cache="$(asset_cache_dir)"
  if is_dry_run; then
    log "dry run: would write $report_path"
    return
  fi
  REPORT_PATH="$report_path" \
  MANIFEST_PATH="$manifest" \
  RELEASE_MANIFEST_URL="${SELECTED_MANIFEST_URL:-}" \
  RELEASE_MANIFEST_PATH="$manifest_cache" \
  ASSET_CACHE_DIR="$asset_cache" \
  SCRIPT_VERSION="$SCRIPT_VERSION" \
  DAEMON_USER="$DAEMON_USER" \
  INSTALL_ROOT="$INSTALL_ROOT" \
  STATE_DIR="$STATE_DIR" \
  WORKSPACE_ROOT="$WORKSPACE_ROOT" \
  PACKAGES_ROOT="$PACKAGES_ROOT" \
  TOOLCHAIN_ROOT="$TOOLCHAIN_ROOT" \
  PAIR_STATUS="$PAIR_STATUS" \
  PROXY_ID="$PROXY_ID" \
  SERVICE_STARTED="$SERVICE_STARTED" \
  python3 <<'PY'
import json
import os
from datetime import datetime, timezone

with open(os.environ["MANIFEST_PATH"], encoding="utf-8") as fh:
    manifest = json.load(fh)

report = {
    "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "script_version": os.environ["SCRIPT_VERSION"],
    "manifest_version": manifest["release"]["version"],
    "daemon_user": os.environ["DAEMON_USER"],
    "install_root": os.environ["INSTALL_ROOT"],
    "state_dir": os.environ["STATE_DIR"],
    "workspace_root": os.environ["WORKSPACE_ROOT"],
    "packages_root": os.environ["PACKAGES_ROOT"],
    "toolchain_root": os.environ["TOOLCHAIN_ROOT"],
    "release_manifest_url": os.environ["RELEASE_MANIFEST_URL"],
    "release_manifest_path": os.environ["RELEASE_MANIFEST_PATH"],
    "asset_cache_dir": os.environ["ASSET_CACHE_DIR"],
    "pair_status": os.environ["PAIR_STATUS"],
    "proxy_id": os.environ["PROXY_ID"],
    "service_started": os.environ["SERVICE_STARTED"],
    "assets": [
        {
            "id": asset["id"],
            "kind": asset["kind"],
            "version": asset["version"],
            "sha256": asset["sha256"],
            "target": asset["target"],
            "install_mode": "installed" if asset["kind"] == "daemon_runtime" else "on_demand",
        }
        for asset in manifest["assets"]
    ],
}

path = os.environ["REPORT_PATH"]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
  chown "$DAEMON_USER:$DAEMON_GROUP" "$report_path"
  chmod 0600 "$report_path"
}

print_summary() {
  cat <<EOF

Install summary
---------------
daemon user:      $DAEMON_USER
install root:     $INSTALL_ROOT
state dir:        $STATE_DIR
workspace root:   $WORKSPACE_ROOT
pack projects:    $PACKAGES_ROOT
toolchains:       $TOOLCHAIN_ROOT
release manifest: $(release_manifest_cache_path)
asset cache:      $(asset_cache_dir)
pair status:      $PAIR_STATUS
proxy_id:         ${PROXY_ID:-<not paired>}
service started:  $SERVICE_STARTED

Useful commands:
  sudo systemctl status lap.service --no-pager
  sudo journalctl -u lap.service -f

If pairing was skipped:
  sudo $INSTALL_ROOT/bin/lap-pair <PAIR_CODE> --saas-url <SAAS_HTTP_URL>
EOF
  if slint_preview_enabled; then
    printf 'slint preview:    enabled (slint-viewer at %s/bin/slint-viewer)\n' \
      "$INSTALL_ROOT"
  fi
}

main() {
  require_no_args "$@"
  require_root_unless_dry_run
  require_commands

  log "LAP daemon installer $SCRIPT_VERSION"

  # Validate the release source up front, in the main shell, so a typo in
  # LAP_RELEASE_SOURCE fails fast with a clear message instead of producing a
  # broken manifest URL — release_base_url()'s own guard runs inside a "$(...)"
  # command substitution and so cannot abort the parent.
  validate_release_source ||
    die "unknown LAP_RELEASE_SOURCE '${LAP_RELEASE_SOURCE:-}' (expected: saas | github | gitee)"

  local selected_manifest_url manifest_path release_version default_saas_url default_pair_url install_saas_url
  if release_uses_saas_manifest; then
    install_saas_url="$(prompt_default "SaaS HTTP URL" "$(default_install_saas_url)")"
    install_saas_url="${install_saas_url%/}"
    validate_saas_url "$install_saas_url"
  fi
  selected_manifest_url="$(manifest_url "${install_saas_url:-}")"
  log "release manifest: $selected_manifest_url"

  INSTALL_TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$INSTALL_TMP_DIR"' EXIT
  manifest_path="$INSTALL_TMP_DIR/manifest.json"
  fetch_manifest "$selected_manifest_url" "$manifest_path"
  validate_manifest "$manifest_path"

  release_version="$(manifest_value "$manifest_path" "release.version")"
  default_saas_url="$(manifest_value "$manifest_path" "defaults.saas_url")"
  if [[ -n "${install_saas_url:-}" ]]; then
    default_saas_url="$install_saas_url"
  fi
  default_pair_url="$(default_pair_api_url "$default_saas_url")"
  default_pair_url="${default_pair_url%/}"
  validate_saas_url "$default_pair_url"

  local default_user default_home
  default_user="${SUDO_USER:-$(id -un)}"
  DAEMON_USER="$(prompt_default "Daemon systemd user" "$default_user")"
  ensure_user "$DAEMON_USER"
  DAEMON_GROUP="$(primary_group "$DAEMON_USER")"
  DAEMON_UID="$(uid_for_user "$DAEMON_USER")"
  default_home="$(home_for_user "$DAEMON_USER")"

  INSTALL_ROOT="$(prompt_default "Install root" "$default_home/lap")"
  STATE_DIR="$(prompt_default "State dir" "/data/lap")"
  INSTALL_ROOT="$(normalize_abs_path "$INSTALL_ROOT")"
  STATE_DIR="$(normalize_abs_path "$STATE_DIR")"
  WORKSPACE_ROOT="$(prompt_default "Project workspace root" "$STATE_DIR/workspace")"
  PACKAGES_ROOT="$(prompt_default "Pack projects dir" "/data/lap-packages")"
  TOOLCHAIN_ROOT="$(prompt_default "Toolchain dir" "$default_home/toolchains")"

  WORKSPACE_ROOT="$(normalize_abs_path "$WORKSPACE_ROOT")"
  PACKAGES_ROOT="$(normalize_abs_path "$PACKAGES_ROOT")"
  TOOLCHAIN_ROOT="$(normalize_abs_path "$TOOLCHAIN_ROOT")"

  validate_install_path "Install root" "$INSTALL_ROOT"
  validate_install_path "State dir" "$STATE_DIR"
  validate_install_path "Project workspace root" "$WORKSPACE_ROOT"
  validate_install_path "Pack projects dir" "$PACKAGES_ROOT"
  validate_install_path "Toolchain dir" "$TOOLCHAIN_ROOT"

  cat <<EOF

Planned install
---------------
release:          $release_version
daemon user:      $DAEMON_USER
daemon group:     $DAEMON_GROUP
daemon uid:       $DAEMON_UID
install root:     $INSTALL_ROOT
state dir:        $STATE_DIR
workspace root:   $WORKSPACE_ROOT
pack projects:    $PACKAGES_ROOT
toolchains:       $TOOLCHAIN_ROOT
default SaaS URL: $default_saas_url
default pair URL: $default_pair_url

Assets:
EOF
  manifest_assets_tsv "$manifest_path" | while IFS=$'\t' read -r id kind version url _sha _archive target _strip; do
    mode="on demand"
    if [[ "$kind" == "daemon_runtime" ]]; then
      mode="install now"
    fi
    printf '  - %s (%s %s) -> %s [%s]\n' "$id" "$kind" "$version" "$(resolve_target "$target")" "$mode"
  done
  printf '\n'

  if ! prompt_yes_no "Proceed with install" "y"; then
    die "installation cancelled"
  fi

  preflight_paths
  if slint_preview_enabled; then
    APT_PACKAGES+=("${SLINT_PREVIEW_APT_PACKAGES[@]}")
    log "slint preview enabled: added GUI/font packages to the apt set"
    if [[ -z "${LAP_SLINT_VIEWER_URL:-}" ]]; then
      APT_PACKAGES+=("${SLINT_BUILD_APT_PACKAGES[@]}")
      log "no prebuilt slint-viewer URL: added cargo build deps to the apt set"
    fi
  fi
  install_apt_packages
  prepare_device_permissions
  prepare_sandbox_userns
  create_dirs
  SELECTED_MANIFEST_URL="$selected_manifest_url"
  write_release_manifest_cache "$manifest_path" "$selected_manifest_url" "$default_saas_url"
  install_assets "$manifest_path" "$INSTALL_TMP_DIR"
  provision_slint_preview
  prepare_user_manager
  write_systemd_unit "$selected_manifest_url" "$default_saas_url"
  write_pair_helper "$default_pair_url"
  pair_and_start "$default_pair_url"
  write_report "$manifest_path"
  print_summary

  if is_dry_run; then
    log "DRY RUN complete"
  else
    log "install complete"
  fi
}

if [[ -z "${BASH_SOURCE[0]-}" || "${BASH_SOURCE[0]-}" == "$0" ]]; then
  main "$@"
fi
