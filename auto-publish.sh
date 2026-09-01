#!/usr/bin/env bash
# publish-public.sh 的 cron 包装：记日志、失败时留醒目标记。
#
# 为什么要包装：cron 里直接跑发布脚本，失败了没人知道。而最需要被看见的失败恰恰是
# 「敏感信息扫描没过」——那说明有东西差点被推上公网，闸门拦住了，但公开版从此停止更新。
# 这种「安全网生效但静默」的状态如果没人发现，会一直烂下去。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HERE/publish.log"
FAIL_FLAG="$HERE/PUBLISH_FAILED"

{
  echo "===== $(date '+%F %T %Z') ====="
  if "$HERE/publish-public.sh" 2>&1; then
    rm -f "$FAIL_FLAG"
    echo "结果: 成功"
  else
    rc=$?
    echo "结果: 失败（退出码 $rc）"
    {
      echo "最近一次自动发布失败: $(date '+%F %T %Z')，退出码 $rc"
      echo "多半是敏感信息扫描没过——去看 publish.log。在修好之前公开版不会再更新。"
    } > "$FAIL_FLAG"
  fi
} >> "$LOG" 2>&1

# 日志只留最近 500 行，别无限长
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
