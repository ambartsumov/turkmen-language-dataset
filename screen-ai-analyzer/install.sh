#!/usr/bin/env bash
# Sets up the virtual environment and the optional system packages.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "Python 3.11+ is required (Ubuntu 24.04 ships 3.12)." >&2
    exit 1
fi

echo "==> Creating virtual environment in .venv"
"$PYTHON" -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Optional system packages"
MISSING=()
command -v tesseract    >/dev/null 2>&1 || MISSING+=(tesseract-ocr)
command -v gnome-screenshot >/dev/null 2>&1 || MISSING+=(gnome-screenshot)
command -v notify-send >/dev/null 2>&1 || MISSING+=(libnotify-bin)
dpkg -s xdg-desktop-portal >/dev/null 2>&1 || MISSING+=(xdg-desktop-portal xdg-desktop-portal-gnome)

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "The following packages improve capture/OCR support:"
    printf '    %s\n' "${MISSING[@]}"
    read -r -p "Install them with apt now? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y "${MISSING[@]}"
    else
        echo "Skipped. You can install them later with:"
        echo "    sudo apt-get install ${MISSING[*]}"
    fi
fi

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "==> Created .env - put your API key(s) in it:  nano .env"
fi

echo
echo "Done. Start the app with:  ./run.sh"
echo "Check the environment with: ./run.sh --check"
