# Cross-Machine Test Release

Use this internal path when one Ubuntu host builds release assets and another
Ubuntu host installs the LAP daemon before customer publishing. Customer
installs should use `docs/install/customer-release.md`.

The internal source of truth is the local GitLab project:

```text
http://<gitlab-host>:8090/canhaolin/lap-v2-release
```

Do not commit generated tarballs into Git. Publish them to the GitLab Generic
Package Registry, then make the installer consume that registry URL via the
generated manifest.

## 1. Prerequisites

On the build machine:

```bash
export GITLAB_BASE_URL=http://192.168.1.108:8090
export GITLAB_PROJECT_ID=5
export GITLAB_PROJECT_PATH=canhaolin/lap-v2-release
export GITLAB_TOKEN=<personal-access-token-with-api-or-write_package_registry>
export RELEASE_VERSION=v0.1.0-test-$(date -u +%Y%m%d%H%M%S)
export PACKAGE_NAME=lap-v2-release
export RELEASE_INPUTS=/data/lch/work/omni-stack-gen/release-inputs
export RELEASE_DIST=/data/lch/work/omni-stack-gen/lap-v2-release-test-dist
```

The current local GitLab project id is `5`. If the project is recreated, get it
from the GitLab project page HTML (`data-project-id`) or the project settings.

## 2. Push The Installer Repo

The target host should pull `install.sh` from GitLab. Make sure this repository
has been pushed to the local GitLab first.

```bash
cd /data/lch/work/omni-stack-gen/lap-v2-releases
git status --short --branch
git push
```

For the smoothest target-host command, merge the installer branch into `main`
or create a release tag after review. During branch testing, clone the branch
explicitly on the target host.

## 3. Prepare Release Inputs

Prepare the daemon runtime asset:

```bash
cd /data/lch/work/omni-stack-gen/lap-v2-releases
LAP_V2_TOOLS_DIR=/data/lch/work/omni-stack-gen/code_v2_lap_tools \
LAP_RUNTIME_OUT="$RELEASE_INPUTS/lap-daemon-runtime" \
  scripts/prepare_v2_runtime_asset.sh
```

This runtime asset packages the v2 `lap` Python daemon plus its dependencies in
a copied system-Python venv. Verify `"$RELEASE_INPUTS/lap-daemon-runtime/bin/lap" --version`
prints `2.0.0`. Do not use the old `code/dist/lap-v0.23.0-linux-x86_64`
binary for the v2 `lap_mcp` stack; it pairs against the legacy
`/v1/proxy/register` API instead of `/v1/pair`.

Prepare the toolchain asset:

```bash
rm -rf "$RELEASE_INPUTS/toolchains"
mkdir -p "$RELEASE_INPUTS/toolchains"
cp -a /data/lch/work/omni-stack-gen/code/saas_mock/content/toolchains/. \
  "$RELEASE_INPUTS/toolchains/"
```

The pack project source is configured in
`examples/release-config.example.json` as:

```text
/data/lch/work/omni-stack-gen/lap-packages
```

## 4. Build Manifest And Tarballs

The manifest must point at the GitLab Package Registry URLs that the target host
will download.

```bash
export PACKAGE_BASE_URL="$GITLAB_BASE_URL/api/v4/projects/$GITLAB_PROJECT_ID/packages/generic/$PACKAGE_NAME/$RELEASE_VERSION"

python3 scripts/build_release.py \
  --config examples/release-config.example.json \
  --out-dir "$RELEASE_DIST" \
  --release-version "$RELEASE_VERSION" \
  --asset-base-url "$PACKAGE_BASE_URL" \
  --default-saas-url "http://192.168.1.108:38082"

cp install.sh "$RELEASE_DIST/$RELEASE_VERSION/install.sh"
python3 scripts/validate_manifest.py "$RELEASE_DIST/$RELEASE_VERSION/manifest.json"
ls -lh "$RELEASE_DIST/$RELEASE_VERSION"
```

Expected files:

```text
install.sh
manifest.json
SHA256SUMS
lap-daemon-runtime.tar.gz
lap-pack-projects.tar.gz
lap-toolchains.tar.gz
```

## 5. Upload Assets To GitLab Package Registry

Use a fresh `RELEASE_VERSION` for each upload. GitLab Generic Package Registry
does not overwrite an existing file in the same package/version cleanly.

```bash
cd "$RELEASE_DIST/$RELEASE_VERSION"

for file in \
  install.sh \
  manifest.json \
  lap-daemon-runtime.tar.gz \
  lap-pack-projects.tar.gz \
  lap-toolchains.tar.gz \
  SHA256SUMS
do
  curl --fail --show-error \
    --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    --upload-file "$file" \
    "$PACKAGE_BASE_URL/$file"
done
```

Verify from the build machine:

```bash
curl -fL "$PACKAGE_BASE_URL/manifest.json" | python3 -m json.tool >/tmp/lap-manifest.check.json
curl -fL "$GITLAB_BASE_URL/$GITLAB_PROJECT_PATH/-/raw/main/README.md" | head
```

If package download requires authentication, make the project/package public for
the v1 test or add deploy-token support to the installer before using a private
registry. The current installer downloads plain HTTP(S) URLs and does not attach
GitLab auth headers.

## 6. Install On The Target Host

Preferred production-like path after the installer branch is merged to `main`:

```bash
export GITLAB_BASE_URL=http://192.168.1.108:8090
export GITLAB_PROJECT_ID=5
export GITLAB_PROJECT_PATH=canhaolin/lap-v2-release
export RELEASE_VERSION=<the-uploaded-release-version>
export PACKAGE_NAME=lap-v2-release
export PACKAGE_BASE_URL="$GITLAB_BASE_URL/api/v4/projects/$GITLAB_PROJECT_ID/packages/generic/$PACKAGE_NAME/$RELEASE_VERSION"

curl -fsSLO "$GITLAB_BASE_URL/$GITLAB_PROJECT_PATH/-/raw/main/install.sh"
sudo env LAP_RELEASE_MANIFEST_URL="$PACKAGE_BASE_URL/manifest.json" bash install.sh
```

Branch-test path before merging to `main`:

```bash
export GITLAB_BASE_URL=http://192.168.1.108:8090
export RELEASE_VERSION=<the-uploaded-release-version>
export PACKAGE_BASE_URL="$GITLAB_BASE_URL/api/v4/projects/5/packages/generic/lap-v2-release/$RELEASE_VERSION"

git clone --branch feat/lap-daemon-installer-v1 \
  "$GITLAB_BASE_URL/canhaolin/lap-v2-release.git"
cd lap-v2-release
sudo env LAP_RELEASE_MANIFEST_URL="$PACKAGE_BASE_URL/manifest.json" bash install.sh
```

The installer is interactive. Press Enter to accept defaults unless this target
host needs different paths. For a real daemon-online test, choose pairing during
install and enter the pair code from the SaaS or pairing service.

For the current LAN test stack, the endpoint roles are:

```text
SaaS HTTP URL:          http://192.168.1.108:38082
Daemon WebSocket URL:   ws://192.168.1.108:38081/v2/wss
lap_agent MCP URL:      http://192.168.1.108:38080/mcp
```

Enter the SaaS HTTP URL at the installer prompt. The daemon WebSocket URL is
returned by the pair API and must not be pasted into that prompt.

## 7. Verify The Target Host

```bash
sudo systemctl status lap.service --no-pager
sudo journalctl -u lap.service -f
sudo cat /data/lap/install-report.json
ls -la /data/lap-packages
ls -la /home/"${SUDO_USER:-$USER}"/toolchains
```

Expected pack project entries:

```text
.venv
Pack_FD_F1_R88R30_ADB_SPINOR
Pack_RL_F1s_DV10_2_SPINOR
pack.sh
```

If the installer refuses to continue because a target directory is non-empty,
back it up or remove it before retrying. The guarded directories are the install
root, toolchain root, and pack project root.

## Fallback: Temporary HTTP Server

Only use a temporary HTTP server for local debugging when GitLab Package Registry
is unavailable. It is not the intended cross-machine acceptance path.
