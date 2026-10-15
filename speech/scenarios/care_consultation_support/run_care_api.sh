#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/../.."

if [ -f "$HOME/.config/elder_companion/cloud.env" ]; then
    source "$HOME/.config/elder_companion/cloud.env"
fi

exec python3 \
  scenarios/care_consultation_support/care_api.py
