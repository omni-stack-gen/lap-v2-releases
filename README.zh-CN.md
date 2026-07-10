# lap-v2-release

[English](README.md) · **简体中文**

LAP v2 守护进程部署的发布资产与安装器。

本仓库负责发布清单（manifest）、Linux 生产 VM 安装器、发布构建器，以及面向运维的安装文档——把一台全新的守护进程主机变成预期的 LAP v2 运行时形态：

- 守护进程运行时安装在所选守护进程用户的家目录下
- 状态与项目工作区位于 `/data/lap`
- 按需落地的 pack 项目缓存位于 `/data/lap-packages`
- 按需落地的 SoC toolchain 位于安装时选择的 toolchain 根目录
- `lap.service` 由 systemd 托管

当前 LAN 测试栈下，保持以下端点互不混淆：

- SaaS 资产 HTTP URL：`http://192.168.1.108:18000`
- 配对 HTTP URL：`http://192.168.1.108:38082`
- 配对后返回的守护进程 WebSocket 端点：`ws://192.168.1.108:38081/v2/wss`
- 供 `lap_agent` 使用的 MCP HTTP 端点：`http://192.168.1.108:38080/mcp`

## LAN 测试：安装 → 配对 → 重启 → 看日志

### 1. 安装守护进程（一条命令）

默认情况下，安装器会询问 SaaS 资产 HTTP URL，从 SaaS 下载 release
manifest，只安装 daemon runtime，并把 manifest 保存下来供后续按工程下载
板级资产，同时持久化可访问的 SaaS URL 和本地资产根目录：

```text
<SaaS asset URL>/v1/assets/lap-release/manifest.json
```

当前 LAN 栈示例：

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_SAAS_URL="http://192.168.1.108:18000" \
             LAP_PAIR_API_URL="http://192.168.1.108:38082" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

如需从公开 GitHub release 获取 daemon 启动 manifest 和 runtime，设置
`LAP_RELEASE_SOURCE=github`。运行期 Pack/toolchain 仍使用安装器持久化的
SaaS URL：

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_RELEASE_SOURCE=github \
             LAP_SAAS_URL="http://192.168.1.108:18000" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

中国大陆（或 GitHub 慢/不通时），可用 `LAP_RELEASE_SOURCE=gitee` 从
Gitee 获取 daemon 启动包。运行期 Pack/toolchain 字节仍经过 SaaS 资产
facade：

```bash
curl -fsSL https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_RELEASE_SOURCE=gitee \
             LAP_SAAS_URL="http://192.168.1.108:18000" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

旧 LAN 包注册表仍可用 `LAP_RELEASE_PACKAGE_BASE` 覆盖 daemon 启动
manifest 和 runtime 压缩包地址：

```bash
curl -fsSL "http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh" \
  | sudo env LAP_RELEASE_PACKAGE_BASE="http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release" \
             LAP_SAAS_URL="http://192.168.1.108:18000" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

安装器询问是否配对时，回答 **n** 跳过，稍后再配对。

### 2. 获取配对码

在任意能访问配对 API（`:38082`）的机器上运行：

```bash
curl -sX POST http://192.168.1.108:38082/v1/pair-requests \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"ce-plan-test","device_name":"office-board-1"}'
# -> {"pair_code":"XXXX-XXXX","pair_url":"http://192.168.1.108:38082", ...}
```

### 3. 配对守护进程

在**守护进程主机**上，使用安装器生成的助手脚本（写入 identity、应用 `ws://` 覆盖、启动服务）。`<daemon_user>` 是守护进程运行所用的用户（如 `dpower`）：

```bash
sudo /home/<daemon_user>/lap/bin/lap-pair <PAIR_CODE> --saas-url http://192.168.1.108:38082
# 示例：
sudo /home/dpower/lap/bin/lap-pair 4HAQ-64J2 --saas-url http://192.168.1.108:38082
```

> Web UI 会打印同样的 `lap-pair` 命令。**避免直接使用 `sudo …/lap pair <code>`**——以 root 运行会把 `/data/lap/identity.json` 写成 root 所有（权限 0600），而以守护进程用户身份运行的 `lap.service` 将无法读取（“permission denied”）。`lap-pair` 以守护进程用户身份执行配对，属主才正确。

> 粘贴**配对 HTTP URL**（`:38082`），而不是守护进程 WebSocket URL。`ws://…:38081/v2/wss` 端点由配对 API 返回，并自动写入 identity。

### 4. 重启 / 验证 / 日志

```bash
sudo systemctl restart lap.service
sudo systemctl status lap.service --no-pager -l
sudo cat /data/lap/identity.json          # 已配对的 identity（状态目录 = /data/lap）
sudo journalctl -u lap.service -f         # 实时日志
```

面向客户的安装形态：

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh | sudo bash
```

面向客户的发布项目应只暴露安装文档与发布产物。源码与原始构建输入留在私有/内部仓库中。

可选的 Slint 预览支持（在带显示器的守护进程主机上实时渲染生成的 `.slint`）**默认关闭**；用 `LAP_INSTALL_SLINT_PREVIEW=1` 启用——见 [Slint 预览支持](docs/install/slint-preview.md)。

## Toolchain 资产包结构

每个 toolchain 压缩包只包含自己的目录和包内元数据，不携带全局
`toolchains.toml`。在 SaaS 懒加载资产流程中，安装器不会预先下载所有
`kind=toolchain` 资产；后续编译流程按需把某个 toolchain 落地到 LAP
主机后，再基于同样的元数据刷新 `$TOOLCHAIN_ROOT/toolchains.toml`。

示例压缩包结构：

```text
riscv64-linux-x86_64-20210512/
|-- .omnistack-toolchain.toml
|-- bin/
|-- sysroot/
`-- ...
```

`.omnistack-toolchain.toml` 示例：

```toml
profile = "F1"
target = "riscv64gc-unknown-linux-gnu"
bin = ["bin"]
cc = "bin/riscv64-unknown-linux-gnu-gcc"
ar = "bin/riscv64-unknown-linux-gnu-ar"
linker = "bin/riscv64-unknown-linux-gnu-gcc"
```

一个 LAP 可以同时持有多个 SoC 的编译链；每个包提供一个不同的
`profile`，本地 registry 由已经实际落地的 toolchain 合成。

## 运行期托管资产

普通安装会创建 cache、Pack 和 toolchain 根目录，但保持 Pack/toolchain
为空。安装器只下载 `kind=daemon_runtime`；真实任务或运维命令随后按一个
selector 向 SaaS manifest 请求资产：

| Selector | 托管资产 | 本地兼容输出 |
|---|---|---|
| `--soc F1` | F1 交叉编译链 | `<toolchain-root>/toolchains.toml` 和不可变版本目录 |
| `--board FD_F1_...` | `Pack_FD_F1_...` 工程 | `<packages-root>/Pack_FD_F1_...` 指向不可变版本 |

每个 Pack 压缩包必须在自己的 `Pack_<project>` 目录内自包含 `pack.sh` 和
依赖，不再依赖共享的顶层 `pack.sh` 或 `.venv`。

安装器将以下配置写入 `<state-dir>/release-source.env`，并同步给
`lap.service`：

```text
LAP_RELEASE_SAAS_URL=<可访问的 SaaS base URL>
LAP_RELEASE_MANIFEST_URL=<SaaS base URL>/v1/assets/lap-release/manifest.json
LAP_ASSET_CACHE_DIR=<state-dir>/assets
LAP_PACKAGES_ROOT=<packages-root>
LAP_TOOLCHAINS_ROOT=<toolchain-root>
LAP_EXPECTED_UID=<daemon uid>
```

三个目录都由 daemon 用户持有。生成的 sandbox allowlist 只加入编译和
打包需要的 Pack/toolchain 根目录。重新安装 daemon runtime 时，已安装的
资产和无关 toolchain profile 会保留。

运维人员也可以主动下载或检查 daemon 使用的同一套资产。命令必须以
daemon 用户执行，以免产生混合属主：

```bash
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --soc F1
sudo -u <daemon-user> -H <install-root>/bin/lap assets ensure --board FD_F1_R88R30_ADB_SPINOR
sudo -u <daemon-user> -H <install-root>/bin/lap assets status --soc F1 --json
```

若安装时选择了非默认 state 目录，还需传入 `LAP_STATE_DIR=<state-dir>`，
CLI 才能加载安装器持久化的资产配置。

`ensure` 每次都会检查 SaaS 当前 descriptor，并输出实际 identity、版本、
SHA256、不可变路径以及是否复用了本地字节。`status` 只读本地状态，返回
`ready`、`missing` 或 `invalid`。两者都不会直接访问 PocketBase。修改资产
的命令必须以 daemon 用户运行；其他身份会在创建资产目录前被拒绝。

manifest、下载、摘要、解压、激活或本地 readiness 任一环节失败，当前操作
都会终止。旧的有效版本仍保留在磁盘，但不会作为 fallback 被本次操作使用；
修复原因后需重新开始命令或 Web 操作。

从这里开始：

- [客户发布安装指南](docs/install/customer-release.md)
- [Linux 安装器需求](docs/requirements/2026-05-26-lap-daemon-installer-v1.md)
- [Linux 安装指南](docs/install/linux-production-vm.md)
- [跨机测试发布指南](docs/install/cross-machine-test.md)
- [Slint 预览支持（可选）](docs/install/slint-preview.md)
- [Windows USB 说明](docs/install/windows-usbipd-notes.md)

开发检查：

```bash
bash -n install.sh
python3 scripts/validate_manifest.py examples/manifest.example.json
python3 scripts/build_release.py --config examples/release-config.example.json --check-only
python3 -m unittest discover -s tests
```
