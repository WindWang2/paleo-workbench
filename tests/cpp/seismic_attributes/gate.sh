#!/usr/bin/env bash
# Linux equivalent of scripts/cpp-migration/Invoke-ResourceGate.ps1 (A-line
# owns the canonical script; this host has no PowerShell). Same protocol:
#   * exclusive hold of the shared lock file in the common git dir
#     (.bare/cpp-migration-heavy.lock) — busy => exit 75;
#   * at least 8 GiB available memory — low => exit 75;
#   * CMAKE_BUILD_PARALLEL_LEVEL=2 / CTEST_PARALLEL_LEVEL=2, BLAS/OpenMP
#     thread caps pinned to 1 (same env contract as the PS gate);
#   * build outputs must live under this worktree's build/ directory.
#
# Usage: gate.sh -- <command...>
# The gate wraps one heavy command; the child's exit code is passed through.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "RESOURCE_GATE_ERROR: run from a migration worktree" >&2; exit 1; }
COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)" || {
    echo "RESOURCE_GATE_ERROR: no common git dir" >&2; exit 1; }
COMMON_DIR="$(cd "$COMMON_DIR" && pwd)"
LOCK_PATH="$COMMON_DIR/cpp-migration-heavy.lock"

MIN_GIB="${PWB_GATE_MIN_GIB:-8}"
AVAILABLE_KIB=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
AVAILABLE_GIB=$((AVAILABLE_KIB / 1024 / 1024))

exec 9>"$LOCK_PATH"
if ! flock -n 9; then
    echo "RESOURCE_BUSY: another migration job holds the shared slot; exit=75."
    exit 75
fi
if [ "$AVAILABLE_GIB" -lt "$MIN_GIB" ]; then
    echo "RESOURCE_LOW_MEMORY: free=${AVAILABLE_GIB} GiB required=${MIN_GIB} GiB; exit=75."
    exit 75
fi
echo "RESOURCE_READY: shared slot acquired; available=${AVAILABLE_GIB} GiB; jobs=2."
printf 'pid=%s root=%s time=%s\n' "$$" "$REPO_ROOT" "$(date -u +%FT%TZ)" >&9

export CMAKE_BUILD_PARALLEL_LEVEL=2
export CTEST_PARALLEL_LEVEL=2
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

if [ "${1:-}" != "--" ]; then
    echo "RESOURCE_GATE_ERROR: expected -- <command>" >&2; exit 1
fi
shift
"$@"
exit_code=$?
flock -u 9
exit "$exit_code"
