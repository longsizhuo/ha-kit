#!/usr/bin/env python3
"""重建某天的进出时间线。默认今天。

    day-report.py [YYYY-MM-DD]

数据源与各自的职责（见 presence/sensor-coverage.md）：
  门锁   精确时刻 + 是谁进来的（出门匿名，内侧开门不需要认证）
  网络   全屋覆盖的稳态确认，但滞后（出门 ~7 分钟，回家 ~2 分钟）
  PIR    只覆盖客厅，用来区分「开了下门」和「真的走了」

单看门锁会把「开门扔垃圾」误判成出门——必须结合 PIR 和网络是否随之消失。
"""
import sqlite3, datetime, json, os, shutil, sys

DB = "/opt/ha/config/home-assistant_v2.db"
LOCK = "event.YOUR_LOCK_lock_event_e_2_1020"
NET = "binary_sensor.someone_home"
PIR = "event.YOUR_DIFFUSER_someone_move_e_4_3"
DEAD = ("unavailable", "unknown", "none", "")
USERS = {101: "本人", 102: "妈", 103: "爸", 104: "亮亮"}


def snapshot():
    tmp = "/tmp/ha_report.db"
    for e in ("", "-wal", "-shm"):
        if os.path.exists(DB + e):
            shutil.copy(DB + e, tmp + e)
    return sqlite3.connect(tmp)


def series(c, eid, a, b, with_attrs=False):
    col = "sa.shared_attrs" if with_attrs else "s.state"
    q = f"""SELECT s.last_updated_ts, {col} FROM states s
            JOIN states_meta m ON m.metadata_id=s.metadata_id
            {'LEFT JOIN state_attributes sa ON sa.attributes_id=s.attributes_id' if with_attrs else ''}
            WHERE m.entity_id=? AND s.last_updated_ts BETWEEN ? AND ? ORDER BY 1"""
    return [(datetime.datetime.fromtimestamp(t), v) for t, v in c.execute(q, (eid, a, b)) if v]


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    d0 = datetime.datetime.fromisoformat(day)
    a, b = d0.timestamp(), (d0 + datetime.timedelta(days=1)).timestamp()
    c = snapshot()

    # 门锁开锁事件（动作=2）
    opens = []
    for t, attr in series(c, LOCK, a, b, with_attrs=True):
        d = json.loads(attr)
        if d.get("锁动作") != 2:
            continue
        opens.append((t, d.get("操作位置"), d.get("操作ID"), d.get("操作方式")))

    net = [(t, s) for t, s in series(c, NET, a, b) if s not in DEAD]
    pir = [t for t, _ in series(c, PIR, a, b)]

    print(f"=== {day} 进出重建 ===\n")
    if not opens:
        print("  当天没有任何开锁事件")
    for t, loc, uid, method in opens:
        # 判定是「真的离开」还是「只是开了下门」：看之后 15 分钟内网络是否消失
        after = [s for tt, s in net if t < tt <= t + datetime.timedelta(minutes=15)]
        pir_after = [x for x in pir if t < x <= t + datetime.timedelta(minutes=15)]
        if loc == 2:
            who = USERS.get(uid, f"未知用户{uid}")
            conf = next((tt for tt, s in net if tt > t and s == "on"), None)
            lag = f"，网络 {conf:%H:%M:%S} 确认（滞后 {int((conf-t).total_seconds())} 秒）" if conf else ""
            print(f"  {t:%H:%M:%S}  ← 回家   外侧指纹，{who}{lag}")
        else:
            gone = "off" in after
            if gone:
                conf = next((tt for tt, s in net if tt > t and s == "off"), None)
                lag = f"，网络 {conf:%H:%M:%S} 确认（滞后 {int((conf-t).total_seconds())} 秒）" if conf else ""
                print(f"  {t:%H:%M:%S}  → 出门   内侧开门（匿名）{lag}")
            else:
                why = f"PIR 仍有 {len(pir_after)} 次活动" if pir_after else "网络未消失"
                print(f"  {t:%H:%M:%S}     开门未离开（{why}）")

    # 在外时长
    outs = [t for t, loc, _, _ in opens if loc == 1
            and "off" in [s for tt, s in net if t < tt <= t + datetime.timedelta(minutes=15)]]
    ins = [t for t, loc, _, _ in opens if loc == 2]
    for o in outs:
        nxt = next((i for i in ins if i > o), None)
        if nxt:
            print(f"\n  在外 {str(nxt-o).split('.')[0]}（{o:%H:%M} → {nxt:%H:%M}）")
        else:
            print(f"\n  {o:%H:%M} 出门后至今未归")


if __name__ == "__main__":
    main()
