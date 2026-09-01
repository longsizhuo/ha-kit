#!/usr/bin/env python3
"""每轮抓一张全量特征快照，追加到 features.jsonl，供后续做证据融合。

设计要点：**对在场探测有用的不是"设备当前什么状态"，而是"多久前被动过"。**
空调开着可能是出门没关（弱证据）；水壶刚被提起一定有人（强证据）。
所以每个实体记的是 age = 距上次状态变化的秒数，而不只是 state。

用法: ha_snapshot.py <HA_URL> <TOKEN> <输出文件> <网络判断> <陌生设备数>
"""
import json, sys, time, urllib.request
from datetime import datetime, timezone

# 强证据：这些实体变化 = 几乎肯定有人在场（必须有人动手，或设备的人感判定）
# 用【精确 entity_id】而不是子串匹配 —— 之前用 "_light"/"lamp35" 图省事，
# 把台灯的 20 个设置项（delay_time/focus_time/rest_time/pir_en…）和空调、网关的
# 指示灯全扫进来了，那些是配置和设备自身状态，跟有没有人无关。
DEAD = ("unavailable", "unknown", "none", "")

STRONG = {
    "event.YOUR_LOCK_lock_event_e_2_1020": "门锁事件",
    "event.YOUR_LOCK_doorbell_ring_e_5_1006": "门铃",
    "sensor.YOUR_LOCK_door_state_p_3_1021": "门状态",
    "light.YOUR_LAMP_s_2_light": "台灯开关",
    "sensor.YOUR_LAMP_light_on_times_p_2_2": "开灯次数",
    "light.YOUR_DIFFUSER_s_3_ambient_light": "香氛机氛围灯",
    "binary_sensor.YOUR_KETTLE_kettle_lifting_p_3_7": "水壶被提起",
    "media_player.YOUR_TV": "电视",
    "media_player.YOUR_SPEAKER": "小爱音箱",
    "media_player.YOUR_TVBOX": "小米盒子",
}
# 弱证据：状态可能是"走时没关"留下的，不能单独当在场依据
WEAK = {
    "climate.YOUR_AC": "空调",
    "humidifier.YOUR_HUMIDIFIER": "加湿器",
}


def main():
    ha_url, token, out, net_guess, unknown_n = sys.argv[1:6]
    req = urllib.request.Request(f"{ha_url}/api/states",
                                 headers={"Authorization": f"Bearer {token}"})
    states = json.load(urllib.request.urlopen(req, timeout=15))
    now = datetime.now(timezone.utc)

    def age(e):
        """距上次状态变化的秒数。"""
        try:
            t = datetime.fromisoformat(e["last_changed"].replace("Z", "+00:00"))
            return int((now - t).total_seconds())
        except Exception:
            return None

    row = {
        "ts": now.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "net_guess": net_guess,           # 网络排除法的判断
        "unknown_devices": int(unknown_n),
        "truth": None,                    # 人工标注，下面填
        "strong": {}, "weak": {}, "other_recent": [],
    }

    for e in states:
        eid, a = e["entity_id"], age(e)
        if a is None:
            continue
        if eid == "input_boolean.home_truth":
            row["truth"] = e["state"]
        elif eid in STRONG:
            row["strong"][STRONG[eid]] = {"s": e["state"][:26], "age": a,
                                          "ok": e["state"] not in DEAD}
        elif eid in WEAK:
            row["weak"][WEAK[eid]] = {"s": e["state"][:26], "age": a}
        elif a < 180:                     # 其余实体只在刚变过时才记，避免每行几百个字段
            row["other_recent"].append(eid)

    # 派生：多久没有任何"强证据"实体发生变化。
    # 必须排掉 unavailable/unknown 的实体：设备掉线本身是一次状态变化，会被算成
    # "刚有活动"把 quiet_s 拉小，方向正好反了。（2026-08-25 实测：水壶 08:48 掉线，
    # 比人出门早两小时，它的静默跟在不在家无关。）
    ages = [v["age"] for v in row["strong"].values() if v["ok"]]
    row["quiet_s"] = min(ages) if ages else None

    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  quiet={row['quiet_s']}s strong={len(row['strong'])} "
          f"recent={len(row['other_recent'])} truth={row['truth']}")


if __name__ == "__main__":
    main()
