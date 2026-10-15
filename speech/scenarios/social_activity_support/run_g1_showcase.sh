#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

CLOUD_ENV="$HOME/.config/elder_companion/cloud.env"

if [ -f "$CLOUD_ENV" ]; then
    set -a
    source "$CLOUD_ENV"
    set +a
else
    echo "警告: 未找到云端环境配置 $CLOUD_ENV"
fi

PYTHON="./venv/bin/python"

echo "============================================================"
echo "SOCIAL_ACTIVITY_SUPPORT G1"
echo "============================================================"

echo
echo "[1/2] 刷新今天和明天的活动场次"

"$PYTHON" \
  scenarios/social_activity_support/refresh_activity_schedule.py

echo
echo "[2/2] 启动 G1 社区活动场景"
echo

exec "$PYTHON" \
  scenarios/social_activity_support/g1_showcase_demo.py \
  --listen-seconds 5.0 \
  --state-timeout 0 \
  --announce-decisions
