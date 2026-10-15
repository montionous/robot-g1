#!/usr/bin/env bash

set -e

SPEECH_ROOT="$HOME/github-product/g1-dex3-care-vla/speech"

cd "$SPEECH_ROOT"
source "$SPEECH_ROOT/companion_recording_env.sh" contact_family

if [ -f "$HOME/.config/elder_companion/cloud.env" ]; then
    source "$HOME/.config/elder_companion/cloud.env"
fi

echo "检查 Speech Server..."

if ! curl -fsS \
    http://127.0.0.1:8780/health \
    >/dev/null
then
    echo
    echo "错误：Speech Server 没有运行"
    echo
    echo "请先启动 speech/server.py"
    exit 1
fi

echo "Speech Server OK"
echo

exec python3 \
    scenarios/contact_family/g1_voice_demo.py \
    "$@" \
    --elderly-id "$G1_ELDERLY_ID" --record-log "$CARE_SESSION_LOG" --record-mode live
