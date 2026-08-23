#!/usr/bin/env bash
set -a
source .env
set +a
source venv/bin/activate
python3 ../read_mailboxes.py
