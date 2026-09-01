#!/usr/bin/env python3
"""Wake-on-LAN：往局域网发魔法包唤醒电脑。

    wol.py <MAC> [--broadcast 192.168.X.Y] [--repeat 3]

魔法包 = 6 字节 0xFF + 目标 MAC 重复 16 次，UDP 广播到 9 端口。
必须从**同一个局域网**发出去——路由器默认不转发定向广播，所以这个脚本得跑在
mail 服务器上（192.168.X.Y），从公网发是没用的。

能不能唤醒取决于目标机器，脚本这边只负责把包发对：
  1. 网卡在关机/睡眠时仍要供电（BIOS: Wake on LAN / Power On by PCI-E 打开）
  2. Windows 网卡属性 → 电源管理 → 允许此设备唤醒计算机 + 只允许魔法包唤醒
  3. **关掉 Windows 的「快速启动」**——它让关机变成混合休眠，多数主板在这个状态下
     不响应 WoL。控制面板 → 电源选项 → 选择电源按钮的功能 → 更改当前不可用的设置
  4. 有线连接最可靠。WiFi 的 WoWLAN 支持看网卡和驱动，经常不灵
"""
import argparse, socket, sys


def magic(mac: str) -> bytes:
    raw = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(raw) != 12:
        raise SystemExit(f"MAC 格式不对: {mac}")
    return b"\xff" * 6 + bytes.fromhex(raw) * 16


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mac")
    ap.add_argument("--broadcast", default="192.168.X.Y")
    ap.add_argument("--port", type=int, default=9)
    ap.add_argument("--repeat", type=int, default=3, help="连发几次，丢包时更可靠")
    ap.add_argument("--iface", help="直接从这块网卡发裸以太网帧（点对点直连用，不需要 IP）")
    a = ap.parse_args()

    pkt = magic(a.mac)

    if a.iface:
        # 二层直发：WoL 本质是以太网帧，不需要 IP、不需要路由器。
        # 两台机器用一根网线直连时用这个——直连链路上双方都可以没有 IP 地址。
        # 需要 root（AF_PACKET）。
        dst = bytes.fromhex(a.mac.replace(":", "").replace("-", ""))
        try:
            s2 = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
            s2.bind((a.iface, 0))
            src = s2.getsockname()[4]
            # EtherType 0x0842 是 WoL 的惯用值；也有网卡只认帧内的魔法包内容而不看类型
            frame = dst + src + b"\x08\x42" + pkt
            for _ in range(a.repeat):
                s2.send(frame)
            s2.close()
        except PermissionError:
            raise SystemExit("二层直发需要 root：sudo ./wol.py ... --iface " + a.iface)
        except OSError as e:
            raise SystemExit(f"网卡 {a.iface} 发送失败: {e}")
        print(f"已从 {a.iface} 直发 {a.repeat} 个裸以太网帧 → {a.mac}")
        print("（点对点直连不经路由器，目标网卡只要有待机供电就能收到）")
        return
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # 7 和 9 都是 WoL 惯用端口，两个都发，省得目标只听其中一个
    for _ in range(a.repeat):
        for port in {a.port, 7, 9}:
            s.sendto(pkt, (a.broadcast, port))
    s.close()
    print(f"已发送 {a.repeat} 轮魔法包 → {a.mac}  广播 {a.broadcast} 端口 {sorted({a.port,7,9})}")
    print("（发包成功不代表能唤醒——目标机器的 BIOS/网卡/快速启动设置才是决定因素）")


if __name__ == "__main__":
    main()
