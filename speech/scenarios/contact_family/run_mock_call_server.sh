#!/usr/bin/env bash

set -e

cd "$HOME/github-product/g1-dex3-care-vla/speech"

exec python3 \
  scenarios/contact_family/mock_call_server.py
