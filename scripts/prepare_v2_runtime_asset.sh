#!/usr/bin/env bash
set -Eeuo pipefail

LAP_V2_TOOLS_DIR="${LAP_V2_TOOLS_DIR:-/data/lch/work/omni-stack-gen/code_v2_lap_tools}"
LAP_RUNTIME_OUT="${LAP_RUNTIME_OUT:-/data/lch/work/omni-stack-gen/release-inputs/lap-daemon-runtime}"

if [[ ! -d "$LAP_V2_TOOLS_DIR/lap" || ! -d "$LAP_V2_TOOLS_DIR/proto" ]]; then
  printf 'error: LAP_V2_TOOLS_DIR must point at code_v2_lap_tools: %s\n' "$LAP_V2_TOOLS_DIR" >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  printf 'error: python3 is required\n' >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  printf 'error: uv is required\n' >&2
  exit 2
fi

rm -rf "$LAP_RUNTIME_OUT"
mkdir -p "$LAP_RUNTIME_OUT/bin"
wheel_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$wheel_dir"
}
trap cleanup EXIT

# Use system python and --copies so the packaged runtime does not point at a
# build-user-specific uv Python path such as /home/<user>/.local/share/uv.
python3 -m venv --copies --without-pip "$LAP_RUNTIME_OUT/.venv"

# Build local workspace members into wheels before installing. Installing the
# workspace directories directly can produce editable .pth files that point back
# at the build host's source tree, which breaks after the runtime tarball is
# extracted on another machine.
uv build --wheel --out-dir "$wheel_dir" "$LAP_V2_TOOLS_DIR/proto"
uv build --wheel --out-dir "$wheel_dir" "$LAP_V2_TOOLS_DIR/lap"
UV_LINK_MODE=copy uv pip install --python "$LAP_RUNTIME_OUT/.venv/bin/python" \
  "$wheel_dir"/lap_proto-*.whl \
  "$wheel_dir"/lap-*.whl

cat > "$LAP_RUNTIME_OUT/bin/lap" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

self_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$self_dir/../.venv/bin/python" -m lap "$@"
EOF
chmod 0755 "$LAP_RUNTIME_OUT/bin/lap"

"$LAP_RUNTIME_OUT/bin/lap" --version
"$LAP_RUNTIME_OUT/.venv/bin/python" - <<'PY'
from pathlib import Path
import lap.daemon
from lap.assets.manager import AssetManager
from lap.cli import main as lap_cli
from lap.identity import Identity
import lap_proto
from lap_proto.tool_schemas import AssetEnsureInput, AssetEnsureOutput
import sysconfig

site_packages = Path(sysconfig.get_paths()["purelib"])
editable_lap_files = sorted(site_packages.glob("*editable*lap*.pth"))
if editable_lap_files:
    paths = ", ".join(str(path) for path in editable_lap_files)
    raise SystemExit(f"editable LAP package references found in runtime: {paths}")

assets_group = lap_cli.commands.get("assets")
asset_commands = set(getattr(assets_group, "commands", {}))
required_asset_commands = {"ensure", "status"}
if not required_asset_commands.issubset(asset_commands):
    missing = sorted(required_asset_commands - asset_commands)
    raise SystemExit(f"asset CLI commands missing from runtime: {missing}")

if "asset_base_url" not in Identity.model_fields:
    raise SystemExit("paired asset_base_url support is missing from runtime")

print(f"lap_proto import ok: {lap_proto.__file__}")
print(f"asset manager import ok: {AssetManager.__module__}")
print(f"asset protocol import ok: {AssetEnsureInput.__name__}/{AssetEnsureOutput.__name__}")
print(f"asset CLI commands ok: {sorted(required_asset_commands)}")
print("paired asset_base_url support ok")
print("lap.daemon import ok")
PY
printf 'runtime asset ready: %s\n' "$LAP_RUNTIME_OUT"
