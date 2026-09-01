#!/usr/bin/env bash
# 在场状态机自检。用假的 HA（本地 http server）和 FAKE_UNKNOWN 跑完整状态转换。
# 这个状态机决定会不会半夜误触发把人吵醒，改动后务必跑一遍。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=18923
D=$(mktemp -d)
pass=0; fail=0

# 假 HA：GET 返回当前设定的门锁事件，POST 一律 200
cat > "$D/fake_ha.py" <<'PY'
import http.server, json, os, sys
class H(http.server.BaseHTTPRequestHandler):
    def _send(self, obj):
        b=json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        try: ts,loc,act,uid = open(os.environ["LOCKFILE"]).read().split()
        except Exception: ts,loc,act,uid = "-","-","-","-"
        self._send({"state":ts,"attributes":{"操作位置":int(loc) if loc.isdigit() else loc,
                    "锁动作":int(act) if act.isdigit() else act,
                    "操作ID":int(uid) if uid.isdigit() else uid}})
    def do_POST(self): self._send({"ok":True})
    def log_message(self,*a): pass
http.server.HTTPServer(("127.0.0.1",int(sys.argv[1])),H).serve_forever()
PY
export LOCKFILE="$D/lock"
echo "- - - -" > "$LOCKFILE"
python3 "$D/fake_ha.py" $PORT & FAKE=$!
trap 'kill $FAKE 2>/dev/null; rm -rf "$D"' EXIT
sleep 1

echo "tok" > "$D/token"
# 用临时 DIR，绝不碰生产状态
export DIR="$D/state"
mkdir -p "$DIR"
run() { FAKE_UNKNOWN="$1" HA_URL="http://127.0.0.1:$PORT" TOKEN_FILE="$D/token" \
        DIR="$DIR" ALLOW="$HERE/../private/allowlist.txt" LOG_TAG=presence-scan-test \
        bash "$HERE/presence-scan.sh" >/dev/null 2>&1; }
st() { cat "$DIR/state"; }
pd() { cat "$DIR/pending"; }
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; pass=$((pass+1));
        else echo "  ✗ $1  期望=$3 实际=$2"; fail=$((fail+1)); fi }

reset() { echo home > "$DIR/state"; echo none > "$DIR/pending"
          echo 0 > "$DIR/zero"; echo 0 > "$DIR/quiet_since"; : > "$DIR/last_lock"; }

echo "── 场景1：内侧开门后网络归零 → 应判定离开 ──"
reset; echo "T1 1 2 0" > "$LOCKFILE"; run 3
chk "内侧开门进入 leaving" "$(pd)" "leaving"
run 0; chk "第1轮归零还不翻" "$(st)" "home"
run 0; chk "第2轮归零 → away" "$(st)" "away"

echo "── 场景2：内侧开门但人没走（陌生设备一直在）→ 应保持 home ──"
reset; echo "T2 1 2 0" > "$LOCKFILE"; run 3
chk "进入 leaving" "$(pd)" "leaving"
for i in 1 2 3 4 5; do run 3; done
chk "网络一直有设备 → 仍是 home" "$(st)" "home"

echo "── 场景3：外侧指纹开门 → 应立刻 home，不等网络 ──"
reset; echo away > "$DIR/state"
echo "T3 2 2 101" > "$LOCKFILE"; run ""
chk "外侧开门立刻 home" "$(st)" "home"
chk "不进入任何 pending" "$(pd)" "none"

echo "── 场景4：没有门锁事件 → 状态不变，且不扫网 ──"
reset; echo "T3 2 2 101" > "$LOCKFILE"   # 同一个事件，不算新
for i in 1 2 3; do run ""; done
chk "无新事件保持 home" "$(st)" "home"
chk "无新事件不进 pending" "$(pd)" "none"

echo "── 场景5：密集窗口到期仍未确认 → 应转观察期而非放弃 ──"
reset; echo "T5 1 2 0" > "$LOCKFILE"; run 3
chk "进入 leaving" "$(pd)" "leaving"
# 把 deadline 提前到过去，模拟 15 分钟窗口到期
echo 1 > "$DIR/deadline"
run 3
chk "窗口到期转 watching（不是 none）" "$(pd)" "watching"
chk "此时仍是 home" "$(st)" "home"
# 观察期里手机终于离网
echo 0 > "$DIR/tick"      # 让 tick_prev%3==0，观察期这一轮会扫
run 0; echo 0 > "$DIR/tick"; run 0
chk "观察期内确认离开 → away" "$(st)" "away"

echo "── 场景6：观察期也到期 → 才判定没走 ──"
reset; echo "T6 1 2 0" > "$LOCKFILE"; run 3
echo 1 > "$DIR/deadline"; run 3
chk "转入 watching" "$(pd)" "watching"
echo 1 > "$DIR/deadline"; echo 0 > "$DIR/tick"; run 3
chk "观察期到期 → 放弃，回 none" "$(pd)" "none"
chk "仍是 home" "$(st)" "home"

echo
echo "通过 $pass，失败 $fail"
[ "$fail" -eq 0 ]
