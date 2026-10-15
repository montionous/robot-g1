#!/usr/bin/env bash

set -euo pipefail

readonly DIALOGUE_CONFIRM=--confirm-g1-companion-camera-dialogue
readonly LISTEN_INVITE_CONFIRM=--confirm-g1-companion-camera-listen-invite
if [[ $# -ne 1 ]]; then
  printf 'usage: %s {%s|%s}\n' "$0" "$DIALOGUE_CONFIRM" "$LISTEN_INVITE_CONFIRM" >&2
  exit 64
fi
case "$1" in
  "$DIALOGUE_CONFIRM"|"$LISTEN_INVITE_CONFIRM") ;;
  *)
    printf 'usage: %s {%s|%s}\n' "$0" "$DIALOGUE_CONFIRM" "$LISTEN_INVITE_CONFIRM" >&2
    exit 64
    ;;
esac

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EMOTION_PY="$ROOT/data/visual/venv-emotion/bin/python"
SPEECH_PY="$ROOT/speech/venv/bin/python"
TV_PY="/home/user/miniconda3/envs/tv/bin/python"
PCM_BRIDGE="$ROOT/build/g1_companion_pcm_bridge"
EXECUTOR="$ROOT/scripts/g1_elder_companion_custom_action_executor.py"
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
  printf 'run preflight first: companion dialogue dependency unavailable\n' >&2
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
ELDER_CHAT_URL=http://127.0.0.1:8811
PYTHONPATH="$ROOT/speech" "$SPEECH_PY" -c 'import sys; from emotion_dialogue import _require_elder_chat_health; _require_elder_chat_health(sys.argv[1])' "$ELDER_CHAT_URL" || {
  printf 'companion dialogue API unavailable: %s\n' "$ELDER_CHAT_URL" >&2
  exit 69
}

mkdir -p "$LOG_ROOT"
RUN_DIR=$(mktemp -d "$LOG_ROOT/camera-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
PYTHONPATH="$ROOT" python3 -m care_console.link \
  --console-url "${CARE_CONSOLE_URL:-http://127.0.0.1:8766}" --elderly-id "$G1_ELDERLY_ID" \
  --emotion-log "${G1_EMOTION_DASHBOARD_LOG:-$RUN_DIR/emotion-dashboard.jsonl}" \
  --interaction-log "$RUN_DIR/care-session.jsonl" > "$RUN_DIR/workstation-link.json"
LOG="$RUN_DIR/stdout.jsonl"
EXECUTOR_LOG="$RUN_DIR/custom_action.jsonl"
WAKE_LOG="$RUN_DIR/wake_mode.stdout"
printf 'purpose=one camera emotion event to a bounded Mandarin G1 companion dialogue; G1 first says 现在演示多轮对话场景 then a detection opening; sad listen_hold requests the recorded open_palm_invite once before that detection opening so the official custom ArmAction overlaps 看到您/检测到 speech; after arms leave the torso by 0.135 rad hands stay closed, then at the 0.25-rad invite pose only the right Dex3 fingers 3..6 open over 0.8s while preserving all thumb targets; the left hand receives no HandCmd and stays unchanged; the right hand closes only on the arm return or action finish; this confirmation covers --confirm-g1-companion-listen-invite-executor; Elder Companion Unified API owns later replies until the elder ends the chat; this script does not ask for or run official wave/clap ArmAction 17/25, write LowCmd, start VLA, or replay XR 24D\n'
printf 'prerequisite=speech service on 8780 and isolated companion API on %s before this command\n' "$ELDER_CHAT_URL"
printf 'mode=after this confirmation, enable G1 wake/microphone mode with the existing voice-mode owner before camera startup; regular sport standing and small idle posture stay allowed\n'
printf 'bound=camera index 0 waits at most 60 seconds for its first event; after it the preview stays visible and listening waits for speech, submits after 1.2 seconds of silence, and caps each utterance at 20 seconds until the elder ends the chat; WAV input remains capped by the PCM bridge and playback wait follows its actual duration; one recorded open_palm_invite request on sad listen_hold overlapping the detection opening; hands remain closed through 0.135-rad clearance and only the right fingers 3..6 open at the 0.25-rad invite pose, thumbs unchanged; the left hand receives no HandCmd; no official wave/clap ArmAction 17/25\n'
printf 'privacy=mic WAVs are deleted immediately after ASR; stdout/control JSONL stays transcript-free; the independent care-session journal records console transcript and generated text for the bound elderly ID\n'
printf 'entertainment=only story/joke playback listens for explicit stop or replace commands; ordinary replies remain blocking; replacement waits for the old stream stop RPC success and process exit; narration echo is filtered by text but field ASR/echo separation still requires observation\n'
printf 'acceptance=completed dialogue summary, g1_played=true receipts, and operator hears each G1 reply; happy/sad/angry still emit intent_only rows; sad listen_hold emits one emotion_dialogue_custom_action_request before the detection opening; happy silent and angry do not; executor whitelist is open_palm_invite only; this script does not emit emotion_dialogue_motion_request or ask for official wave/clap\n'
printf 'stop=press q or Esc only to close the preview, or Ctrl-C; Ctrl-C restores voice mode; right-finger-only Dex3 HandCmd is skipped unless the recorded arm reaches the 0.25-rad invite pose; the left hand receives no HandCmd; no LowCmd, homemade arm trajectory, VLA, or XR 24D replay\n'
printf 'log=%s\n' "$LOG"
printf 'custom_action_log=%s\n' "$EXECUTOR_LOG"
printf 'console=%s\n' "$RUN_DIR/console.log"
printf 'wake_log=%s\n' "$WAKE_LOG"
printf 'elder_chat_url=%s\n' "$ELDER_CHAT_URL"

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
EMOTION_PID=
EVENT_PIPE=
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
request_emotion_demo_stop() {
  if [[ -n "${EMOTION_PID:-}" ]] && kill -0 "$EMOTION_PID" 2>/dev/null; then
    kill "$EMOTION_PID" 2>/dev/null || true
  fi
}
stop_emotion_demo() {
  request_emotion_demo_stop
  if [[ -n "${EMOTION_PID:-}" ]]; then
    wait "$EMOTION_PID" 2>/dev/null || true
    EMOTION_PID=
  fi
}
cleanup() {
  stop_emotion_demo
  if [[ -n "${EVENT_PIPE:-}" ]]; then
    rm -f -- "$EVENT_PIPE"
  fi
  restore_voice_mode
}
trap cleanup EXIT

CONSOLE="$RUN_DIR/console.log"
start_emotion_demo() {
  EVENT_PIPE="$RUN_DIR/emotion-events.fifo"
  mkfifo "$EVENT_PIPE"
  "$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py" \
    --input 0 --display --max-seconds 60 --continue-after-first-event \
    --dashboard-log "${G1_EMOTION_DASHBOARD_LOG:-$RUN_DIR/emotion-dashboard.jsonl}" \
    > "$EVENT_PIPE" 2> >(tee -a "$CONSOLE" >&2) &
  EMOTION_PID=$!
}
forward_dialogue_output() {
  while IFS= read -r line; do
    printf '%s\n' "$line"
    case "$line" in
      *'"status":"quiet_requested"'*|*'"status":"session_ended"'*)
        request_emotion_demo_stop
        ;;
    esac
  done
}

start_emotion_demo
set -o pipefail
{
  "$SPEECH_PY" -u "$ROOT/speech/emotion_dialogue.py" \
    --g1-pcm-bridge "$PCM_BRIDGE" --confirm-g1-companion-pcm \
    --audio-dir "$RUN_DIR/mic" --dialect mandarin \
    --elderly-id "$G1_ELDERLY_ID" --record-log "$RUN_DIR/care-session.jsonl" \
    --listen-seconds "${G1_DIALOGUE_MAX_SPEECH_SECONDS:-20}" \
    --silence-timeout "${G1_DIALOGUE_SILENCE_TIMEOUT:-1.2}" \
    --speech-rms-threshold "${G1_DIALOGUE_SPEECH_RMS_THRESHOLD:-450}" \
    --demo-scene dialogue \
    --elder-chat-url "$ELDER_CHAT_URL" \
    --enable-listen-invite \
    --enable-entertainment-interrupts \
    --accept-visual-transitions \
    < "$EVENT_PIPE" |
  stdbuf -oL tee "$LOG" |
  forward_dialogue_output |
  "$TV_PY" "$EXECUTOR" \
    --from-stdin \
    --confirm-g1-companion-listen-invite-executor \
    --interface enp3s0 |
  tee "$EXECUTOR_LOG"
} 2> >(tee -a "$CONSOLE" >&2)
