---
name: ha-wsl-deployment
description: Home Assistant 跑在 WSL2 Ubuntu 上的部署位置与三个必须知道的坑（WSL 会话回收、Hyper-V 防火墙、ghcr 不可达）
metadata: 
  node_type: memory
  type: project
  originSessionId: f45fcce1-11c7-437e-a249-469cec1202d8
  modified: 2026-08-23T14:56:30.597Z
---

> **脱敏副本。完整版在 mail 上，那里是唯一信任源：**
> `ssh mail` → `~/agent-notes/smarthome/`
>
> `<...·见 mail>` 是被移除的个人标识信息。


2026-08-23 在 Windows 台式机（192.168.X.Y）上搭起 HA，用于验证小米多模网关能否本地化。见 [[xiaomi-smarthome-probe]]。

**部署位置**
- WSL2 发行版 `Ubuntu` 26.04 LTS，装在 `F:\WSL\Ubuntu`（C 盘只剩 23 GB，放不下）
- HA 数据在发行版内 `/opt/ha`，`docker-compose.yml` + `config/`
- Docker 29.1.3（Ubuntu 官方源的 `docker.io`），apt 换清华源
- `~/.wslconfig`：`networkingMode=mirrored` + `vmIdleTimeout=-1`

**三个坑**

1. **每条一次性 `wsl -d Ubuntu -- 命令` 结束时，WSL 会 SIGTERM 掉发行版内的进程**，容器里的 HA 跟着被杀，永远跑不完启动流程（日志表现为 s6 反复 `received signal 15`，而 docker 的 `RestartCount=0` —— 因为死的是容器内的 HA Core，不是容器）。必须**持有一个常驻 WSL 会话**（`wsl -d Ubuntu -u root --exec /bin/sh -c "exec sleep infinity"`）。用 `Start-Process` 起的会随父进程树被回收，没用。长期方案应做成开机计划任务。

2. **mirrored 模式下 Windows 访问不到 WSL 的监听端口**，因为 WSL 的 Hyper-V 防火墙 `DefaultInboundAction=Block`。需要管理员执行：
   `New-NetFirewallHyperVRule -Name "WSL-HomeAssistant-8123" -DisplayName "WSL Home Assistant 8123" -Direction Inbound -VMCreatorId "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" -Protocol TCP -LocalPorts 8123 -Action Allow`

3. **ghcr.io 拉不动**：`/v2/` API 通（返回 401），但下载层走 `pkg-containers.githubusercontent.com`，国内不可达；而 daemon.json 的 registry-mirrors **只对 Docker Hub 生效**。可用的是 `ghcr.nju.edu.cn`（南大镜像站）。

**排查提示**：这台机器有 Clash 代理 `127.0.0.1:7897`，Windows 和 WSL 都继承了 `http_proxy` 环境变量。用 curl 测本地服务时若见到 502，多半是代理返回的假象，要加 `--noproxy "*"`。浏览器不受影响（ProxyOverride 已含 `192.168.*`）。

**架构隐患**：这是台游戏主机，HA 需要常驻，重启频繁会导致自动化中断。长期应迁到专用小主机。
