#!/usr/bin/env sh
# Scorekeep setup: installs the dev/test runner and the optional `scorekeep`
# shortcut, verifies the tool imports, then EXITS. It never starts the scorer.
#
# Usage: sh install.sh
set -eu

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found. Install Python 3.9 or newer (see INSTALL.md)." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "error: Scorekeep needs Python 3.9 or newer; found $("$PYTHON" -V 2>&1)" >&2
    exit 1
fi

# Refresh packaging tooling so editable installs work. Offline is fine: no
# runtime package is needed, so a failure here is only a note.
"$PYTHON" -m pip install --upgrade pip setuptools wheel --quiet 2>/dev/null ||
    echo "note: could not refresh pip/setuptools/wheel (offline?) - continuing" >&2

# The test runner is the only declared dependency (requirements.txt).
"$PYTHON" -m pip install -r requirements.txt --quiet 2>/dev/null ||
    echo "note: pytest was not (re)installed - checking the existing interpreter" >&2

if ! "$PYTHON" -c 'import pytest' 2>/dev/null; then
    echo "error: pytest is required to run the test suite (python3 -m pip install -r requirements.txt)" >&2
    exit 1
fi

# Optional: put the `scorekeep` console script on PATH. The tool itself never
# needs installing - `python3 scorekeep.py` is the documented start command.
"$PYTHON" -m pip install -e . --no-build-isolation --quiet 2>/dev/null ||
    echo "note: skipped the optional 'scorekeep' console shortcut; use 'python3 scorekeep.py'" >&2

"$PYTHON" -c 'import scorekeep' ||
    { echo "error: scorekeep.py failed to import - the install is incomplete" >&2; exit 1; }

echo "Scorekeep is ready."
echo "  Score a leg : $PYTHON scorekeep.py --game 501 --players Alice,Bob"
echo "  Demo        : sh demo.sh"
echo "  Tests       : $PYTHON -m pytest"
