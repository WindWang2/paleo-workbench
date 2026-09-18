#!/usr/bin/env bash
# Shared admission gate for the C++ migration worktrees — POSIX port of
# Invoke-ResourceGate.ps1 (1:1 semantics: exclusive flock in the common git
# dir, free-memory gate, bounded job ceiling, stale-lock recovery, build tree
# confined to <worktree>/build, environment saved and restored).
#
# Usage:
#   invoke-resource-gate.sh {Probe|Configure|Build|Test}
#     [-s SourceDir] [-b BuildDir] [-c Configuration] [-t 'target;list']
#     [-a cmakeArg;...] [-r TestRegex] [-m MinFreeGiB] [-j Jobs]
#     [-M StaleLockMinutes] [-F]
#
# Exit codes: 0 success; 1 internal/usage error; 64 invalid usage (EX_USAGE);
# 75 resource refusal (busy or low memory); 124 reserved (timeout).
#
# Diagnostic tokens (machine-readable, exactly one summary line per outcome):
#   RESOURCE_READY free_gib=.. jobs=.. lock=<path>
#   RESOURCE_BUSY holder_pid=.. age_min=..
#   RESOURCE_LOW_MEMORY free_gib=.. required=..
#   RESOURCE_STALE_LOCK_RECOVERED age_min=..
#   RESOURCE_GATE_ERROR detail=..
set -u

Action="${1:-Probe}"; shift 1 2>/dev/null || true
Usage="usage: invoke-resource-gate.sh {Probe|Configure|Build|Test} [-s SourceDir] [-b BuildDir] [-c Configuration] [-t 'target;list'] [-a cmakeArg;...] [-r TestRegex] [-m MinFreeGiB] [-j Jobs] [-M StaleLockMinutes] [-F]"
SourceDir=""; BuildDir=""; Configuration="Release"; Targets=""; CmakeArguments=""; TestRegex="."; MinFreeGiB="8"; Jobs="2"; StaleLockMinutes="45"; ForceRecoverLock=0
while getopts ":s:b:c:t:a:r:m:j:M:F" opt; do
  case "$opt" in
    s) SourceDir="$OPTARG" ;;
    b) BuildDir="$OPTARG" ;;
    c) Configuration="$OPTARG" ;;
    t) Targets="$OPTARG" ;;
    a) CmakeArguments="$OPTARG" ;;
    r) TestRegex="$OPTARG" ;;
    m) MinFreeGiB="$OPTARG" ;;
    j) Jobs="$OPTARG" ;;
    M) StaleLockMinutes="$OPTARG" ;;
    F) ForceRecoverLock=1 ;;
    *) echo "$Usage" >&2; exit 1 ;;
  esac
done

# --- validate flags (invalid usage -> 64, before touching the lock) ---
case "$MinFreeGiB" in
  ''|*[!0-9.]*) echo "RESOURCE_GATE_ERROR detail=invalid MinFreeGiB: '$MinFreeGiB' must be a positive number"; exit 64 ;;
esac
min_free="$(awk -v v="$MinFreeGiB" 'BEGIN{ if (v+0>0) {print v+0} else {print "BAD"} }')"
if [ "$min_free" = "BAD" ]; then
  echo "RESOURCE_GATE_ERROR detail=invalid MinFreeGiB: '$MinFreeGiB' must be a positive number"; exit 64
fi
case "$Jobs" in
  ''|*[!0-9]*) echo "RESOURCE_GATE_ERROR detail=invalid Jobs: '$Jobs' must be an integer 1..8"; exit 64 ;;
esac
if [ "$Jobs" -lt 1 ]; then
  echo "RESOURCE_GATE_ERROR detail=invalid Jobs: $Jobs must be >= 1"; exit 64
fi
if [ "$Jobs" -gt 8 ]; then
  echo "RESOURCE_GATE_WARNING detail=Jobs $Jobs clamped to 8 (unbounded parallelism rejected)"
  Jobs=8
fi
case "$StaleLockMinutes" in
  ''|*[!0-9]*) echo "RESOURCE_GATE_ERROR detail=StaleLockMinutes must be a positive integer"; exit 64 ;;
esac
if [ "$StaleLockMinutes" -le 0 ]; then
  echo "RESOURCE_GATE_ERROR detail=StaleLockMinutes must be a positive integer"; exit 64
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "RESOURCE_GATE_ERROR detail=run from a migration worktree" >&2; exit 1; }
common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || { echo "RESOURCE_GATE_ERROR detail=cannot resolve common git dir" >&2; exit 1; }
[ -d "$common_dir" ] || common_dir="$repo_root/$common_dir"
gate_path="$common_dir/cpp-migration-heavy.lock"
owner_path="$common_dir/cpp-migration-heavy.owner"

exec 9>"$gate_path"
if ! flock -n 9; then
  # A live process holds the flock -> the slot is busy. The owner sidecar is a
  # separate file and stays readable while the lock is held.
  holder_pid="unknown"; age_min="0.0"
  if [ -f "$owner_path" ]; then
    holder_pid="$(awk -F'=' '/^pid=/{print $2; exit}' "$owner_path" | awk '{print $1}')"
    [ -z "$holder_pid" ] && holder_pid="unknown"
    now="$(date +%s)"
    mtime="$(stat -c %Y "$owner_path" 2>/dev/null || echo "$now")"
    age_min="$(awk -v n="$now" -v m="$mtime" 'BEGIN{printf "%.1f", (n-m)/60}')"
  fi
  echo "RESOURCE_BUSY holder_pid=$holder_pid age_min=$age_min"
  exit 75
fi

# Successful acquire: stale-lock recovery (never reclaim a live owner).
# If the previous owner died, the OS freed the flock and we acquired it; an old
# owner sidecar means it was abandoned. Never reclaim when the recorded pid is
# still alive (kill -0).
if [ -f "$owner_path" ]; then
  holder_pid="$(awk -F'=' '/^pid=/{print $2; exit}' "$owner_path" | awk '{print $1}')"
  now="$(date +%s)"
  mtime="$(stat -c %Y "$owner_path" 2>/dev/null || echo "$now")"
  age_min="$(awk -v n="$now" -v m="$mtime" 'BEGIN{printf "%.1f", (n-m)/60}')"
  stale=0
  if [ "$ForceRecoverLock" = 1 ] || awk -v a="$age_min" -v s="$StaleLockMinutes" 'BEGIN{exit !(a+0>=s+0)}'; then
    stale=1
  fi
  alive=0
  if [ -n "$holder_pid" ] && [ "$holder_pid" != "unknown" ]; then
    kill -0 "$holder_pid" 2>/dev/null && alive=1
  fi
  if [ "$stale" = 1 ] && [ "$alive" = 0 ]; then
    echo "RESOURCE_STALE_LOCK_RECOVERED age_min=$age_min"
  fi
fi

# Publish ownership (readable sidecar; the .lock file stays flocked).
printf 'pid=%s action=%s root=%s time=%s\n' "$$" "$Action" "$repo_root" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$owner_path"

# --- free-memory gate ---
# MemAvailable counts reclaimable cache (closest to the memory a new build can
# actually use right now).
avail_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)"
[ -z "$avail_kib" ] && avail_kib=0
free_gib="$(awk -v k="$avail_kib" 'BEGIN{printf "%.1f", k/1048576}')"
below="$(awk -v f="$free_gib" -v m="$min_free" 'BEGIN{print (f+0<m+0)?1:0}')"
if [ "$below" = 1 ]; then
  echo "RESOURCE_LOW_MEMORY free_gib=$free_gib required=$min_free"
  exit 75
fi

if [ "$Action" = Probe ]; then
  echo "RESOURCE_READY free_gib=$free_gib jobs=$Jobs lock=$gate_path"
  exit 0
fi

# --- action-specific guards ---
[ -n "$BuildDir" ] || { echo "RESOURCE_GATE_ERROR detail=BuildDir is required" >&2; exit 1; }
case "$BuildDir" in /*) resolved_build="$BuildDir" ;; *) resolved_build="$PWD/$BuildDir" ;; esac
resolved_build="$(realpath -m "$resolved_build")"
allowed_prefix="$repo_root/build/"
case "$resolved_build/" in
  "$allowed_prefix"*) ;;
  *) echo "RESOURCE_GATE_ERROR detail=BuildDir must be a child of this worktree/build; shared writable build trees are forbidden" >&2; exit 1 ;;
esac
if [ "$Action" = Build ] || [ "$Action" = Test ]; then
  [ -d "$resolved_build" ] || { echo "RESOURCE_GATE_ERROR detail=Build directory '$resolved_build' does not exist yet. Run Configure first to create it." >&2; exit 1; }
fi

saved_cmake_par="${CMAKE_BUILD_PARALLEL_LEVEL-}"
saved_ctest_par="${CTEST_PARALLEL_LEVEL-}"
saved_omp="${OMP_NUM_THREADS-}"
export CMAKE_BUILD_PARALLEL_LEVEL="$Jobs" CTEST_PARALLEL_LEVEL="$Jobs" \
       OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

restore_env() {
  [ -z "$saved_cmake_par" ] && unset CMAKE_BUILD_PARALLEL_LEVEL || export CMAKE_BUILD_PARALLEL_LEVEL="$saved_cmake_par"
  [ -z "$saved_ctest_par" ] && unset CTEST_PARALLEL_LEVEL || export CTEST_PARALLEL_LEVEL="$saved_ctest_par"
  [ -z "$saved_omp" ] && unset OMP_NUM_THREADS || export OMP_NUM_THREADS="$saved_omp"
}
trap restore_env EXIT

case "$Action" in
  Configure)
    [ -n "$SourceDir" ] || { echo "RESOURCE_GATE_ERROR detail=SourceDir is required for Configure" >&2; exit 1; }
    resolved_source="$(cd "$SourceDir" 2>/dev/null && pwd)" || { echo "RESOURCE_GATE_ERROR detail=SourceDir not found" >&2; exit 1; }
    case "$resolved_source/" in
      "$repo_root/"*) ;;
      *) echo "RESOURCE_GATE_ERROR detail=SourceDir must be in this worktree; pass read-only SDK paths via CMake variables" >&2; exit 1 ;;
    esac
    # shellcheck disable=SC2086  # CmakeArguments is a ';'-list by contract
    cmake -S "$resolved_source" -B "$resolved_build" -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" $(printf '%s ' "${CmakeArguments//;/ }")
    ;;
  Build)
    if [ -n "$Targets" ]; then
      cmake --build "$resolved_build" --config "$Configuration" --parallel "$Jobs" --target $(printf '%s ' "${Targets//;/ }")
    else
      cmake --build "$resolved_build" --config "$Configuration" --parallel "$Jobs"
    fi
    ;;
  Test)
    ctest --test-dir "$resolved_build" -C "$Configuration" --parallel "$Jobs" --output-on-failure --no-tests=error --timeout 180 -R "$TestRegex"
    ;;
  *) echo "RESOURCE_GATE_ERROR detail=unknown action $Action" >&2; echo "$Usage" >&2; exit 1 ;;
esac
exit $?
