> **脱敏副本。完整版在 mail 上，那里是唯一信任源：**
> `ssh mail` → `~/agent-notes/smarthome/`
>
> `<...·见 mail>` 是被移除的个人标识信息。

- [小米智能家居探测结论](xiaomi-smarthome-probe.md) — 网关固件 1.5.7 超出 XiaomiGateway3 支持范围；小爱对话记录可读（GO）；三个花了 3 条短信才定位的坑
- [HA 正式部署（mail 服务器）](ha-mail-deployment.md) — 当前生产环境；12 台设备已接入；云端控制只要 100-200ms，这改变了要不要本地化的取舍
- [Hermes 控制 HA 的 skill](hermes-ha-skill.md) — mail 与 oracle 双份 skill + 反向 SSH 隧道；脚本刻意不做语义匹配，那是 LLM 的活
- [HA 在 WSL 上的部署（已作废）](ha-wsl-deployment.md) — 仅留作踩坑记录：WSL 会话回收会杀掉容器内进程、Hyper-V 防火墙挡入站、ghcr.io 要换南大镜像
