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
source "$SPEECH_ROOT/companion_recording_env.sh" social_activity_support

if [ -f "$HOME/.config/elder_companion/cloud.env" ]; then
    source "$HOME/.config/elder_companion/cloud.env"
fi

python3 \
    "$SCRIPT_DIR/g1_voice_demo.py" \
    "$@" \
    --elderly-id "$G1_ELDERLY_ID" --record-log "$CARE_SESSION_LOG" --record-mode live
