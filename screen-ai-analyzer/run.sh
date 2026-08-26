#!/usr/bin/env bash
# Starts the app (or forwards --trigger to a running instance).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -d .venv ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

exec python -m app.main "$@"
