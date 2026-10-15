#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 0 ]]; then
  printf 'usage: %s\n' "$0" >&2
  exit 64
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EMOTION_PY="$ROOT/data/visual/venv-emotion/bin/python"
SPEECH_PY="$ROOT/speech/venv/bin/python"
PCM_BRIDGE="$ROOT/build/g1_companion_pcm_bridge"
VIDEO="$ROOT/vedio/happy_1.mp4"

[[ -x "$EMOTION_PY" && -x "$SPEECH_PY" && -r "$VIDEO" ]] || {
  printf 'preflight dependency unavailable\n' >&2
  exit 66
}

cmake --build "$ROOT/build" --target g1_companion_pcm_bridge \
  g1_companion_pcm_test -j2
ctest --test-dir "$ROOT/build" -R 'g1_companion_pcm_' \
  --output-on-failure

PCM_WAV=$(find "$ROOT/speech/output" -maxdepth 1 -type f -name '*.wav' -print -quit)
[[ -n "$PCM_WAV" ]] || {
  printf 'preflight requires one existing speech/output WAV\n' >&2
  exit 66
}
"$PCM_BRIDGE" --dry-run "$PCM_WAV"

set -o pipefail
"$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py" \
  --input "$VIDEO" --max-seconds 60 |
  "$SPEECH_PY" "$ROOT/speech/emotion_interaction.py" --g1-phrase-jsonl
