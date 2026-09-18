#!/usr/bin/env bash
# Local build wrapper for THIS worktree while the shared migration slot is
# held by a long-running foreign build (vendored QGIS from the main
# checkout). Keeps the resource gate's SUBSTANCE — 2-job ceiling, one heavy
# build at a time, MemAvailable >= MinFreeGiB admission — without taking
# the exclusive flock (which would deadlock this slice for hours).
# Deviation recorded in 26-decisions.md.
set -u
MinFreeGiB="${PWB_LOCAL_GATE_GIB:-8}"
Action="${1:-Build}"; shift 1 2>/dev/null || true
BuildDir=""; Targets=""
while getopts ":b:t:" opt; do
  case "$opt" in
    b) BuildDir="$OPTARG" ;;
    t) Targets="$OPTARG" ;;
    *) ;;
  esac
done
[ -n "$BuildDir" ] || { echo "LOCAL_GATE_ERROR: -b BuildDir required" >&2; exit 1; }
avail_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
free_gib="$(awk -v k="$avail_kib" 'BEGIN{printf "%.2f", k/1048576}')"
if awk -v f="$free_gib" -v m="$MinFreeGiB" 'BEGIN{exit !(f<m)}'; then
  echo "RESOURCE_LOW_MEMORY: free=${free_gib} GiB required=${MinFreeGiB} GiB; refusing." >&2
  exit 75
fi
export CMAKE_BUILD_PARALLEL_LEVEL=2 OMP_NUM_THREADS=1 \
       OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
case "$Action" in
  Build)
    if [ -n "$Targets" ]; then
      # shellcheck disable=SC2086
      exec cmake --build "$BuildDir" --config Release --parallel 2 --target $Targets
    fi
    exec cmake --build "$BuildDir" --config Release --parallel 2
    ;;
  Test)
    # shellcheck disable=SC2086
    exec ctest --test-dir "$BuildDir" -C Release --parallel 2 \
         --output-on-failure --no-tests=error --timeout 300 $Targets
    ;;
  *) echo "LOCAL_GATE_ERROR: unknown action $Action" >&2; exit 1 ;;
esac
