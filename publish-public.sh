#!/usr/bin/env bash
# 把私有仓库的改动发布到公开仓库 YOUR_HOST/ha-kit。
#
#   ./publish-public.sh "提交说明"
#   ./publish-public.sh              # 不给说明就用私有仓库最近一条 commit 的标题
#   ./publish-public.sh --dry-run    # 只构建和扫描，不推送
#
# 【必须在 Oracle 上跑】——家里那台 mail 服务器到 GitHub 的网络不稳（curl 52 / RPC 失败），
# 推送经常断在半路。Oracle 连 GitHub 一直稳定。
#
# 流程：从家里的私有仓库拉最新 → 构建公开版（含敏感信息扫描闸门）
#      → 同步进公开仓库工作副本 → commit → push
# 扫描不过就直接失败、不推任何东西。这是防手滑的最后一道关，别绕过。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUB_REPO="YOUR_HOST/ha-kit"
WORK="$HERE/build/ha-kit"
DRY=0
[ "${1:-}" = "--dry-run" ] && { DRY=1; shift; }

echo "── 1. 从家里的私有仓库拉最新 ──"
GIT_SSH_COMMAND="ssh -p 2222 -o BatchMode=yes -o LogLevel=ERROR" \
  git -C "$HERE" fetch -q mail presence-detection
git -C "$HERE" checkout -q -B presence-detection FETCH_HEAD
git -C "$HERE" log --oneline -1 | sed 's/^/    /'

MSG="${1:-$(git -C "$HERE" log -1 --pretty=%s)}"

echo "── 2. 构建公开版（含敏感信息扫描）──"
"$HERE/build-public.sh" >/dev/null || { echo "构建失败，已中止，未推送任何内容。"; exit 1; }
echo "    ✓ 扫描通过（MAC / 内网IP / 主机名 / 设备实体ID 四项）"

[ "$DRY" = "1" ] && { echo "── dry-run，到此为止。产物在 $HERE/build/public ──"; exit 0; }

echo "── 3. 同步到公开仓库工作副本 ──"
if [ -d "$WORK/.git" ]; then
  git -C "$WORK" fetch -q origin main && git -C "$WORK" reset -q --hard origin/main
else
  rm -rf "$WORK"; git clone -q "https://github.com/$PUB_REPO.git" "$WORK"
fi
rsync -a --delete --exclude='.git' "$HERE/build/public/" "$WORK/"

echo "── 4. 提交并推送 ──"
cd "$WORK"
if [ -z "$(git status --porcelain)" ]; then
  echo "    没有变化，不需要发布。"; exit 0
fi
git status --short | sed 's/^/    /'
git add -A
git -c user.name="Long Sizhuo" -c user.email="YOUR_HOST@gmail.com" commit -q -m "$MSG"
git push -q origin main
echo "✓ 已发布: https://github.com/$PUB_REPO"
git log --oneline -1 | sed 's/^/    /'
