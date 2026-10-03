#!/usr/bin/env sh
# Scorekeep - non-interactive, recordable end-to-end demonstration.
# No prompts, no network, no input files needed. Usage: sh demo.sh
set -eu

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
SK="$PYTHON scorekeep.py"

section() {
    printf '\n============================================================\n'
    printf '%s\n' "$1"
    printf '============================================================\n'
}

section "1. The command reference and the accepted dart grammar"
$SK --help

section "2. The full 2-170 checkout table, in the scorer's own token notation"
$SK --table

section "3. Route lookups: 170, 167, 164, a no-checkout score, and above 170"
$SK --checkout 170 --checkout 167 --checkout 164 --checkout 169 --checkout 171

section "4. A scripted session: 501 with a bust, a 170 finish, leg 2 and averages,"
printf '   then a full cricket leg with dead numbers and the winning bull.\n'
$SK --demo

section "5. A scripted 301 leg from a file (examples/301-leg.darts)"
$SK --game 301 --players Alice,Bob --file examples/301-leg.darts

printf '\nDemo complete: 301, 501 and cricket scored, checkouts looked up, averages shown.\n'
