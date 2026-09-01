# ha-kit

Home Assistant 的一套**在场探测 + 远程控制**工具，从一个真实的家里长出来的，
不是设计出来的示例工程。

判断家里有没有人、出门自动关空调、回家自动开灯并语音播报、远程唤醒并操作电脑。
全部基于 HA 的 REST API，脚本只依赖 Python 标准库。

## 这个仓库的特别之处：踩坑记录比代码多

`notes/` 里保留了完整的排查过程——**包括所有走错的路和被数据推翻的假设**。
代码本身不复杂，真正难的是知道哪些方案物理上就不成立。举几个例子：

- **持续扫描网络来判断在场是错的**：手机半夜休眠掉线会翻成「没人」，醒来重连又翻成
  「有人回家」，于是音箱说话、灯亮，人被吵醒。去抖只能拖慢翻转，消不掉。
  正解是**门锁事件驱动的状态机**——没开门就不可能有人进出，状态只在开门后才允许改变。
- **设备活动判断不了「没人」**：实测把 7 个信号全并起来，确认在家的 34 小时里最长
  静默 13.5 小时，而实际出门只有 5.4 小时——两者在这个特征上无法分离。
  人在家不代表会去碰设备，而传感器又有大片盲区。设备信号**只能升不能降**。
- **人可以忘带手机**：所以设备要分三类（必带 / 本人其他 / 真客人），
  否则「自己忘在家的手机」和「客人的手机」行为一样，但期望完全相反。

这些结论都是**否定性的**，靠实测数据得到，能帮你省掉几周走弯路。

## 给 AI agent 的安装提示

如果你是在帮人部署这套东西：

1. **先读 `notes/sensor-coverage.md`**——它决定了哪些方案在这个家里物理上不可能成立。
   传感器覆盖图比任何算法都重要。
2. **`SKILL.md` 是操作手册**，`notes/` 是设计依据和踩坑记录，两者都要读。
3. 所有 `YOUR_XXX` 占位符必须换成真实 entity_id。用 `scripts/ha.py catalog` 列出来，
   **不要猜**——脚本刻意不做名字猜测，因为多义时误操作的代价比多问一句高。
4. 三个 `presence/*.example.txt` 必须按实际设备填写，去掉 `.example`。
   填错的后果见 `notes/presence-detection.md` 里「设备三分类」一节。
5. **改任何判据前先跑 `scripts/test-presence.sh`**（16 项断言）。这个状态机直接决定
   会不会半夜误触发把人吵醒。

## 必须自己填的东西

| 文件 | 内容 | 怎么获得 |
| --- | --- | --- |
| `presence/allowlist.example.txt` | 家电 MAC 白名单 | 主动扫全网段后逐个辨认，见 notes |
| `presence/carried-devices.example.txt` | 必带手机的 MAC | 出门时观察哪台离网 |
| `presence/own-devices.example.txt` | 本人其他设备 | 留在家里的那些 |
| `config.json` | HA 地址与长期令牌 | 抄 `config.example.json` |
| `SKILL.md` / `ha/automations.yaml` 里的 `YOUR_XXX` | 设备 entity_id | `scripts/ha.py catalog` |

## 目录

```
scripts/ha.py              HA 控制 CLI（catalog / state / on / off / call）
scripts/presence-scan.sh   在场状态机，门锁事件驱动
scripts/test-presence.sh   状态机自检，16 项断言
scripts/day-report.py      重建某天的进出时间线
scripts/wol.py             Wake-on-LAN，支持 UDP 广播与二层裸帧
scripts/network-watchdog.sh 分层网络看门狗
ha/automations.yaml        回家欢迎仪式 + 出门关空调
notes/                     设计依据、踩坑记录、真实部署日志
```

## 硬件前提

在场探测依赖**智能门锁**提供进出事件。没有门锁的话，状态机的转换触发器要换成别的
（人体传感器、地磁门磁），但「网络只做确认、不做判定」这个核心结构仍然适用。

## 许可

见 LICENSE。这是从一个具体的家里长出来的工具，直接拿去改，不必保持通用。
