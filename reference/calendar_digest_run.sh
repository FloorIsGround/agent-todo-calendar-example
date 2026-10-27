#!/usr/bin/env bash
# Deterministic run for the discord-7day-calendar-digest cron job.
# 1) Sync course items into the todo service (idempotent).
# 2) Generate + deliver the 7-day calendar digest to Discord.
set -euo pipefail
cd "$HOME/.hermes/scripts" || exit 1
"${HERMES_VENV_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}" course_todo_sync.py
"${HERMES_VENV_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}" google_calendar_7day_digest.py