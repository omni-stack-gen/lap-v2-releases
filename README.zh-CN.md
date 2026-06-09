# lap-v2-release

[English](README.md) · **简体中文**

LAP v2 守护进程部署的发布资产与安装器。

本仓库负责发布清单（manifest）、Linux 生产 VM 安装器、发布构建器，以及面向运维的安装文档——把一台全新的守护进程主机变成预期的 LAP v2 运行时形态：

- 守护进程运行时安装在所选守护进程用户的家目录下
- 状态与项目工作区位于 `/data/lap`
- pack 项目位于 `/data/lap-packages`
- `lap.service` 由 systemd 托管

当前 LAN 测试栈下，保持以下端点互不混淆：

- 配对 HTTP URL：`http://192.168.1.108:38082`
- 配对后返回的守护进程 WebSocket 端点：`ws://192.168.1.108:38081/v2/wss`
- 供 `lap_agent` 使用的 MCP HTTP 端点：`http://192.168.1.108:38080/mcp`

## LAN 测试：安装 → 配对 → 重启 → 看日志

### 1. 安装守护进程（一条命令）

从 LAN GitLab 包注册表安装（无需联网）。`LAP_RELEASE_PACKAGE_BASE` 让安装器从同一台 LAN 主机拉取清单 + 资产：

```bash
curl -fsSL "http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release/latest/install.sh" \
  | sudo env LAP_RELEASE_PACKAGE_BASE="http://192.168.1.108:8090/api/v4/projects/5/packages/generic/lap-v2-release" \
             LAP_INSTALL_SLINT_PREVIEW=1 bash
```

若主机可联网，公网默认源（GitHub）无需覆盖：

```bash
curl -fsSL https://github.com/omni-stack-gen/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_INSTALL_SLINT_PREVIEW=1 bash
```

中国大陆（或 GitHub 慢/不通时），用 `LAP_RELEASE_SOURCE=gitee` 从 Gitee 镜像安装——安装器会改从 Gitee 拉取清单与资产，而非 GitHub：

```bash
curl -fsSL https://gitee.com/lch8/lap-v2-releases/releases/download/v0.1.2/install.sh \
  | sudo env LAP_RELEASE_SOURCE=gitee LAP_INSTALL_SLINT_PREVIEW=1 bash
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
