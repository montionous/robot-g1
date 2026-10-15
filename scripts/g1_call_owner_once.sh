#!/usr/bin/env bash
# Run the existing owner-only G1 phone flow with the local paired-phone defaults.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHONE_URL="${G1_PHONE_URL:-http://10.42.0.117:8765}"
TOKEN_FILE="${G1_PHONE_TOKEN_FILE:-/home/user/.config/g1-phone-dial/token}"
RUNS_DIR="${G1_PHONE_RUNS_DIR:-$ROOT/runs/g1-contact-family-call}"
OUTPUT_DIR="$RUNS_DIR/once-$(date -u +%Y%m%dT%H%M%SZ)-$BASHPID"
PYTHON="$ROOT/speech/venv/bin/python"
RUNNER="$ROOT/scripts/g1_contact_family_call.py"

usage() {
  printf '%s\n' "Usage: $0 [--dry-run|--preflight]" >&2
}

case "$#:${1-}" in
  0:)
    action="--confirm-g1-contact-family-call"
    ;;
  1:--dry-run)
    action="--dry-run"
    ;;
  1:--preflight)
    action="--preflight"
    ;;
  *)
    usage
    exit 64
    ;;
esac

mkdir -p "$RUNS_DIR"
arguments=("$RUNNER" --phone-url "$PHONE_URL" --output-dir "$OUTPUT_DIR")
if [[ "$action" == "--confirm-g1-contact-family-call" ]]; then
  arguments+=(--token-file "$TOKEN_FILE")
fi
arguments+=("$action")
exec "$PYTHON" "${arguments[@]}"
