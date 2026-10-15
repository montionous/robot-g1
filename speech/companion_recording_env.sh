#!/usr/bin/env bash
# One explicit identity and a fresh journal for each standalone scene run.
if [[ ! "${G1_ELDERLY_ID:-}" =~ ^[0-9]+$ ]] || ! python3 - "$G1_ELDERLY_ID" <<'PY'
import sys
value = int(sys.argv[1])
raise SystemExit(0 if 1 <= value <= (2**63 - 1) else 1)
PY
then
    printf 'G1_ELDERLY_ID must identify the actual elder (1..2^63-1)\n' >&2
    exit 64
fi
CARE_INTERACTION_RECORD_ROOT="$SPEECH_ROOT/../runs/elder-companion-interaction"
mkdir -p "$CARE_INTERACTION_RECORD_ROOT"
CARE_INTERACTION_RECORD_DIR=$(mktemp -d "$CARE_INTERACTION_RECORD_ROOT/$1-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
CARE_SESSION_LOG="$CARE_INTERACTION_RECORD_DIR/care-session.jsonl"
PYTHONPATH="$SPEECH_ROOT/.." python3 -m care_console.link \
    --console-url "${CARE_CONSOLE_URL:-http://127.0.0.1:8766}" \
    --elderly-id "$G1_ELDERLY_ID" --interaction-log "$CARE_SESSION_LOG" \
    > "$CARE_INTERACTION_RECORD_DIR/workstation-link.json"
printf 'care_session_log=%s\n' "$CARE_SESSION_LOG"
