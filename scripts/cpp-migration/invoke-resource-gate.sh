#!/usr/bin/env bash
# Shared admission gate for the C++ migration worktrees — POSIX port of
# Invoke-ResourceGate.ps1 (this machine has no pwsh; semantics are 1:1:
# exclusive lock file in the common git dir, >=MinFreeGiB available RAM,
# exit 75 on resource refusal, 2-job ceilings, build tree confined to
# <worktree>/build, environment saved and restored).
set -u

Action="${1:-Probe}"; shift 1 2>/dev/null || true
Usage="usage: invoke-resource-gate.sh {Probe|Configure|Build|Test} [-s SourceDir] [-b BuildDir] [-c Configuration] [-t 'target;list'] [-a cmakeArg;...] [-r TestRegex] [-m MinFreeGiB]"
SourceDir=""; BuildDir=""; Configuration="Release"; Targets=""; CmakeArguments=""; TestRegex="."; MinFreeGiB=8
while getopts ":s:b:c:t:a:r:m:" opt; do
  case "$opt" in
    s) SourceDir="$OPTARG" ;;
    b) BuildDir="$OPTARG" ;;
    c) Configuration="$OPTARG" ;;
    t) Targets="$OPTARG" ;;
    a) CmakeArguments="$OPTARG" ;;
    r) TestRegex="$OPTARG" ;;
    m) MinFreeGiB="$OPTARG" ;;
    *) echo "$Usage" >&2; exit 1 ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "RESOURCE_GATE_ERROR: run from a migration worktree" >&2; exit 1; }
common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || { echo "RESOURCE_GATE_ERROR: cannot resolve common git dir" >&2; exit 1; }
[ -d "$common_dir" ] || common_dir="$repo_root/$common_dir"
gate_path="$common_dir/cpp-migration-heavy.lock"

exec 9>"$gate_path"
if ! flock -n 9; then
  echo "RESOURCE_BUSY: another migration job holds the shared slot; exit=75."
  exit 75
fi
printf 'pid=%s action=%s root=%s time=%s\n' "$$" "$Action" "$repo_root" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&9

# MemAvailable counts reclaimable cache (the closest match to the gate's
# intent: memory a new build can actually use right now).
avail_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
free_gib="$(awk -v k="$avail_kib" 'BEGIN{printf "%.2f", k/1048576}')"
below="$(awk -v f="$free_gib" -v m="$MinFreeGiB" 'BEGIN{print (f<m)?1:0}')"
if [ "$below" = 1 ]; then
  echo "RESOURCE_LOW_MEMORY: free=${free_gib} GiB required=${MinFreeGiB} GiB; exit=75."
  exit 75
fi
if [ "$Action" = Probe ]; then
  echo "RESOURCE_READY: shared slot available; free=${free_gib} GiB; jobs=2; probe only."
  exit 0
fi

[ -n "$BuildDir" ] || { echo "RESOURCE_GATE_ERROR: BuildDir is required" >&2; exit 1; }
case "$BuildDir" in /*) resolved_build="$BuildDir" ;; *) resolved_build="$PWD/$BuildDir" ;; esac
resolved_build="$(realpath -m "$resolved_build")"
allowed_prefix="$repo_root/build/"
case "$resolved_build/" in
  "$allowed_prefix"*) ;;
  *) echo "RESOURCE_GATE_ERROR: BuildDir must be a child of this worktree/build; shared writable build trees are forbidden" >&2; exit 1 ;;
esac

saved_cmake_par="${CMAKE_BUILD_PARALLEL_LEVEL-}"
saved_ctest_par="${CTEST_PARALLEL_LEVEL-}"
saved_omp="${OMP_NUM_THREADS-}"
export CMAKE_BUILD_PARALLEL_LEVEL=2 CTEST_PARALLEL_LEVEL=2 \
       OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

restore_env() {
  [ -z "$saved_cmake_par" ] && unset CMAKE_BUILD_PARALLEL_LEVEL || export CMAKE_BUILD_PARALLEL_LEVEL="$saved_cmake_par"
  [ -z "$saved_ctest_par" ] && unset CTEST_PARALLEL_LEVEL || export CTEST_PARALLEL_LEVEL="$saved_ctest_par"
  [ -z "$saved_omp" ] && unset OMP_NUM_THREADS || export OMP_NUM_THREADS="$saved_omp"
}
trap restore_env EXIT

case "$Action" in
  Configure)
    [ -n "$SourceDir" ] || { echo "RESOURCE_GATE_ERROR: SourceDir is required for Configure" >&2; exit 1; }
    resolved_source="$(cd "$SourceDir" 2>/dev/null && pwd)" || { echo "RESOURCE_GATE_ERROR: SourceDir not found" >&2; exit 1; }
    case "$resolved_source/" in
      "$repo_root/"*) ;;
      *) echo "RESOURCE_GATE_ERROR: SourceDir must be in this worktree; pass read-only SDK paths via CMake variables" >&2; exit 1 ;;
    esac
    # shellcheck disable=SC2086  # CmakeArguments is a ';'-list by contract
    cmake -S "$resolved_source" -B "$resolved_build" -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" $(printf '%s ' "${CmakeArguments//;/ }")
    ;;
  Build)
    if [ -n "$Targets" ]; then
      cmake --build "$resolved_build" --config "$Configuration" --parallel 2 --target $(printf '%s ' "${Targets//;/ }")
    else
      cmake --build "$resolved_build" --config "$Configuration" --parallel 2
    fi
    ;;
  Test)
    ctest --test-dir "$resolved_build" -C "$Configuration" --parallel 2 --output-on-failure --no-tests=error --timeout 180 -R "$TestRegex"
    ;;
  *) echo "RESOURCE_GATE_ERROR: unknown action $Action" >&2; echo "$Usage" >&2; exit 1 ;;
esac
exit $?
