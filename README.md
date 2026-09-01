# home-assistant skill

一个控制 Home Assistant 的 agent skill，同时适用于 **Claude Code** 和 **Hermes Agent**。
只依赖 Python 标准库，没有第三方包。

## 设计原则：脚本不做语义匹配

设备的 entity_id 完全不可读：

```
light.YOUR_LAMP_s_2_light     ← 这是"米家桌面学习灯"
climate.YOUR_AC            ← 这是空调
```

早期版本试图在 Python 里解决这个问题 —— 同义词表（台灯→学习灯）、域优先级、
模糊兜底。**这是错的**：调用方本来就是 LLM，它读一遍设备目录就知道对应关系，
在脚本里重做这一层既多余又更差，还得手工维护词表。

所以分工是：

```
catalog          →  输出可读的设备目录
  ↓  (LLM 在这里做语义匹配，选出 entity_id)
on / off / call  →  按【确切的 entity_id】执行
```

`on/off/toggle` 拒绝设备名，只接受 entity_id，避免多义时误操作。

## 安装

### Claude Code

```bash
git clone git@github.com:<you>/ha-skill.git ~/.claude/skills/home-assistant
cp ~/.claude/skills/home-assistant/config.example.json \
   ~/.claude/skills/home-assistant/config.json
# 编辑 config.json 填 url 和 token
```

### Hermes Agent

```bash
git clone git@github.com:<you>/ha-skill.git \
   ~/.hermes/skills/smart-home/home-assistant
```

Hermes 下会自动读 `~/.hermes/stored_tokens.json` 的 `home_assistant` 段，
不需要单独的 config.json。

## 配置

按顺序查找第一个可用的：

| 顺序 | 位置 |
|---|---|
| 1 | 环境变量 `HA_URL` / `HA_TOKEN` |
| 2 | `~/.claude/skills/home-assistant/config.json` |
| 3 | `~/.hermes/stored_tokens.json` 的 `home_assistant` / `homeassistant` 段 |

令牌获取：HA 界面 → 左下角用户名 → 底部「长期访问令牌」→ 创建。

## 命令

```
catalog [--sensors] [--all]      按设备分组的目录
grep <关键词> [--domain D]        字面过滤
state <entity_id>                状态与属性
on / off / toggle <entity_id>    开关
call <domain.service> [--entity E] [--data k=v]...
check                            连通性自检
```

## 已知坑

这些都是实际踩过的，写在这里省得重复排查：

- **HTTP 代理会截走内网请求**。机器上有 Clash 一类代理时，`urllib` 会读
  `http_proxy` 环境变量，去连 `192.168.x.x` 也走代理，表现为 502 或超时，
  看起来完全像 HA 挂了。脚本已对私网/回环地址强制 `ProxyHandler({})` 绕过。
- **PowerShell 写的 config.json 带 BOM**。`Set-Content -Encoding UTF8` 在
  Windows PowerShell 5.1 下会写 UTF-8 BOM，`json.loads` 直接抛异常。
  脚本用 `utf-8-sig` 读，并且解析失败会打警告而不是静默跳过。
- **HA 的状态是乐观更新的**。调用服务后立刻读 `/states` 拿到的是期望值，
  不是设备实测值；直接拿它测延迟会得到 2ms 这种假数字。真实的云端往返
  应该看服务调用本身的耗时（实测 100–200ms）。


## notes/

项目背景笔记的**脱敏副本** —— 网关为什么无法本地化、云端延迟实测、部署踩过的坑等。

**唯一信任源是 mail 服务器**，不是这个仓库：

```bash
ssh mail
ls ~/agent-notes/smarthome/
```

仓库里这份去掉了手机号、账号 ID、公网地址等个人标识（显示为 `<...·见 mail>`），
方便换机器时 clone 下来快速恢复上下文；需要完整细节时回 mail 上取。

## License

MIT
