---
name: xiaomi-smarthome-probe
description: 小米智能家居本地化方案的探测结论 —— 网关固件超出支持范围、小爱对话记录可读、以及三个踩过的坑
metadata: 
  node_type: memory
  type: project
  originSessionId: f45fcce1-11c7-437e-a249-469cec1202d8
  modified: 2026-08-23T12:48:50.863Z
---

> **脱敏副本。完整版在 mail 上，那里是唯一信任源：**
> `ssh mail` → `~/agent-notes/smarthome/`
>
> `<...·见 mail>` 是被移除的个人标识信息。


2026-08-23 完成方案第 1/2 步验证。小米账号 <手机号·见 mail>（userId <userId·见 mail>），**该账号只能走短信验证码登录（细节见 mail）。

**第 1 步 · 网关固件：`lumi.gateway.mgl03` 固件 `1.5.7_0001`（did <did·见 mail>，192.168.X.Y）**
XiaomiGateway3 官方 README 只支持到 1.5.6（1.5.0–1.5.4 只要 token；1.5.5–1.5.6 要 token+key；1.4.6–1.4.7 明确 UNSUPPORTED）。**1.5.7 未列出，本地化能否成功是未知数**，可能需要降级固件（zvldz/mgl03_fw）。这是整个方案的地基风险。

**第 2 步 · 小爱对话记录：GO**，零硬件成本，不需要转 ESP32。
- 必须用 REST：`https://userprofile.mina.mi.com/device_profile/v2/conversation?hardware=LX05&timestamp=<ms>&limit=N`
- cookie 三件套：`userId` + `serviceToken`(micoapi 的) + **`deviceId`＝音箱的 deviceID**（LX05 是 `6ff89b41-6dbc-4849-8a6c-202617248e7e`）
- ubus `nlp_result_get` 在 LX05 上是死路，ROM 返回 `code:1001, result:[]`

**三个坑（都很难自行定位，重蹈会很贵）：**
1. **对话接口传错 deviceId 不报错** —— 传账号 deviceId 而非音箱 deviceID 时，返回 HTTP200 + code=0 + `records:[]`，长得和"没有对话记录"一模一样。完全不传反而会 400 明确报错。
2. **miservice 的 MiAccount.login 有两处需要打补丁**：(a) 复用会话时响应不含 `passToken`，原实现写死 `resp["passToken"]` 会 KeyError；(b) except 分支无条件 `save_token()`，无参调用等于**删除凭据文件** —— 本账号没密码，删了就得重新收短信。
3. **每个 sid 登录前必须清空 cookie jar** —— `xiaomiio` 登录会留下 `passInfo`/`cUserId`/`pass_ua`，带着这些请求 `micoapi` 时小米返回精简响应，缺 `nonce`/`ssecurity`，换不出 serviceToken。只用单一服务不会遇到，MiIO+MiNA 同时用（正是本方案所需）必踩。

另：`~/.mi_device_id` 持久化 + `trust=true` 是**反效果** —— 一旦 deviceId 被信任，小米改走密码校验，而本账号无密码，必然 70016。这个账号只有陌生 deviceId 才能进短信通道。

相关：[[xiaomi-lan-topology]]
