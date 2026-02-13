#!/usr/bin/env bash
set -Eeuo pipefail
export CLAW_RUNTIME_HOME="/Users/lukaswaschul/Library/Application Support/Clawgotchi"
export CLAW_ENV_FILE="/Users/lukaswaschul/Library/Application Support/Clawgotchi/.env"
export CLAW_VENV_PATH="/Users/lukaswaschul/.pyenv/versions/3.12.4"
export PYTHONUNBUFFERED=1
exec "/Users/lukaswaschul/.pyenv/versions/3.12.4/bin/python3.12" "/Users/lukaswaschul/Desktop/Clawgotchi/main.py" "$@"
