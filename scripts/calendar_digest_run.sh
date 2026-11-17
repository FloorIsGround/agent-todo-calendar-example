#!/usr/bin/env bash
# One run, using the repository's prepared environment even from cron's cwd.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"
exec "${TODO_PYTHON:-$ROOT/.venv/bin/python}" -m todo_example.job "$@"
