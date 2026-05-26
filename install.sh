#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_VERSION="0.1.0-dev"
DEFAULT_RELEASE_PACKAGE_BASE="http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release"
APT_PACKAGES=(
  ca-certificates
  curl
  tar
  gzip
  python3
  sudo
  android-tools-adb
  usbutils
  linux-tools-generic
  hwdata
  bubblewrap
  util-linux
  ripgrep
  libusb-1.0-0-dev
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
  printf '%s' "${LAP_RELEASE_PACKAGE_BASE:-$DEFAULT_RELEASE_PACKAGE_BASE}"
}

release_version_pin() {
  printf '%s' "${LAP_DAEMON_VERSION:-${LAP_RELEASE_VERSION:-}}"
}

release_base_url() {
  if [[ -n "${LAP_RELEASE_BASE_URL:-}" ]]; then
    printf '%s' "${LAP_RELEASE_BASE_URL%/}"
    return
  fi

  local package_base version
  package_base="$(release_package_base)"
  package_base="${package_base%/}"
  version="$(release_version_pin)"
  if [[ -n "$version" ]]; then
    printf '%s/%s' "$package_base" "$version"
  else
    printf '%s/latest' "$package_base"
  fi
}

manifest_url() {
  if [[ -n "${LAP_RELEASE_MANIFEST_URL:-}" ]]; then
    printf '%s' "$LAP_RELEASE_MANIFEST_URL"
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
    curl -fsSL --retry 3 --connect-timeout 20 --output "$dest" "$url"
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
        asset["url"],
        asset["sha256"],
        asset.get("archive", "tar.gz"),
        asset["target"],
        str(asset.get("strip_components", 0)),
    ]
    print("\t".join(fields))
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
        for field in ("version", "url"):
            if not isinstance(asset.get(field), str) or not asset[field]:
                errors.append(f"assets[{index}].{field} is required")
        if not isinstance(asset.get("sha256"), str) or not sha_re.match(asset["sha256"]):
            errors.append(f"assets[{index}].sha256 must be 64 lowercase hex chars")
        if asset.get("archive") not in archives:
            errors.append(f"assets[{index}].archive must be one of {sorted(archives)}")
        if asset.get("target") not in targets:
            errors.append(f"assets[{index}].target must be one of {sorted(targets)}")
        strip = asset.get("strip_components", 0)
        if not isinstance(strip, int) or strip < 0:
            errors.append(f"assets[{index}].strip_components must be a non-negative integer")
    missing = {"daemon_runtime", "pack_projects", "toolchain"} - seen_kinds
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

preflight_paths() {
  if is_dry_run; then
    log "dry run: would refuse non-empty install/toolchain/pack directories"
    return
  fi
  local path
  for path in "$INSTALL_ROOT" "$TOOLCHAIN_ROOT" "$PACKAGES_ROOT"; do
    if dir_nonempty "$path"; then
      die "refusing to overwrite non-empty directory: $path. Back it up or remove it, then rerun."
    fi
  done
}

create_dirs() {
  if is_dry_run; then
    log "dry run: would create state/workspace directories and asset targets"
    return
  fi
  mkdir -p "$STATE_DIR" "$WORKSPACE_ROOT" "$INSTALL_ROOT" "$TOOLCHAIN_ROOT" "$PACKAGES_ROOT"
  chown -R "$DAEMON_USER:$DAEMON_GROUP" "$STATE_DIR" "$INSTALL_ROOT" "$TOOLCHAIN_ROOT" "$PACKAGES_ROOT"
  chmod 0700 "$STATE_DIR"
  chmod 0755 "$WORKSPACE_ROOT" "$PACKAGES_ROOT"
}

install_assets() {
  local manifest="$1"
  local tmp_dir="$2"
  local id kind version url sha archive target_token strip target_path asset_file

  while IFS=$'\t' read -r id kind version url sha archive target_token strip; do
    target_path="$(resolve_target "$target_token")"
    log "asset $id ($kind $version) -> $target_path"
    if is_dry_run; then
      log "dry run: would download $url"
      continue
    fi
    asset_file="$tmp_dir/$id.asset"
    download_file "$url" "$asset_file"
    printf '%s  %s\n' "$sha" "$asset_file" | sha256sum -c -
    mkdir -p "$target_path"
    tar -xzf "$asset_file" -C "$target_path" --strip-components "$strip"
    chown -R "$DAEMON_USER:$DAEMON_GROUP" "$target_path"
  done < <(manifest_assets_tsv "$manifest")
}

write_systemd_unit() {
  local unit="/etc/systemd/system/lap.service"
  local lap_bin="$INSTALL_ROOT/bin/lap"
  if is_dry_run; then
    log "dry run: would write $unit with ExecStart=$lap_bin run"
    return
  fi
  cat > "$unit" <<EOF
# lap.service - generated by lap-v2-release install.sh

[Unit]
Description=OmniStack Local Agent Proxy (lap v2)
After=network-online.target
Wants=network-online.target

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
Environment=LAP_TOOLCHAINS_ROOT=$TOOLCHAIN_ROOT
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lap
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
}

pair_and_start() {
  local saas_url="$1"
  PAIR_STATUS="skipped"
  PROXY_ID=""
  SERVICE_STARTED="false"

  if ! prompt_yes_no "Pair daemon now" "y"; then
    return
  fi

  local pair_code
  if ! pair_code="$(read_prompt_line "Pair code: ")"; then
    pair_code=""
  fi
  if [[ -z "$pair_code" ]]; then
    log "empty pair code; skipping pairing"
    return
  fi
  saas_url="$(prompt_default "SaaS URL" "$saas_url")"

  if is_dry_run; then
    PAIR_STATUS="dry_run"
    PROXY_ID="lap-dryrun"
    SERVICE_STARTED="dry_run"
    log "dry run: would run lap pair and start lap.service"
    return
  fi

  local lap_bin="$INSTALL_ROOT/bin/lap"
  [[ -x "$lap_bin" ]] || die "lap binary is not executable: $lap_bin"

  local pair_output
  set +e
  pair_output="$(sudo -u "$DAEMON_USER" env LAP_STATE_DIR="$STATE_DIR" "$lap_bin" pair "$pair_code" --saas-url "$saas_url" 2>&1)"
  local status=$?
  set -e
  printf '%s\n' "$pair_output"
  if [[ "$status" -ne 0 ]]; then
    PAIR_STATUS="failed"
    die "pairing failed"
  fi
  PAIR_STATUS="paired"
  PROXY_ID="$(printf '%s\n' "$pair_output" | sed -n 's/^paired\. proxy_id=//p' | tail -1)"

  systemctl enable --now lap.service
  SERVICE_STARTED="true"
}

write_report() {
  local manifest="$1"
  local report_path="$STATE_DIR/install-report.json"
  if is_dry_run; then
    log "dry run: would write $report_path"
    return
  fi
  REPORT_PATH="$report_path" \
  MANIFEST_PATH="$manifest" \
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
pair status:      $PAIR_STATUS
proxy_id:         ${PROXY_ID:-<not paired>}
service started:  $SERVICE_STARTED

Useful commands:
  sudo systemctl status lap.service --no-pager
  sudo journalctl -u lap.service -f

If pairing was skipped:
  sudo -u $DAEMON_USER LAP_STATE_DIR=$STATE_DIR $INSTALL_ROOT/bin/lap pair <PAIR_CODE> --saas-url <SAAS_URL>
  sudo systemctl enable --now lap.service
EOF
}

main() {
  require_no_args "$@"
  require_root_unless_dry_run
  require_commands

  log "LAP daemon installer $SCRIPT_VERSION"

  local selected_manifest_url manifest_path release_version default_saas_url
  selected_manifest_url="$(manifest_url)"
  log "release manifest: $selected_manifest_url"

  INSTALL_TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$INSTALL_TMP_DIR"' EXIT
  manifest_path="$INSTALL_TMP_DIR/manifest.json"
  fetch_manifest "$selected_manifest_url" "$manifest_path"
  validate_manifest "$manifest_path"

  release_version="$(manifest_value "$manifest_path" "release.version")"
  default_saas_url="$(manifest_value "$manifest_path" "defaults.saas_url")"

  local default_user default_home
  default_user="${SUDO_USER:-$(id -un)}"
  DAEMON_USER="$(prompt_default "Daemon systemd user" "$default_user")"
  ensure_user "$DAEMON_USER"
  DAEMON_GROUP="$(primary_group "$DAEMON_USER")"
  default_home="$(home_for_user "$DAEMON_USER")"

  INSTALL_ROOT="$(prompt_default "Install root" "$default_home/lap")"
  STATE_DIR="$(prompt_default "State dir" "/data/lap")"
  WORKSPACE_ROOT="$(prompt_default "Project workspace root" "$STATE_DIR/workspace")"
  PACKAGES_ROOT="$(prompt_default "Pack projects dir" "/data/lap-packages")"
  TOOLCHAIN_ROOT="$(prompt_default "Toolchain dir" "$default_home/toolchains")"

  validate_abs_path "Install root" "$INSTALL_ROOT"
  validate_abs_path "State dir" "$STATE_DIR"
  validate_abs_path "Project workspace root" "$WORKSPACE_ROOT"
  validate_abs_path "Pack projects dir" "$PACKAGES_ROOT"
  validate_abs_path "Toolchain dir" "$TOOLCHAIN_ROOT"

  cat <<EOF

Planned install
---------------
release:          $release_version
daemon user:      $DAEMON_USER
daemon group:     $DAEMON_GROUP
install root:     $INSTALL_ROOT
state dir:        $STATE_DIR
workspace root:   $WORKSPACE_ROOT
pack projects:    $PACKAGES_ROOT
toolchains:       $TOOLCHAIN_ROOT
default SaaS URL: $default_saas_url

Assets:
EOF
  manifest_assets_tsv "$manifest_path" | while IFS=$'\t' read -r id kind version url _sha _archive target _strip; do
    printf '  - %s (%s %s) -> %s\n' "$id" "$kind" "$version" "$(resolve_target "$target")"
  done
  printf '\n'

  if ! prompt_yes_no "Proceed with install" "y"; then
    die "installation cancelled"
  fi

  preflight_paths
  install_apt_packages
  create_dirs
  install_assets "$manifest_path" "$INSTALL_TMP_DIR"
  write_systemd_unit
  pair_and_start "$default_saas_url"
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
