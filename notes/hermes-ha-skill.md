---
name: hermes-ha-skill
description: "Hermes 控制 Home Assistant 的 skill 与两台机器之间的反向 SSH 隧道；以及\"脚本不做语义匹配\"这条设计原则"
metadata: 
  node_type: memory
  type: project
  originSessionId: f45fcce1-11c7-437e-a249-469cec1202d8
  modified: 2026-08-23T17:45:44.886Z
---

> **脱敏副本。完整版在 mail 上，那里是唯一信任源：**
> `ssh mail` → `~/agent-notes/smarthome/`
>
> `<...·见 mail>` 是被移除的个人标识信息。


2026-08-24 完成。两台机器上的 Hermes 都能控制家里的 HA（[[ha-mail-deployment]]）。

**源仓库**：https://github.com/YOUR_HOST/home-assistant-skill （**private**）。要在新机器上装：clone 到 `~/.claude/skills/home-assistant` 或 `~/.hermes/skills/smart-home/home-assistant` 即可。

**已部署位置**（5 处，内容相同）：
- Claude：Windows `~/.claude/skills/home-assistant/`（带 config.json，url 用 `192.168.X.Y:8123`）、mail、oracle
- Hermes：mail 和 oracle 的 `~/.hermes/skills/smart-home/home-assistant/`

命令：`catalog` / `grep` / `state` / `on` / `off` / `toggle` / `call` / `check`。只用标准库。

**设计原则（重要，别再退回去）**：脚本**刻意不做任何语义匹配**。早期版本写了同义词表（台灯→学习灯）、域优先级、模糊兜底，用户一句"LLM 应该没有这么笨吧，你现在做的是第一层的语义识别吗"点破了——调用方就是 LLM，它读一遍 `catalog` 就知道对应关系，在 Python 里重做这层既多余又更差。现在的分工是：`catalog` 给出可读目录 → LLM 选 entity_id → `on/off/call` 按**确切 entity_id** 执行。`on/off/toggle` 拒绝设备名，只接受 entity_id，避免误操作。

**连接方式**：oracle 走**反向 SSH 隧道**，不是 Cloudflare Tunnel（那条隧道虽然配好但一直是 disabled，且 ingress 里只有 ssh.YOUR_HOST.com）。
- mail 上 `ha-tunnel.service`（system 级，enabled+active，`Restart=always`）跑
  `ssh -NT -R 127.0.0.1:8123:127.0.0.1:8123 ubuntu@<oracle公网IP·见 mail>`
- 用原生 ssh + systemd 重启代替 autossh：`ServerAliveInterval=30` 探活、`ExitOnForwardFailure=yes` 转发失败即退出
- 隧道专用密钥 `~/.ssh/id_ha_tunnel`（ed25519 无密码短语）。**不能用 mail 的 `~/.ssh/id_rsa` —— 它带密码短语，BatchMode 下必然 `Permission denied (publickey)`**，这个现象很容易误判成"公钥没授权"
- oracle 的 authorized_keys 里该键限制为 `restrict,port-forwarding,permitlisten="127.0.0.1:8123"`，拿到也开不了 shell
- 结果：零公网暴露，oracle 上 HA 就在 `127.0.0.1:8123`

**配置键名**：mail 用 `home_assistant`，oracle 上历史遗留是 `homeassistant`（带 service/desc 字段）。脚本两个都读，不强行统一。

**踩过的小坑**：`grep -qF "$KEY"` 里 KEY 为空会匹配任何文件，导致"公钥已存在"的误判——写这类脚本要先判空。
