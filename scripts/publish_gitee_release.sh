#!/usr/bin/env bash
set -Eeuo pipefail

OWNER="${GITEE_OWNER:-lch8}"
REPO="${GITEE_REPO:-lap-v2-releases}"
TAG="${GITEE_RELEASE_TAG:-v0.1.4}"
TARGET="${GITEE_TARGET_COMMITISH:-main}"
DIST_DIR="${GITEE_RELEASE_DIST_DIR:-dist-gitee/$TAG}"
API_BASE="${GITEE_API_BASE:-https://gitee.com/api/v5}"

die() {
  printf '[gitee-release] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[gitee-release] %s\n' "$*"
}

require_token() {
  if [[ -z "${GITEE_TOKEN:-}" ]]; then
    die "GITEE_TOKEN is required"
  fi
}

require_assets() {
  local asset
  [[ -d "$DIST_DIR" ]] || die "dist dir does not exist: $DIST_DIR"
  while IFS= read -r asset; do
    [[ -f "$DIST_DIR/$asset" ]] || die "missing asset: $DIST_DIR/$asset"
  done < <(release_assets)
}

release_assets() {
  local base_assets=(
    "install.sh"
    "manifest.json"
    "SHA256SUMS"
    "lap-daemon-runtime.tar.gz"
    "lap-pack-projects.tar.gz"
  )
  local asset part
  for asset in "${base_assets[@]}"; do
    printf '%s\n' "$asset"
  done
}

curl_config() {
  local path="$1"
  umask 077
  printf 'header = "Authorization: Bearer %s"\n' "$GITEE_TOKEN" >"$path"
}

release_id_from_json() {
  python3 -c '
import json
import sys

tag = sys.argv[1]
data = json.load(sys.stdin)
if isinstance(data, list):
    for item in data:
        if isinstance(item, dict) and item.get("tag_name") == tag:
            print(item.get("id", ""))
            break
elif isinstance(data, dict):
    print(data.get("id", ""))
' "$TAG"
}

find_release_id() {
  local cfg="$1"
  curl -fsS -K "$cfg" \
    "$API_BASE/repos/$OWNER/$REPO/releases?per_page=100" |
    release_id_from_json
}

create_release() {
  local cfg="$1"
  curl -fsS -K "$cfg" \
    -X POST \
    --data-urlencode "tag_name=$TAG" \
    --data-urlencode "name=$TAG" \
    --data-urlencode "target_commitish=$TARGET" \
    --data-urlencode "body=LAP daemon release $TAG" \
    "$API_BASE/repos/$OWNER/$REPO/releases" |
    release_id_from_json
}

delete_release() {
  local cfg="$1"
  local release_id="$2"
  curl -fsS -K "$cfg" \
    -X DELETE \
    "$API_BASE/repos/$OWNER/$REPO/releases/$release_id" >/dev/null
}

upload_assets() {
  local cfg="$1"
  local release_id="$2"
  local asset

  while IFS= read -r asset; do
    log "uploading $asset"
    curl -fsS -K "$cfg" \
      -X POST \
      -F "file=@$DIST_DIR/$asset" \
      "$API_BASE/repos/$OWNER/$REPO/releases/$release_id/attach_files" >/dev/null
  done < <(release_assets)
}

main() {
  require_token
  require_assets

  local cfg_path release_id
  cfg_path="$(mktemp)"
  trap 'rm -f "${cfg_path:-}"' EXIT
  curl_config "$cfg_path"

  release_id="$(find_release_id "$cfg_path")"
  if [[ -n "$release_id" && "${GITEE_RECREATE_RELEASE:-0}" == "1" ]]; then
    log "deleting existing release $TAG id=$release_id"
    delete_release "$cfg_path" "$release_id"
    release_id=""
  fi
  if [[ -z "$release_id" ]]; then
    log "creating release $TAG on $OWNER/$REPO"
    release_id="$(create_release "$cfg_path")"
  else
    log "using existing release $TAG id=$release_id"
  fi

  [[ -n "$release_id" ]] || die "could not resolve release id for $TAG"
  upload_assets "$cfg_path" "$release_id"
  log "release published: https://gitee.com/$OWNER/$REPO/releases/tag/$TAG"
}

main "$@"
