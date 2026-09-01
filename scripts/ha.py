#!/usr/bin/env python3
"""Home Assistant 控制工具 — 供 Hermes skill 调用。

设计原则: 这个脚本【不做语义匹配】。
调用方是 LLM, 它读一遍设备目录就能把"台灯"对应到"米家桌面学习灯",
在 Python 里维护同义词表和模糊匹配纯属重复劳动, 而且做得更差。

所以分工是:
    catalog  -> 给 LLM 一份可读的设备目录 (它据此选出 entity_id)
    on/off/call/state -> 按【确切的 entity_id】执行

只用标准库。凭据从 ~/.hermes/stored_tokens.json 的 home_assistant 段读:
    {"home_assistant": {"url": "...", "token": "..."}}
也可用 HA_URL / HA_TOKEN 环境变量覆盖。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import ipaddress
import urllib.parse

# 配置来源, 按顺序找第一个可用的。
# 同一份脚本要同时服务 Claude(Windows) 和两台机器上的 Hermes(Linux),
# 各自的配置习惯不同, 所以全都认。
CONFIG_PATHS = [
    (Path.home() / ".claude" / "skills" / "home-assistant" / "config.json", None),
    (Path.home() / ".hermes" / "stored_tokens.json", ("home_assistant", "homeassistant")),
]

# 设备"主体"实体所在的域, 越靠前越像是这台设备的代表
PRIMARY = ("climate", "media_player", "light", "humidifier", "vacuum",
           "cover", "lock", "fan", "water_heater", "switch")


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def load_cfg():
    url, token = os.environ.get("HA_URL"), os.environ.get("HA_TOKEN")
    if not (url and token):
        for path, keys in CONFIG_PATHS:
            if not path.is_file():
                continue
            try:
                # utf-8-sig: Windows 上用 PowerShell 的 Set-Content -Encoding UTF8
                # 写出来的文件带 BOM, 普通 utf-8 解析会直接抛异常
                d = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                # 不能静默跳过 —— 否则"配置文件存在但解析失败"会伪装成"没有配置",
                # 完全看不出真正的原因
                print(f"警告: {path} 解析失败, 已跳过 ({e})", file=sys.stderr)
                continue
            c = d
            if keys:
                for k in keys:
                    if isinstance(d.get(k), dict):
                        c = d[k]
                        break
                else:
                    continue
            if c.get("url") and c.get("token"):
                return (url or c["url"]).rstrip("/"), token or c["token"]
    if not url or not token:
        die("缺少配置。任选其一:\n"
            "  1) 环境变量 HA_URL / HA_TOKEN\n"
            "  2) ~/.claude/skills/home-assistant/config.json  {\"url\":..., \"token\":...}\n"
            "  3) ~/.hermes/stored_tokens.json 的 home_assistant 段")
    return url.rstrip("/"), token


def _is_private(host):
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost",) or host.endswith(".local")


def _opener(url):
    """连内网地址时强制绕开代理。

    这台 Windows 设了 http_proxy=127.0.0.1:7897 (Clash), 而 urllib 会读它,
    于是访问 192.168.X.Y 的请求被送进代理, 表现为 502 或超时 ——
    看起来完全像"HA 挂了", 极难定位。系统代理的 ProxyOverride 对 urllib 无效。
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if _is_private(host):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def api(path, payload=None, timeout=30):
    url, token = load_cfg()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{url}/api{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if data is not None else "GET")
    try:
        with _opener(url).open(req, timeout=timeout) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        die(f"HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"连不上 HA ({url}): {e.reason}\n"
            f"  排查: 地址是否正确 / HA 是否在跑 / 从外网调用时隧道是否启用")


def name_of(s):
    return s.get("attributes", {}).get("friendly_name") or s["entity_id"]


def device_key(eid):
    """xiaomi_home 的 entity_id 形如 light.YOUR_LAMP_s_2_light,
    前四段标识设备, 其余是该设备下的功能点。"""
    body = eid.split(".", 1)[1]
    p = body.split("_")
    return "_".join(p[:4]) if len(p) >= 4 else body


def device_name(s):
    return name_of(s).split("  ")[0].split(" * ")[0]


# ---------------- 命令 ----------------

def cmd_catalog(a):
    """给 LLM 看的设备目录 —— 语义匹配由它来做, 这里只负责把信息摆清楚。"""
    states = api("/states")
    devs = {}
    for s in states:
        devs.setdefault(device_key(s["entity_id"]), []).append(s)

    # 先算出真正要显示的内容, 再决定标题 —— 否则会出现只有标题没有条目的空段
    blocks, offline = [], []
    for k in sorted(devs, key=lambda x: device_name(devs[x][0])):
        ents = devs[k]
        ctl = [e for e in ents if e["entity_id"].split(".")[0] in PRIMARY]
        if not ctl and not a.all:
            continue
        shown = [e for e in sorted(ctl, key=lambda x: x["entity_id"])
                 if e["state"] != "unavailable" or a.all]
        if not shown:
            offline.append(device_name(ents[0]))
            continue
        blocks.append((device_name(ents[0]), len(ents), shown, ents))

    print(f"# 设备目录  ({len(blocks)} 台在线 / 共 {len(states)} 个实体)")
    print("# 从下面挑出需要的 entity_id, 再用 on/off/call 操作\n")

    for dev, total, shown, ents in blocks:
        print(f"## {dev}   ({total} 个实体)")
        for e in shown:
            label = name_of(e)
            short = label.split("  ", 1)[1] if "  " in label else label
            print(f"   {e['state']:<12} {short[:40]:<42} {e['entity_id']}")
        if a.sensors:
            for e in sorted(ents, key=lambda x: x["entity_id"]):
                if not e["entity_id"].startswith("sensor."):
                    continue
                if e["state"] in ("unknown", "unavailable"):
                    continue
                u = e.get("attributes", {}).get("unit_of_measurement", "")
                label = name_of(e)
                short = label.split("  ", 1)[1] if "  " in label else label
                print(f"   {e['state']:>12}{u:<4} {short[:40]:<42} {e['entity_id']}")
        print()

    if offline:
        print(f"# 离线设备 ({len(offline)}): " + "、".join(offline))
        print("#   加 --all 可以看到它们的实体")


def cmd_grep(a):
    """纯字面过滤, 不做任何猜测。目录太长时用它缩小范围。"""
    kw = a.keyword.lower()
    hit = [s for s in api("/states")
           if kw in s["entity_id"].lower() or kw in name_of(s).lower()]
    if a.domain:
        hit = [s for s in hit if s["entity_id"].startswith(a.domain + ".")]
    if not hit:
        print(f"没有包含 '{a.keyword}' 的实体。用 `catalog` 看完整目录。")
        return
    print(f"{len(hit)} 条:")
    for s in sorted(hit, key=lambda x: x["entity_id"])[: a.limit]:
        print(f"  {s['state']:<12} {name_of(s)[:46]:<48} {s['entity_id']}")
    if len(hit) > a.limit:
        print(f"  ... 另有 {len(hit)-a.limit} 条")


def cmd_state(a):
    s = api(f"/states/{a.entity}")
    if not s.get("entity_id"):
        die(f"没有这个实体: {a.entity}")
    print(f"{s['entity_id']}")
    print(f"  名称  : {name_of(s)}")
    print(f"  状态  : {s['state']}")
    print(f"  更新于: {s.get('last_updated','')}")
    at = {k: v for k, v in s.get("attributes", {}).items() if k != "friendly_name"}
    if at:
        print("  属性  :")
        for k, v in list(at.items())[: a.max_attrs]:
            print(f"    {k}: {str(v)[:90]}")


def _switch(entity, service):
    if "." not in entity:
        die(f"需要确切的 entity_id (形如 light.xxx), 收到 '{entity}'。先跑 catalog 或 grep。")
    domain = entity.split(".")[0]
    before = api(f"/states/{entity}").get("state")
    api(f"/services/{domain}/{service}", {"entity_id": entity})
    after = api(f"/states/{entity}").get("state")
    print(f"{entity}\n  {before}  ->  {after}")
    print("  注: HA 会乐观更新状态, 要确认设备真的动了请隔几秒再读。")


def cmd_on(a):
    _switch(a.entity, "turn_on")


def cmd_off(a):
    _switch(a.entity, "turn_off")


def cmd_toggle(a):
    _switch(a.entity, "toggle")


def cmd_call(a):
    if "." not in a.service:
        die("服务格式应为 domain.service, 例如 climate.set_temperature")
    domain, svc = a.service.split(".", 1)
    payload = {}
    if a.entity:
        payload["entity_id"] = a.entity
    for kv in a.data or []:
        if "=" not in kv:
            die(f"--data 需要 key=value, 收到 '{kv}'")
        k, v = kv.split("=", 1)
        try:
            payload[k] = json.loads(v)
        except json.JSONDecodeError:
            payload[k] = v
    res = api(f"/services/{domain}/{svc}", payload)
    print(f"已调用 {a.service}  {json.dumps(payload, ensure_ascii=False)}")
    if isinstance(res, list) and res:
        for s in res[:10]:
            print(f"  {s['entity_id']:<52} -> {s['state']}")


def cmd_check(a):
    url, _ = load_cfg()
    print(f"HA 地址: {url}")
    print(f"  连通性: {api('/').get('message','?')}")
    c = api("/config")
    print(f"  版本  : {c.get('version')}   状态: {c.get('state')}")
    print(f"  位置  : {c.get('location_name')}   时区: {c.get('time_zone')}")
    print(f"  实体数: {len(api('/states'))}")


def main():
    p = argparse.ArgumentParser(prog="ha", description="Home Assistant 控制 (Hermes skill)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("catalog", help="设备目录 —— 先跑这个, 从中选 entity_id")
    s.add_argument("--sensors", action="store_true", help="附带传感器读数")
    s.add_argument("--all", action="store_true", help="包含 unavailable 与无主体的设备")
    s.set_defaults(func=cmd_catalog)

    s = sub.add_parser("grep", help="按字面过滤实体 (不做语义猜测)")
    s.add_argument("keyword")
    s.add_argument("--domain")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(func=cmd_grep)

    s = sub.add_parser("state", help="查实体状态与属性 (需确切 entity_id)")
    s.add_argument("entity")
    s.add_argument("--max-attrs", type=int, default=25)
    s.set_defaults(func=cmd_state)

    for n, f, h in (("on", cmd_on, "打开"), ("off", cmd_off, "关闭"),
                    ("toggle", cmd_toggle, "切换")):
        s = sub.add_parser(n, help=f"{h} (需确切 entity_id)")
        s.add_argument("entity")
        s.set_defaults(func=f)

    s = sub.add_parser("call", help="调用任意服务")
    s.add_argument("service")
    s.add_argument("--entity")
    s.add_argument("--data", action="append", help="key=value, 可重复")
    s.set_defaults(func=cmd_call)

    s = sub.add_parser("check", help="连通性自检")
    s.set_defaults(func=cmd_check)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
