#!/usr/bin/env bash

set -euo pipefail

readonly CONFIRM=--confirm-g1-companion-camera-tts
if [[ $# -ne 1 || "$1" != "$CONFIRM" ]]; then
  printf 'usage: %s %s\n' "$0" "$CONFIRM" >&2
  exit 64
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EMOTION_PY="$ROOT/data/visual/venv-emotion/bin/python"
SPEECH_PY="$ROOT/speech/venv/bin/python"
PCM_BRIDGE="$ROOT/build/g1_companion_pcm_bridge"
LOG_ROOT="$ROOT/runs/elder-companion-emotion-tts"

[[ -x "$EMOTION_PY" && -x "$SPEECH_PY" && -x "$PCM_BRIDGE" ]] || {
  printf 'run preflight first: companion emotion dependency unavailable\n' >&2
  exit 66
}

mkdir -p "$LOG_ROOT"
RUN_DIR=$(mktemp -d "$LOG_ROOT/camera-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
LOG="$RUN_DIR/stdout.jsonl"
printf 'purpose=UVC camera emotion to Mandarin TTS on the bounded G1 speaker\n'
printf 'prerequisite=run ./speech/run_server.sh in another terminal before this command\n'
printf 'bound=camera index 0 for 60 seconds; at most three reviewed phrases; each WAV is at most 15 seconds\n'
printf 'acceptance=completed play_result=0 stop_result=0 and audible G1 speech\n'
printf 'stop=press q or Esc in the preview, or Ctrl-C; each G1 PCM subprocess has a 15-second bound\n'
printf 'log=%s\n' "$LOG"

set -o pipefail
"$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py" \
  --input 0 --display --max-seconds 60 |
  "$SPEECH_PY" "$ROOT/speech/emotion_interaction.py" \
    --g1-pcm-bridge "$PCM_BRIDGE" --confirm-g1-companion-pcm --dialect mandarin |
  tee "$LOG"
