#!/usr/bin/env bash

set -euo pipefail

readonly CONFIRM=--confirm-g1-companion-camera-dialogue-motion
if [[ $# -ne 1 || "$1" != "$CONFIRM" ]]; then
  printf 'usage: %s %s\n' "$0" "$CONFIRM" >&2
  exit 64
fi

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EMOTION_PY="$ROOT/data/visual/venv-emotion/bin/python"
SPEECH_PY="$ROOT/speech/venv/bin/python"
TV_PY="/home/user/miniconda3/envs/tv/bin/python"
PCM_BRIDGE="$ROOT/build/g1_companion_pcm_bridge"
EXECUTOR="$ROOT/scripts/g1_elder_companion_motion_executor.py"
LOG_ROOT="$ROOT/runs/elder-companion-emotion-dialogue"
CLOUD_ENV="$HOME/.config/elder_companion/cloud.env"

if [[ ! "${G1_ELDERLY_ID:-}" =~ ^[0-9]+$ ]] || ! python3 - "$G1_ELDERLY_ID" <<'PY'
import sys
value = int(sys.argv[1])
raise SystemExit(0 if 1 <= value <= (2**63 - 1) else 1)
PY
then
  printf 'G1_ELDERLY_ID must be a positive decimal ID no larger than 2^63-1\n' >&2
  exit 64
fi

[[ -x "$EMOTION_PY" && -x "$SPEECH_PY" && -x "$TV_PY" && -x "$PCM_BRIDGE" ]] || {
  printf 'run preflight first: companion dialogue motion dependency unavailable\n' >&2
  exit 66
}
[[ -r "$CLOUD_ENV" ]] || {
  printf 'companion dialogue configuration unavailable: %s\n' "$CLOUD_ENV" >&2
  exit 66
}
source "$CLOUD_ENV"
[[ -n "${DASHSCOPE_API_KEY:-}" && -n "${DASHSCOPE_WORKSPACE_ID:-}" ]] || {
  printf 'companion dialogue configuration requires DASHSCOPE_API_KEY and DASHSCOPE_WORKSPACE_ID\n' >&2
  exit 66
}

mkdir -p "$LOG_ROOT"
RUN_DIR=$(mktemp -d "$LOG_ROOT/camera-motion-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
PYTHONPATH="$ROOT" python3 -m care_console.link \
  --console-url "${CARE_CONSOLE_URL:-http://127.0.0.1:8766}" --elderly-id "$G1_ELDERLY_ID" \
  --emotion-log "${G1_EMOTION_DASHBOARD_LOG:-$RUN_DIR/emotion-dashboard.jsonl}" \
  --interaction-log "$RUN_DIR/care-session.jsonl" > "$RUN_DIR/workstation-link.json"
LOG="$RUN_DIR/stdout.jsonl"
WAKE_LOG="$RUN_DIR/wake_mode.stdout"
printf 'purpose=G1 first says 现在演示动作交互场景; operator then waves or claps; a voice yes starts official ArmAction 25/17, then opens Dex3 after the arms leave the torso; no companion chat during G1 motion\n'
printf 'prerequisite=run ./speech/run_server.sh in another terminal; G1 in regular sport mode, standing still\n'
printf 'mode=after this confirmation, enable G1 wake/microphone mode with the existing voice-mode owner before camera startup\n'
printf 'bound=camera index 0 for 120 seconds; ignore non-gesture events until happy+wave/clap; ask once then listen; no LLM and no water; ArmAction timeout 12s; wave and closed-hand clap open Dex3 only after arm clearance, never at hip rest\n'
printf 'privacy=mic WAVs are deleted immediately after ASR; stdout/control JSONL stays transcript-free; the independent care-session journal records recognized text for the bound elderly ID\n'
printf 'acceptance=announce 现在演示动作交互场景 first, then operator gesture, then voice yes, then confirmed motion request without a second scene sentence, then official action 25 or 17 RPC with Dex3 open only after arms leave the torso; skip HandCmd if clearance fails or hands stay closed, do not cancel ArmAction\n'
printf 'stop=Ctrl-C restores voice mode after official ArmAction 17/25 finishes on its own; q or Esc only ends the camera preview, not a prerequisite for waving or clapping; no LowCmd, VLA, or unofficial arm trajectory\n'
printf 'log=%s\n' "$LOG"
printf 'console=%s\n' "$RUN_DIR/console.log"
printf 'wake_log=%s\n' "$WAKE_LOG"

"$ROOT/scripts/g1_voice_wake_mode.sh" --confirm-g1-voice-wake-mode | tee "$WAKE_LOG"
RESTORE_MODE=$("$SPEECH_PY" - "$WAKE_LOG" <<'PY'
import json
import sys
from pathlib import Path

try:
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    sys.exit()
mode = result.get("mode_before")
if result.get("status") == "completed" and result.get("write_performed") is True and mode in (0, 1, 2):
    print(mode)
PY
)
restore_voice_mode() {
  if [[ -z "${RESTORE_MODE:-}" ]]; then
    return
  fi
  local mode=$RESTORE_MODE
  RESTORE_MODE=
  if ! "$ROOT/scripts/g1_voice_wake_mode.sh" --confirm-g1-voice-mode-restore "$mode" | tee -a "$WAKE_LOG"; then
    printf 'voice mode restore failed; see %s\n' "$WAKE_LOG" >&2
    exit 70
  fi
}
trap restore_voice_mode EXIT

CONSOLE="$RUN_DIR/console.log"
set -o pipefail
{
  "$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py" \
    --input 0 --display --max-seconds 120 \
    --dashboard-log "${G1_EMOTION_DASHBOARD_LOG:-$RUN_DIR/emotion-dashboard.jsonl}" |
    "$SPEECH_PY" -u "$ROOT/speech/emotion_dialogue.py" \
      --g1-pcm-bridge "$PCM_BRIDGE" --confirm-g1-companion-pcm \
      --audio-dir "$RUN_DIR/mic" --dialect mandarin \
      --elderly-id "$G1_ELDERLY_ID" --record-log "$RUN_DIR/care-session.jsonl" \
    --listen-seconds "${G1_DIALOGUE_MAX_SPEECH_SECONDS:-20}" \
    --silence-timeout "${G1_DIALOGUE_SILENCE_TIMEOUT:-1.2}" \
    --speech-rms-threshold "${G1_DIALOGUE_SPEECH_RMS_THRESHOLD:-450}" \
      --demo-scene motion |
    stdbuf -oL tee "$LOG" |
    "$TV_PY" "$EXECUTOR" \
      --from-stdin \
      --confirm-g1-companion-motion-executor \
      --interface enp3s0 \
      --jsonl-output "$LOG"
} 2> >(tee -a "$CONSOLE" >&2)
