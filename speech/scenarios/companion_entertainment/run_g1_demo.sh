#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"

SPEECH_ROOT="$(
    cd "$SCRIPT_DIR/../.."
    pwd
)"

cd "$SPEECH_ROOT"
source "$SPEECH_ROOT/companion_recording_env.sh" companion_entertainment

if [ -f "$HOME/.config/elder_companion/cloud.env" ]; then
    source "$HOME/.config/elder_companion/cloud.env"
fi

# 娱乐陪伴默认使用已经为陕西口语编写、并可赛前预生成的回复。
# 如需普通话，设置 G1_ENTERTAINMENT_DIALECT=mandarin，或在命令末尾
# 传入 --dialect mandarin 覆盖即可。
ENTERTAINMENT_DIALECT="${G1_ENTERTAINMENT_DIALECT:-shaanxi}"

exec python3 \
    "$SCRIPT_DIR/g1_voice_demo.py" \
    --dialect "$ENTERTAINMENT_DIALECT" \
    --request-seconds 5 \
    --control-seconds 3 \
    "$@" \
    --elderly-id "$G1_ELDERLY_ID" --record-log "$CARE_SESSION_LOG" --record-mode live
