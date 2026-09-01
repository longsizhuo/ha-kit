#!/usr/bin/env bash
# 在场状态机 —— 门锁是唯一的状态转换触发器，网络只用于确认「是否真的离开」。
#
# 为什么不是「持续扫描 + 网络状态直接驱动判定」（2026-08-28 重构前的做法）：
#   手机半夜休眠掉线 6 分钟 → 判定翻成「没人」→ 醒来重连 → 又翻成「有人回家」
#   → 音箱说话、灯亮，人被吵醒。网络本身会抖，不能直接当状态。
#
# 核心前提：**没有开门就不可能有人进出**。所以状态只在门锁事件后才允许改变。
#
#   门锁 位置=2（外侧指纹开门）→ 立刻 home。
#       指纹开门本身就是「有人进来了」的确凿证据，不需要等网络（网络实测滞后 19 秒）。
#   门锁 位置=1（内侧旋钮开门）→ 进入 leaving 判定，之后 15 分钟密集查网络。
#       开门 ≠ 离开（2026-08-27 00:08 那次只是开了下门），所以必须让网络确认。
#       陌生设备连续 2 轮归零 → away；15 分钟内没归零 → 判定没走，保持 home。
#   没有门锁事件 → 什么都不做，**不扫描**。
#
# 兜底：状态为 home 但陌生设备已连续 60 分钟为 0（比如漏掉了门锁事件），才慢速翻 away。
# 阈值定这么长是故意的——宁可慢，也不能抖。
#
# 日志: journalctl -t presence-scan
set -uo pipefail

SUBNET="${SUBNET:-192.168.31}"
IFACE="${IFACE:-wlp3s0}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOW="${ALLOW:-$HERE/../private/allowlist.txt}"
CARRIED="${CARRIED:-$HERE/../private/carried-devices.txt}"
OWN="${OWN:-$HERE/../private/own-devices.txt}"
DIR="${DIR:-/var/lib/presence}"   # 可覆盖，测试用临时目录避免污染生产状态
HA_URL="${HA_URL:-http://127.0.0.1:8123}"
TOKEN_FILE="${TOKEN_FILE:-/etc/presence-ha-token}"
LOCK_EVT=event.YOUR_LOCK_lock_event_e_2_1020
LEAVE_WINDOW=900       # 内侧开门后的【密集】判定窗口，秒（每轮都扫）
WATCH_WINDOW=7200      # 密集窗口到期仍未确认时，转入【观察】期的时长，秒（每 3 轮扫一次）
WATCH_EVERY=3          # 观察期的扫描间隔，单位「轮」（一轮 2 分钟）
ZERO_ROUNDS=2          # 窗口内陌生设备连续几轮为 0 才判定离开
FALLBACK_QUIET=3600    # 兜底：home 状态下陌生设备连续多久为 0 才慢速翻 away

mkdir -p "$DIR"
# LOG_TAG 可覆盖：测试跑的时候用别的 tag，避免把假事件写进生产 journal
# （2026-08-28 排查真实出门问题时，journal 里混进了测试留下的「内侧开门」，
#   差点被当成真实事件误判）
log() { logger -t "${LOG_TAG:-presence-scan}" "$*"; }
now() { date '+%F %T'; }
TOKEN=$(cat "$TOKEN_FILE" 2>/dev/null) || TOKEN=""
[ -z "$TOKEN" ] && { log "缺 token"; exit 1; }

ha_get() { curl -s -m 8 -H "Authorization: Bearer $TOKEN" "$HA_URL/api/states/$1" 2>/dev/null; }

# ── 1. 廉价路径：只问门锁，不扫网 ──
lock_json=$(ha_get "$LOCK_EVT")
read -r lock_ts lock_loc lock_act lock_uid <<<"$(printf '%s' "$lock_json" | python3 -c '
import json,sys
try: d=json.load(sys.stdin); a=d["attributes"]
except Exception: print("- - - -"); raise SystemExit
print(d["state"], a.get("操作位置","-"), a.get("锁动作","-"), a.get("操作ID","-"))
' 2>/dev/null || echo "- - - -")"

state=$(cat "$DIR/state" 2>/dev/null || echo home)
pending=$(cat "$DIR/pending" 2>/dev/null || echo none)
deadline=$(cat "$DIR/deadline" 2>/dev/null || echo 0)
seen_lock=$(cat "$DIR/last_lock" 2>/dev/null || echo "")

if [ "$lock_ts" != "-" ] && [ "$lock_ts" != "$seen_lock" ]; then
  echo "$lock_ts" > "$DIR/last_lock"
  if [ "$lock_act" = "2" ] && [ "$lock_loc" = "2" ]; then
    # 外侧指纹开门 = 确凿的「有人进来」，不需要网络确认
    [ "$state" != "home" ] && log "门锁：外侧开门(用户$lock_uid) → home"
    state=home; pending=none; echo 0 > "$DIR/zero"
  elif [ "$lock_act" = "2" ] && [ "$lock_loc" = "1" ]; then
    # 内侧开门 = 可能离开，进入密集判定窗口
    log "门锁：内侧开门 → 进入离开判定（${LEAVE_WINDOW}秒窗口）"
    pending=leaving; deadline=$(( $(date +%s) + LEAVE_WINDOW )); echo 0 > "$DIR/zero"
  fi
fi

# ── 2. 决定这一轮要不要扫网 ──
tick_prev=$(cat "$DIR/tick" 2>/dev/null || echo 0)
tick=$(( ( tick_prev + 1 ) % 30 ))
echo "$tick" > "$DIR/tick"
need_scan=0
[ "$pending" = "leaving" ] && need_scan=1
# 观察期：密集窗口到期但还没确认离开时进入。降频而不是放弃——
# 2026-08-29 实测：13:17 出门，手机 13:32~13:54 之间才离网（在楼下/电梯还连着 WiFi），
# 超出了 15 分钟密集窗口。旧逻辑直接放弃、退回 20 分钟兜底，空调多开了半小时。
# 窗口到期只说明「还没确认」，不说明「没走」。
[ "$pending" = "watching" ] && [ $(( ${tick_prev:-0} % WATCH_EVERY )) = 0 ] && need_scan=1
# 兜底：home 状态下每 10 轮（约 20 分钟）扫一次，防止漏掉门锁事件后永久卡在 home
[ "$state" = "home" ] && [ "$pending" = "none" ] && [ $(( tick % 10 )) = 0 ] && need_scan=1

n=-1
# FAKE_UNKNOWN 是测试钩子：跳过真实扫描，直接给定陌生设备数。
# 这个状态机的分支直接决定会不会半夜误触发把人吵醒，必须可测。
if [ -n "${FAKE_UNKNOWN:-}" ]; then
  [ "$need_scan" = "1" ] && n="$FAKE_UNKNOWN"
elif [ "$need_scan" = "1" ]; then
  for i in $(seq 1 254); do ping -c1 -W1 "$SUBNET.$i" >/dev/null 2>&1 & done
  wait; sleep 2
  carried_re="$(grep -oiE '^[0-9a-f:]{17}' "$CARRIED" 2>/dev/null | tr 'A-Z' 'a-z' | paste -sd'|')"
  own_re="$(grep -oiE '^[0-9a-f:]{17}' "$OWN" 2>/dev/null | tr 'A-Z' 'a-z' | paste -sd'|')"
  carried_here=0; guests=0
  allow_mac="$(grep -oiE '^[0-9a-f:]{17}' "$ALLOW" 2>/dev/null | tr 'A-Z' 'a-z' | paste -sd'|')"
  allow_host="$(grep -oiE '^host:[^ #]+' "$ALLOW" 2>/dev/null | sed 's/^host://I' | tr 'A-Z' 'a-z' | paste -sd'|')"
  [ -z "$allow_mac" ] && { log "白名单读不到，跳过"; exit 1; }
  n=0; unknown=""
  while read -r ip _ mac _; do
    mac="$(echo "$mac" | tr 'A-Z' 'a-z')"
    [[ "$mac" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]] || continue
    host="$(timeout 3 avahi-resolve -a "$ip" 2>/dev/null | awk '{print $2}' | tr 'A-Z' 'a-z')"
    [[ "$mac" =~ ^($allow_mac)$ ]] && continue
    [[ -n "$allow_host" && -n "$host" && "$host" =~ ^($allow_host)$ ]] && continue
    n=$((n+1)); unknown="$unknown${unknown:+,}$mac"
    # 必带设备单独标记：它比「所有设备都走了」可靠，因为人可以忘带某一台，
    # 但总有一台是绝对会带的。
    [[ -n "${carried_re:-}" && "$mac" =~ ^($carried_re)$ ]] && carried_here=1
    # 真·客人 = 既不是必带、也不是自己的其他设备。用来决定「能不能关空调」：
    # 自己忘带的手机不该阻止关空调，客人的手机应该阻止。
    if ! [[ -n "${carried_re:-}" && "$mac" =~ ^($carried_re)$ ]] \
       && ! [[ -n "${own_re:-}" && "$mac" =~ ^($own_re)$ ]]; then
      guests=$((guests+1))
    fi
  done < <(ip neigh show dev "$IFACE" 2>/dev/null | grep -vE 'FAILED|INCOMPLETE')
fi

# ── 3. 状态转换 ──
if [ "$pending" = "leaving" ] || [ "$pending" = "watching" ]; then
  z=$(cat "$DIR/zero" 2>/dev/null || echo 0)
  if [ "$n" = "0" ]; then
    z=$((z+1)); echo "$z" > "$DIR/zero"
    if [ "$z" -ge "$ZERO_ROUNDS" ]; then
      log "离开确认（$pending 阶段）：陌生设备连续 $z 轮为 0 → away"
      state=away; pending=none
    fi
  else
    echo 0 > "$DIR/zero"
    if [ "$(date +%s)" -ge "$deadline" ]; then
      if [ "$pending" = "leaving" ]; then
        # 密集窗口到期 ≠ 结论。降频继续观察，别直接放弃。
        log "密集窗口到期：仍有 $n 台陌生设备 → 转入观察期（每 $((WATCH_EVERY*2)) 分钟扫一次，共 $((WATCH_WINDOW/60)) 分钟）"
        pending=watching; deadline=$(( $(date +%s) + WATCH_WINDOW ))
      else
        log "观察期结束：仍有 $n 台陌生设备 → 判定没走，保持 $state"
        pending=none
      fi
    fi
  fi
elif [ "$state" = "home" ] && [ "$n" = "0" ]; then
  # 兜底：慢速。连续 FALLBACK_QUIET 秒都是 0 才翻，宁可慢也不能抖。
  q0=$(cat "$DIR/quiet_since" 2>/dev/null || echo 0)
  [ "$q0" = "0" ] && { q0=$(date +%s); echo "$q0" > "$DIR/quiet_since"; }
  if [ $(( $(date +%s) - q0 )) -ge "$FALLBACK_QUIET" ]; then
    log "兜底：陌生设备已 $((FALLBACK_QUIET/60)) 分钟为 0（可能漏了门锁事件）→ away"
    state=away; echo 0 > "$DIR/quiet_since"
  fi
elif [ "$n" -gt 0 ]; then
  echo 0 > "$DIR/quiet_since"
fi

echo "$state" > "$DIR/state"; echo "$pending" > "$DIR/pending"; echo "$deadline" > "$DIR/deadline"

# ── 4. 推给 HA ──
hs=$([ "$state" = "home" ] && echo on || echo off)
curl -s -m 10 -o /dev/null -X POST "$HA_URL/api/states/binary_sensor.someone_home" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"state\":\"$hs\",\"attributes\":{\"friendly_name\":\"有人在家\",\"device_class\":\"presence\",\"pending\":\"$pending\",\"unknown_count\":$n,\"scanned\":$need_scan}}"

# 必带设备单独一个实体。只在真的扫过网时才更新，没扫就保持上一次的值。
if [ "$need_scan" = "1" ] && [ -n "${carried_re:-}" ]; then
  cs=$([ "${carried_here:-0}" = "1" ] && echo on || echo off)
  echo "$cs" > "$DIR/carried"
  # 必带设备不在、却还有别的陌生设备在，且持续很久 → 多半是隐私 MAC 变了
  if [ "$cs" = "off" ] && [ "$n" -gt 0 ]; then
    w=$(cat "$DIR/carried_warn" 2>/dev/null || echo 0); w=$((w+1)); echo "$w" > "$DIR/carried_warn"
    [ "$w" = "30" ] && log "WARN: 必带设备已连续 30 轮不在网，但仍有 $n 台陌生设备——隐私 MAC 可能已变，请更新 carried-devices.txt"
  else
    echo 0 > "$DIR/carried_warn"
  fi
  curl -s -m 10 -o /dev/null -X POST "$HA_URL/api/states/sensor.guest_devices" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"state\":${guests:-0},\"attributes\":{\"friendly_name\":\"客人设备数\",\"unit_of_measurement\":\"台\"}}"
  curl -s -m 10 -o /dev/null -X POST "$HA_URL/api/states/binary_sensor.carried_phone_home" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"state\":\"$cs\",\"attributes\":{\"friendly_name\":\"必带手机在家\",\"device_class\":\"presence\"}}"
fi

printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(now)" "$state" "$pending" "$n" "$need_scan" "${carried_here:-?}" >> "$DIR/state-log.tsv"
