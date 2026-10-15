#!/usr/bin/env bash

set -e

cd "/home/user/github-product/g1-dex3-care-vla/speech"

source "/home/user/github-product/g1-dex3-care-vla/speech/venv/bin/activate"

source "$HOME/.config/elder_companion/cloud.env"

export SPEECH_SERVER_PORT=8780

exec python server.py
