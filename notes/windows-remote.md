# 远程控制 Windows 主机

ASUS TUF 主板，主机名 `YOUR_HOST`，用户 `YOUR_USER`（微软账户）。
2026-08-30 打通「人在外面把电脑开起来并拉起模拟器」这条链路。

## 拓扑

```
Oracle 云服务器
  └─ 反向 SSH 隧道 :2222 ──→ mail 服务器 192.168.X.Y
                                ├─ WiFi 局域网 ──→ Windows 192.168.X.Y
                                └─ 直连网线 ────→ Windows 10.10.10.X
```

直连网线是 2026-08-30 拉的：用户不愿意把线绕到路由器（走线难看），改成
mail 服务器 `enp2s0` ↔ Windows 以太网口对插。好处是 WoL 不经路由器，
且 WiFi 挂掉时仍有一条通道。

## WoL：排查花了最久，元凶在 BIOS

**唤醒必须发给有线网卡** `AA:BB:CC:DD:EE:FF`（Realtek 2.5GbE）。
无线网卡 `AA:BB:CC:DD:EE:FF`（Intel AX200）关机后不保持供电，WoWLAN 唤不醒。

Windows 侧的设置**本来就全是对的**（`*WakeOnMagicPacket`、`S5WakeOnLan`、
`WolShutdownLinkSpeed=10Mbps 优先` 都已启用），快速启动是我关的（`HiberbootEnabled=0`）。

真正的元凶：BIOS **`高级 → 高级电源管理(APM) → 由 PCI-E 设备唤醒` 原本是关闭的**。
（ASUS 的 BIOS 默认开在 EZ Mode，要按 **F7** 切到 Advanced Mode 才看得到这一项。）
改成开启后，关机 → HA 开关唤醒，**40 秒起来**。

`ErP 支持` 必须保持**关闭**。它的两个档位 `S5` 和 `S4+S5` 都会切断关机后的网卡供电。

### 判断网卡有没有进入 WoL 待机

关机后在 mail 服务器上看：

```bash
cat /sys/class/net/enp2s0/carrier   # 1 = 链路还在 = 网卡有待机供电
cat /sys/class/net/enp2s0/speed     # 降到 10 = 进入 WoL 待机模式
```

**这个信号很关键**：它证明网卡在监听、魔法包也送到了，从而把问题范围缩到主板。
没有它，会一直在网卡驱动和发包方式上白折腾。

## SSH

`C:\ProgramData\ssh\administrators_authorized_keys` 里有 Oracle 和 mail 服务器两把公钥。
管理员账户的授权文件必须放这个系统路径（不是用户目录），且要
`icacls <file> /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`——
**权限不对时 sshd 会静默忽略整个文件**，表现为「密钥明明加了却还要密码」，日志里什么都不说。

Windows 防火墙的 OpenSSH 规则只在 **Private** profile 生效。新网络（尤其无网关的直连链路）
会被判成 **Public** → 表现为「ping 通但 ssh 超时」。修法：

```powershell
$p = Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -eq "以太网" }
Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
```

## 自动登录

微软账户**无法删除密码**（密码在微软服务器上），能做的是自动登录。
Windows 11 默认把 netplwiz 的勾选框藏起来了，要先：

```powershell
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device" `
  -Name DevicePasswordLessBuildVersion -Value 0
```

然后 `netplwiz` → 取消「要使用本计算机，用户必须输入用户名和密码」→ 输**微软账户密码**
（不是 PIN，填 PIN 会导致自动登录失败并掉到「用户名+密码」的兜底登录界面）。

配好后实测：**开机 84 秒建立桌面会话，全程无人碰键盘。**

## 启动 MuMu 模拟器

### 会话隔离

SSH 会话在 session 0，从这里启动的 GUI 程序不会出现在桌面/串流里。实测：

| 做法 | 结果 |
| --- | --- |
| `MuMuManager control -v 0 launch` | 返回 `errcode: 0` 但虚拟机不起 |
| `MuMuManager control -v 0 shutdown` | **可以用**（只是 IPC 命令，不需要桌面） |
| `PsExec64 -i <sid> MuMuNxMain.exe` | 启动器能起来（MuMu 自带 PsExec64） |
| **计划任务 `LogonType Interactive`** | **正确做法**，已建好名为 `LaunchMuMu` |

```powershell
Start-ScheduledTask -TaskName "LaunchMuMu"
```

`shutdown` 能用而 `launch` 不能，这个不对称是关键线索：启动虚拟机需要桌面环境。

### ⚠️ `is_android_started` 会撒谎

`MuMuManager info -v 0` 报的 `is_android_started` / `is_process_started`
**一直是 false，即使虚拟机明明在跑**。我拿它当判据，连续几次误判成失败，
换了一堆方案，其实问题在别处。

可靠的判据：

```powershell
(Get-Process MuMuVMMHeadless -ErrorAction SilentlyContinue).Count    # >0 且占几 GB 内存
& "...\adb.exe" devices                                              # emulator-5554 device
& "...\adb.exe" -s emulator-5554 shell getprop sys.boot_completed    # 1
```

### 启动失败先看内存

模拟器配了 **16 GB / 24 核**。内存不足时 `vms\MuMuPlayer-12.0-0\logs\vboxmanager.log` 里是：

```
VERR_NEM_MAP_PAGES_FAILED | NEM failed to map page(s) into the VM
```

这是 Hyper-V 映射不出足够页面，跟会话、权限统统无关。
实测一次失败时：总内存 31.9 GB，可用仅 5.5 GB（一个游戏占了 7 GB）。

**建议把模拟器内存从 16 GB 调到 8 GB**——远程开机的场景不该依赖「电脑当时刚好空闲」。

## 排查方法论（这次栽的两个跟头）

1. **看到 `shell\MuMuPlayer.exe` 不存在就断定「安装损坏」** ——
   那是旧版遗留路径，MuMu 12 的启动器是 `nx_main\MuMuNxMain.exe`。
   我读的是一条陈旧日志，用户发来截图（模拟器好好地开着）才推翻。

2. **拿 `is_android_started` 当唯一判据** —— 它是错的，导致反复误判失败。

两次都是同一个毛病：**拿单一间接指标当结论，没有交叉验证**。
正确姿势是看进程、看内存占用、用 adb 直接问设备——多个独立来源互相印证。

还有一次差点更严重：排查「出门后手机还在网上」时，看到设备 ping 不通就准备把判据
从「有 ARP 表项」改成「必须应答 ping」。真相是用户忘带了手机、而手机息屏时同样不回
ICMP——改完会导致每晚手机息屏都被判成没人。**看到反常现象先确认事实，再改代码。**
