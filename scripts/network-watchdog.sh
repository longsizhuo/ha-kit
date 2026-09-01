#!/usr/bin/env bash
# 网络看门狗 —— 分层诊断，每层只用对症的修复手段。
#
# 由两个脚本合并而来（2026-08-25）：
#   - 原 ~/network-watchdog.sh：ping 8.8.8.8 失败就重启 Clash / 重置 DNS
#   - 新加的 wifi-watchdog.sh：网关不可达就重置无线网卡
# 并存会互相打架（网关一断两边同时动手），所以合并成一个决策树。
#
#   网关不通                    → 二层问题，重置无线网卡
#   网关通 / 国内 DNS 不通       → 路由器或宽带的事，本机修不了，只记日志
#   国内通 / 8.8.8.8 不通        → Clash 或 DNS 劫持坏了，重启 Clash → 仍不通则重置 resolv.conf
#
# 日志: journalctl -t network-watchdog
set -uo pipefail

IFACE="${IFACE:-$(for d in /sys/class/net/*/wireless; do [ -e "$d" ] && basename "$(dirname "$d")" && break; done)}"
PROBE_CN="${PROBE_CN:-223.5.5.5}"    # 国内可达，验"有没有外网"
PROBE_GFW="${PROBE_GFW:-8.8.8.8}"    # 需要 Clash，验"代理通不通"
NEED_FAILS="${NEED_FAILS:-2}"        # 网关连续几轮不通才重置网卡，避开瞬时抖动
STATE=/run/network-watchdog.fail

log() { logger -t network-watchdog "$*"; }
ok()  { ping -c2 -W2 "$1" >/dev/null 2>&1; }

[ -z "$IFACE" ] && { log "找不到无线网卡，退出"; exit 0; }
GW="$(ip route show default 2>/dev/null | awk '{print $3; exit}')"

# ── 第一层：二层链路 ──
if [ -z "$GW" ] || ! ok "$GW"; then
  n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE"
  if [ "$n" -lt "$NEED_FAILS" ]; then
    log "网关 ${GW:-无默认路由} 不可达 ($n/$NEED_FAILS)，再观察一轮"; exit 0
  fi
  log "网关连续 $n 轮不可达 → 重置 $IFACE"
  if [ -n "${DRY_RUN:-}" ]; then log "DRY_RUN：跳过重置"; rm -f "$STATE"; exit 0; fi
  if command -v nmcli >/dev/null 2>&1; then
    nmcli device disconnect "$IFACE" >/dev/null 2>&1 || true; sleep 5
    nmcli device connect "$IFACE" >/dev/null 2>&1 || true
  else
    ip link set "$IFACE" down; sleep 5; ip link set "$IFACE" up
  fi
  rm -f "$STATE"; exit 0
fi
rm -f "$STATE"

# ── 第二层：外网 ──
if ! ok "$PROBE_CN"; then
  log "网关 $GW 通但 $PROBE_CN 不通 → 路由器/宽带的问题，本机修不了"
  exit 0
fi

# ── 第三层：Clash / DNS 劫持 ──
ok "$PROBE_GFW" && exit 0
log "国内网正常但 $PROBE_GFW 不通 → 重启 clash-verge-service"
[ -n "${DRY_RUN:-}" ] && { log "DRY_RUN：跳过重启 Clash"; exit 0; }
systemctl restart clash-verge-service 2>/dev/null || log "clash-verge-service 重启失败"
sleep 15
ok "$PROBE_GFW" && { log "重启 Clash 后恢复"; exit 0; }

log "仍不通 → 重置 resolv.conf 并重启 cloudflared"
echo "nameserver 1.1.1.1" > /etc/resolv.conf
systemctl restart cloudflared 2>/dev/null || log "cloudflared 重启失败"
