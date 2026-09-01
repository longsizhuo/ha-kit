---
name: ha-mail-deployment
description: "Home Assistant 的正式部署位置（mail 服务器）与接入现状；以及\"云端控制延迟只有 100-200ms\"这个改变方案取舍的实测数字"
metadata: 
  node_type: memory
  type: project
  originSessionId: f45fcce1-11c7-437e-a249-469cec1202d8
  modified: 2026-08-23T16:17:56.776Z
---

> **脱敏副本。完整版在 mail 上，那里是唯一信任源：**
> `ssh mail` → `~/agent-notes/smarthome/`
>
> `<...·见 mail>` 是被移除的个人标识信息。


2026-08-24 起，HA 正式跑在 **mail 服务器**上，不再用 WSL（[[ha-wsl-deployment]] 已作废，只留作踩坑记录）。

**部署**
- `YOUR_HOST@192.168.X.Y`（hostname `mail.YOUR_HOST.com`，Ubuntu 22.04.5）。ssh 别名 `mail` 已配，公钥免密。
- HA 在 `/opt/ha`，docker compose，`network_mode: host`，镜像 `homeassistant/home-assistant:stable`（从 `ghcr.nju.edu.cn` 拉，Docker Hub 在这台不可达）。
- **必须用原生 docker 引擎，不能用 Docker Desktop** —— CLI 默认 context 是 `desktop-linux`，它在 VM 里跑容器导致 `/opt/ha` 挂不进去（报 "Mounts denied"）。已 `docker context use default`。
- `systemctl enable docker` 已设（原本是 disabled，重启后 HA 起不来）。
- ufw 默认 deny incoming，已放行 8123。
- **`internal_url` 必须设成 `http://192.168.X.Y:8123`**，否则 OAuth 回调会跳到解析不了的 `homeassistant.local:8123`。存在 `.storage/core.config`，该目录属 root，改它要 sudo。
- HA 长期访问令牌在 `/opt/ha/.ha_token`（600），网关 token 在 `/opt/ha/.gw_token`。

**这台机器同时跑着邮件服务**（postfix:25、web:80/443、MySQL:3306、Redis:6379、hermes-gateway.service、一个 napcat 容器）。动任何东西前先确认不撞这些。注意 3306 和 6379 对 Anywhere 开放，且 1194 OpenVPN 端口开着 —— 用户已知悉，未处理。

**接入现状**：小米官方集成 `xiaomi_home` v0.4.7（OAuth 2.0，不存密码）已登录，账号 <userId·见 mail>，区域中国大陆。**12 台设备 / 396 实体**。多模网关本身也以云端方式接入了（27 实体）。另装了 XiaomiGateway3 v4.2.0 但因 key 死锁用不了，见 [[xiaomi-smarthome-probe]]。

**关键实测：小米云端控制往返只有 100–200ms**（服务调用 83–477ms，中位数约 100ms，单次复测 195ms）。这个数字**削弱了原方案里"本地化是为了降延迟"的论证** —— 云端已经够快，本地化剩下的真实价值只有**断网可用性**。要不要为此上 ZigBee 协调器，应该按这条重新权衡，而不是按延迟。

**测延迟的坑**：HA 服务调用返回后会**乐观更新**本地状态，直接轮询 `states` 会测出 2ms 的假数字。可信指标是服务调用本身的往返耗时；用 `/history/period` 可验证一条指令只产生了 1 次状态写入（没有设备确认包）。
