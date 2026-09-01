#!/usr/bin/env bash
# 部署到本机（mail 服务器）。幂等，可重复跑。
# 脚本本体留在 repo 里跑，不复制到 /usr/local/bin —— 避免 repo 和线上两份漂移。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo $0"; exit 1; }
chmod +x "$REPO/scripts/"*.sh
mkdir -p /var/lib/presence

# HA token 绝不进 git，单独放
if [ ! -s /etc/presence-ha-token ]; then
  echo "缺 /etc/presence-ha-token —— 放入 HA 长期访问令牌后重跑" >&2
  exit 1
fi
chmod 600 /etc/presence-ha-token

# 清掉合并前的旧 cron（两个看门狗并存会打架）
rm -f /etc/cron.d/wifi-watchdog
crontab -u "${SUDO_USER:-YOUR_HOST}" -l 2>/dev/null | grep -v 'network-watchdog.sh' \
  | crontab -u "${SUDO_USER:-YOUR_HOST}" - 2>/dev/null || true

cat > /etc/cron.d/home-infra <<EOF
# 由 home-assistant-skill/presence/install.sh 生成，勿手改
*/2 * * * * root $REPO/scripts/presence-scan.sh
*/5 * * * * root $REPO/scripts/network-watchdog.sh
EOF
chmod 644 /etc/cron.d/home-infra

echo "✓ 已部署"
echo "  presence-scan   每 2 分钟  $REPO/scripts/presence-scan.sh"
echo "  network-watchdog 每 5 分钟 $REPO/scripts/network-watchdog.sh"
echo "  白名单           $REPO/presence/allowlist.txt"
echo "  状态/历史        /var/lib/presence/"
