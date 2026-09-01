---
name: home-assistant
description: 控制家里的智能设备（通过 Home Assistant）——灯、空调、电视、小爱音箱、洗衣机、电水壶、香氛机、门锁等小米/米家设备。可以开关设备、查设备状态、读传感器（温度、湿度、耗电、门锁状态、电池电量）、调用任意 HA 服务（调温度、调亮度、播放媒体）。当用户说"开灯""关空调""把空调调到26度""家里现在多少度""门锁上了吗""洗衣机洗完了吗"这类话时使用。Use whenever the user asks to turn a home device on/off, asks about a device's state, or asks about conditions at home.
---

# Home Assistant 控制

通过 HA 的 REST API 控制家里的设备。设备经小米官方 `xiaomi_home` 集成接入（云端），
往返延迟约 100–200ms。

## 工作方式：你负责语义，脚本负责执行

**脚本刻意不做任何名字猜测。** 设备的 entity_id 完全不可读
（台灯是 `light.YOUR_LAMP_s_2_light`），但"台灯 → 米家桌面学习灯"
这种对应你读一遍目录就知道，比任何硬编码同义词表都准。

所以流程永远是两步：

```
1. catalog / grep   →  看到设备和 entity_id
2. on / off / call  →  用【确切的 entity_id】执行
```

**不要凭印象猜 entity_id。** `on/off/toggle` 只接受确切 entity_id，传设备名会直接报错 ——
这是有意的，避免多义时误操作。

## 调用方式

脚本是本 skill 目录下的 `scripts/ha.py`，只依赖 Python 标准库。

```bash
# Linux / macOS
python3 ~/.claude/skills/home-assistant/scripts/ha.py <命令>

# Windows
python "%USERPROFILE%\.claude\skills\home-assistant\scripts\ha.py" <命令>

# 装在 Hermes 下时
python3 ~/.hermes/skills/smart-home/home-assistant/scripts/ha.py <命令>
```

下文用 `ha` 代指上面这一长串。

### 看有什么

```bash
ha catalog              # 按设备分组的目录, 先跑这个
ha catalog --sensors    # 附带传感器读数(温度/耗电/电量...)
ha catalog --all        # 含离线设备
ha grep 空调            # 目录太长时按字面过滤
ha grep 温度 --domain sensor
```

`grep` 是纯字面包含匹配，不做推断；找不到就换词或直接看 `catalog`。

### 查状态

```bash
ha state climate.YOUR_AC
ha check                # 连通性自检, 排障先跑这个
```

### 控制

```bash
ha on     light.YOUR_LAMP_s_2_light
ha off    switch.YOUR_DIFFUSER_on_p_2_2
ha toggle light.YOUR_DIFFUSER_s_3_ambient_light
```

### 调用任意服务

`on/off` 覆盖不了的（调温、调亮度、播放媒体）用 `call`：

```bash
# 空调设到 26 度
ha call climate.set_temperature \
   --entity climate.YOUR_AC --data temperature=26

# 切模式 (cool / dry / fan_only / heat / off)
ha call climate.set_hvac_mode \
   --entity climate.YOUR_AC --data hvac_mode=cool

# 台灯亮度 (0-255)
ha call light.turn_on \
   --entity light.YOUR_LAMP_s_2_light --data brightness=180
```

`--data` 的值按 JSON 解析，数字、`true`/`false`、数组都能直接写。

## 配置

按下列顺序查找，取第一个可用的：

1. 环境变量 `HA_URL` / `HA_TOKEN`
2. `~/.claude/skills/home-assistant/config.json`
3. `~/.hermes/stored_tokens.json` 的 `home_assistant` 或 `homeassistant` 段

config.json 格式见 `config.example.json`：

```json
{
  "url": "http://192.168.X.Y:8123",
  "token": "<HA 长期访问令牌>"
}
```

令牌获取：HA 界面左下角用户名 → 底部「长期访问令牌」→ 创建。

## 注意事项

- **门锁通常只能读不能开**。小米集成没暴露开锁服务，这是设备侧的安全设计。
- **状态是乐观更新的**：调用服务后立刻读 `state` 拿到的是期望值，不是设备实测值。
  要确认设备真动了，隔几秒再读。
- **一台设备会展开成几十个实体**（空调有 112 个，大量是"开发者模式"调试开关）。
  日常只用主体实体（`climate.` / `light.` / `media_player.` 那个）。
- **离线设备默认不显示**，加 `--all` 才有。
- **断网时全部设备不可控** —— 小米设备都走云端。
- **脚本会对私网地址强制绕过 HTTP 代理**。如果机器上有 Clash 一类的代理，
  访问 `192.168.x.x` 的请求被代理截走会表现为 502 或超时，看起来像 HA 挂了。
- 排障顺序：`check` → 看 url 对不对 → HA 是否在跑 → 走隧道时隧道是否启用。
- **小米电视关机：`button.*_turn_off_a_7_1` 会报「设备操作超时」，但通常实际已关机**。
  关机后电视不再应答 HA，状态（media_player 显示 playing）会停在最后已知值不更新——
  超时 + 状态冻结 = 关机成功的信号，以电视实际状态为准，别把超时当失败重试。
  确认方法：看该 button 的 state（按下时间戳）已更新，且电视实体 last_updated 冻结。
- **小米电视开机受限：深度关机后远程唤不醒**（BLE 本地控制只对息屏待机态有效）。
  关机远程可以（一按就关），但开机必须手动按遥控/机身——`turn_on_a_6_1` 和
  `media_player.turn_on` 调用看似成功（无报错）但电视不会亮，HA 状态变 unavailable 后冻结。
- **xiaomi_home 集成媒体播放是坏的**：play_media / search_media 对电视/音箱要么
  ServiceNotSupported（声明了能力没实现）、要么 500。要放歌/播报需要装 Xiaomi Miot Auto 社区插件。

## 远程控制 Windows 主机（2026-08-30 打通）

家里那台 Windows（ASUS TUF，主机名 `YOUR_HOST`，用户 `YOUR_USER`）可以远程开机和操作。

### 开机

```bash
ha on switch.windows_zhu_ji      # 发 WoL 魔法包，约 40 秒起来
ha state switch.windows_zhu_ji   # on/off 是 ping 10.10.10.X 实测的，不是"我以为发过包了"
```

唤醒走的是 **mail 服务器 ↔ Windows 的直连网线**（`10.10.10.X` ↔ `10.10.10.X`），不经路由器。

### 进去执行命令

```bash
ssh -J YOUR_HOST@127.0.0.1:2222 YOUR_USER@192.168.X.Y     # 走 WiFi
ssh -J YOUR_HOST@127.0.0.1:2222 YOUR_USER@10.10.10.X         # 走直连网线（WiFi 挂了也能用）
```

**锁屏也能连**（sshd 是服务，不需要有人登录桌面）。默认 shell 是 powershell.exe，
中文输出必须先设编码否则乱码：

```powershell
$OutputEncoding=[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
```

### 启动 MuMu 模拟器

⚠️ **SSH 里直接跑 `MuMuManager control -v 0 launch` 不管用**——命令返回 `errcode: 0`
但虚拟机不起。SSH 会话在 session 0，启动虚拟机需要交互式桌面。
（有意思的是 `shutdown` 从 session 0 可以用，只有 `launch` 不行。）

正确做法是用**计划任务**（已建好，`LogonType Interactive` 让它跑在桌面会话里）：

```powershell
Start-ScheduledTask -TaskName "LaunchMuMu"
```

### 判断模拟器是否真的起来了

**别信 `MuMuManager info` 的 `is_android_started`——它会一直报 false，是错的。**
用这两个：

```powershell
(Get-Process MuMuVMMHeadless -ErrorAction SilentlyContinue).Count   # >0 = 虚拟机在跑
& "<MUMU_DIR>\nx_main\adb.exe" devices                      # emulator-5554 device
& "<MUMU_DIR>\nx_main\adb.exe" -s emulator-5554 shell getprop sys.boot_completed  # 1
```

### 启动失败先查内存

模拟器配了 **16 GB / 24 核**。内存不够时 vboxmanager.log 里是
`VERR_NEM_MAP_PAGES_FAILED`（Hyper-V 映射不出这么多页），跟会话、权限都无关：

```powershell
$os=Get-CimInstance Win32_OperatingSystem; "{0:N1} GB 可用" -f ($os.FreePhysicalMemory/1MB)
```

细节和完整排查过程见 `notes/windows-remote.md`。
