#!/usr/bin/env python3
"""给 features.jsonl 补标注（人在不在家的地面真相）。

不用你每次进出都去点 HA 开关 —— 事后按时间段补就行，一次说一句
"我 8/25 18:00 到家、8/26 09:00 出门"，标注质量一样，摩擦为零。

用法:
    label.py <起> <止> <home|away>          标注一个时间段
    label.py --stats                        看检测率（按进出算，不按样本）
    label.py --lag                          量门锁→网络的滞后，据此定去抖轮数

例:
    label.py "2026-08-25 10:35" "2026-08-25 18:00" away
"""
import json, sys
from datetime import datetime

PATH = "/var/lib/presence/features.jsonl"


def load():
    with open(PATH, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def save(rows):
    with open(PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def parse(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(year=datetime.now().year) if fmt.startswith("%m") else d
        except ValueError:
            continue
    raise SystemExit(f"看不懂的时间: {s}")


def _flips(rows, key):
    """找出状态翻转点。返回 [(行号, 时间, 新状态), ...]"""
    out, prev = [], None
    for i, r in enumerate(rows):
        v = r.get(key)
        if v in ("on", "off") and v != prev:
            if prev is not None:
                out.append((i, datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"), v))
            prev = v
    return out


def stats(rows, window_min=60):
    """按【状态转换】评估，不按样本。

    样本每 2 分钟一条，但一天真正的信息只有两次进出——按样本算准确率会虚高到没意义
    （"永远猜没人"在出门 10 小时的数据上就能拿 83%）。真正该问的是：
    几次进出被检测到了？延迟多久？误报几次？
    """
    labeled = [r for r in rows if r.get("truth") in ("on", "off")]
    print("总行数 %d，已标注 %d (%d%%)" % (
        len(rows), len(labeled), len(labeled) * 100 // max(len(rows), 1)))
    if len(labeled) < 2:
        print("标注太少，先补几段再看")
        return

    truth = _flips(labeled, "truth")
    guess = _flips(labeled, "net_guess")
    print("\n真实进出 %d 次，系统判定翻转 %d 次" % (len(truth), len(guess)))
    if not truth:
        print("标注里没有任何进出转换——目前只有单一状态，这种数据算不出准确率。")
        print("回家后补一段 home 标注，这里才会有内容。")
        return

    matched, lags, used = 0, [], set()
    for _, t, v in truth:
        best = None
        for j, (_, gt, gv) in enumerate(guess):
            if j in used or gv != v:
                continue
            lag = (gt - t).total_seconds() / 60
            if -window_min <= lag <= window_min and (best is None or abs(lag) < abs(best[1])):
                best = (j, lag)
        if best:
            used.add(best[0]); matched += 1; lags.append(best[1])
    lags.sort()
    print("  检测到 %d / %d 次" % (matched, len(truth)))
    if lags:
        print("  延迟中位数 %+.0f 分钟（正=系统慢了，负=系统抢跑）" % lags[len(lags) // 2])
    print("  漏掉 %d 次，误报 %d 次" % (len(truth) - matched, len(guess) - len(used)))

    # 傻瓜基线：说明为什么样本准确率不能看
    on_n = sum(1 for r in labeled if r["truth"] == "on")
    base = max(on_n, len(labeled) - on_n) * 100 // len(labeled)
    acc = sum(1 for r in labeled if r["net_guess"] == r["truth"]) * 100 // len(labeled)
    print("\n（参考）按样本算: 系统 %d%%，但「永远猜多数类」的傻瓜基线就有 %d%%"
          " —— 所以别看这个数" % (acc, base))

    print("\nquiet_s 阈值扫描（单靠'多久没人碰过设备'能判多准）:")
    for th in (600, 1800, 3600, 7200, 14400):
        n = ok = 0
        for r in labeled:
            q = r.get("quiet_s")
            if q is None:
                continue
            n += 1
            ok += ("on" if q < th else "off") == r["truth"]
        if n:
            print("  quiet < %6ds (%3d分) → %d%% (%d/%d)" % (th, th // 60, ok * 100 // n, ok, n))



def lag(rows):
    """量【门锁事件 → 网络判断翻转】的滞后。

    门锁是精确时钟（事件戳到秒），网络是滞后的稳态确认：
      离家 —— 门锁先响，手机在楼道/电梯还连着，ARP 也没过期，几分钟后网络才断
      回家 —— 手机可能在楼道就连上了，网络先翻，人还没进门

    两个信号一前一后夹住真实事件，方向还相反。量出这个滞后量，
    才知道 presence-scan.sh 里的 ABSENT_NEEDED 该定几轮——现在那个 3 是拍脑袋定的。
    """
    # 门锁事件的 state 是事件时间戳字符串，变了就说明锁响了一次
    locks, prev = [], None
    for r in rows:
        ev = (r.get("strong") or {}).get("门锁事件")
        if not ev:
            continue
        if prev is not None and ev["s"] != prev:
            locks.append((datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"), ev["s"]))
        prev = ev["s"]

    flips = _flips(rows, "net_guess")
    print("门锁事件 %d 次，网络翻转 %d 次" % (len(locks), len(flips)))
    if not locks or not flips:
        print("样本不够——需要至少一次进出，且期间 cron 一直在跑。")
        return

    print("\n锁响时刻            最近的网络翻转      滞后")
    lags = []
    for lt, _ in locks:
        best = min(flips, key=lambda f: abs((f[1] - lt).total_seconds()))
        d = (best[1] - lt).total_seconds() / 60
        lags.append(d)
        print("  %s   %s → %-4s  %+6.1f 分钟" % (
            lt.strftime("%m-%d %H:%M"), best[1].strftime("%H:%M"), best[2], d))
    lags.sort()
    med = lags[len(lags) // 2]
    print("\n判定滞后中位数 %+.1f 分钟（正=网络慢，负=网络抢跑）" % med)

    # 原始滞后：陌生设备数真正归零/离零的时刻，不含去抖。
    # 【别用判定滞后去推荐去抖轮数】——判定滞后本身就包含去抖，那是循环论证。
    raws = []
    for lt, _ in locks:
        prev_n = None
        for r in rows:
            n = r.get("unknown_devices")
            t = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
            if prev_n is not None and (prev_n > 0) != (n > 0) and abs((t - lt).total_seconds()) <= 3600:
                raws.append((t - lt).total_seconds() / 60)
                break
            prev_n = n
    if raws:
        raws.sort()
        rmed = raws[len(raws) // 2]
        print("原始滞后中位数 %+.1f 分钟（陌生设备数真正变化的时刻，不含去抖）" % rmed)
        print("  → 其中 %.1f 分钟是物理延迟（走出覆盖 + ARP 过期），不可压缩" % abs(rmed))
        print("  → 其余 %.1f 分钟是去抖贡献" % abs(med - rmed))
    print("\n去抖轮数不该由滞后决定，而应由【在家期间出现假 0 的频率】决定——")
    print("去抖是用来挡假 0 的，不是用来等手机离网的。跑 --stats 看有没有误报。")


def main():
    rows = load()
    if "--stats" in sys.argv:
        return stats(rows)
    if "--lag" in sys.argv:
        return lag(rows)
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    a, b, lab = parse(sys.argv[1]), parse(sys.argv[2]), sys.argv[3]
    if lab not in ("home", "away"):
        raise SystemExit("第三个参数只能是 home 或 away")
    val = "on" if lab == "home" else "off"
    n = 0
    for r in rows:
        t = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        if a <= t <= b:
            r["truth"] = val
            n += 1
    save(rows)
    print(f"✓ 标了 {n} 行为 {lab}（{a} → {b}）")


if __name__ == "__main__":
    main()
