#!/usr/bin/env bash
# Convenience wrapper around the Verilator lint targets, for running outside the
# lab Makefile (e.g. from the repository root, or in CI).
#
#   tools/svannot/lint/lint.sh                 # lint labs/ass1-2026
#   tools/svannot/lint/lint.sh path/to/dir     # lint a specific lab directory
#
# Runs, in order:
#   1. check_contract.py   - required internal signal names (no Verilator needed)
#   2. verilator --lint-only on the design
#   3. verilator --lint-only design + testbench, which is what proves the names
#
# Intended to run inside the course container, where `verilator` exists.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LAB_DIR="${1:-$REPO_ROOT/labs/ass1-2026}"
SVANNOT="$REPO_ROOT/tools/svannot"

VERILATOR="${VERILATOR:-verilator}"
DUTFILES=("$LAB_DIR/nerv-interrupt.sv")
[ -f "$LAB_DIR/singlecycle-interrupt.sv" ] && DUTFILES+=("$LAB_DIR/singlecycle-interrupt.sv")

# -Wno-DECLFILENAME: nerv-interrupt.sv defines module nerv, which Verilator
# would otherwise flag.  Everything else stays on.
LINTFLAGS=(--lint-only -Wall -Wno-DECLFILENAME)

rc=0

echo "== 1. signal-name contract =="
python3 "$SVANNOT/lint/check_contract.py" "${DUTFILES[@]}" || rc=1

if ! command -v "$VERILATOR" >/dev/null 2>&1; then
    echo
    echo "== 2/3. verilator =="
    echo "   '$VERILATOR' not found - run this inside the course container"
    echo "   (docker run ... phwl/elec3608-cad:latest)"
    exit "$rc"
fi

echo
echo "== 2. verilator lint (design only) =="
( cd "$LAB_DIR" && "$VERILATOR" "${LINTFLAGS[@]}" --top-module nerv \
    "${DUTFILES[@]##*/}" ) || rc=1

echo
echo "== 3. verilator lint (design + testbench -> proves the dut.<name> contract) =="
( cd "$LAB_DIR" && "$VERILATOR" "${LINTFLAGS[@]}" --top-module testbench \
    testbench.sv "${DUTFILES[@]##*/}" ) || rc=1

echo
if [ "$rc" -eq 0 ]; then
    echo "lint.sh: PASS"
else
    echo "lint.sh: FAIL (see above)"
fi
exit "$rc"
