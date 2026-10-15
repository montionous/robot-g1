#!/usr/bin/env bash

set -euo pipefail

readonly CONFIRM=--confirm-g1-companion-known-video-tts
if [[ $# -ne 1 || "$1" != "$CONFIRM" ]]; then
  printf 'usage: %s %s\n' "$0" "$CONFIRM" >&2
  exit 64
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EMOTION_PY="$ROOT/data/visual/venv-emotion/bin/python"
SPEECH_PY="$ROOT/speech/venv/bin/python"
PCM_BRIDGE="$ROOT/build/g1_companion_pcm_bridge"
VIDEO="$ROOT/vedio/happy_1.mp4"
LOG_ROOT="$ROOT/runs/elder-companion-emotion-tts"

[[ -x "$EMOTION_PY" && -x "$SPEECH_PY" && -x "$PCM_BRIDGE" && -r "$VIDEO" ]] || {
  printf 'run preflight first: companion emotion dependency unavailable\n' >&2
  exit 66
}

mkdir -p "$LOG_ROOT"
RUN_DIR=$(mktemp -d "$LOG_ROOT/video-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
LOG="$RUN_DIR/stdout.jsonl"
printf 'purpose=known-video emotion to Mandarin TTS on the bounded G1 speaker\n'
printf 'prerequisite=run ./speech/run_server.sh in another terminal before this command\n'
printf 'bound=one 60-second video; at most three reviewed phrases; each WAV is at most 15 seconds\n'
printf 'acceptance=completed play_result=0 stop_result=0 and audible G1 speech\n'
printf 'stop=Ctrl-C; each G1 PCM subprocess has a 15-second bound\n'
printf 'log=%s\n' "$LOG"

set -o pipefail
"$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py" \
  --input "$VIDEO" --max-seconds 60 |
  "$SPEECH_PY" "$ROOT/speech/emotion_interaction.py" \
    --g1-pcm-bridge "$PCM_BRIDGE" --confirm-g1-companion-pcm --dialect mandarin |
  tee "$LOG"
