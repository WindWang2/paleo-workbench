#!/usr/bin/env bash
# POSIX self-test mirror of Test-ResourceGate.ps1 for invoke-resource-gate.sh.
# Cases:
#   (a) Probe succeeds              -> RESOURCE_READY, exit 0
#   (b) a concurrent holder          -> RESOURCE_BUSY, exit 75
#   (c) a huge MinFreeGiB            -> RESOURCE_LOW_MEMORY, exit 75
#   (d) a backdated (stale) lock     -> RESOURCE_STALE_LOCK_RECOVERED + READY, exit 0
#   (e) -j 99                        -> clamped to 8 (jobs=8 + warning), exit 0
#   (f) invalid usage                -> RESOURCE_GATE_ERROR, exit 64
#   (g) Build with missing build dir -> RESOURCE_GATE_ERROR "run Configure first", exit 1
#   (h) Exec -- sh -c exit 7        -> child exit code propagated, PWB_GATE_HELD visible
# Prints PASS/FAIL per case. Exit codes: 0 all cases passed, 1 a case failed,
# 77 SKIPPED because this host lacks flock / /proc/meminfo (the POSIX gate is
# Linux-only, so the mirror is not runnable from Git-Bash on Windows).
set -u

if ! command -v flock >/dev/null 2>&1 || [ ! -r /proc/meminfo ]; then
  echo "SELF-TEST SKIPPED: this POSIX gate needs flock and /proc/meminfo (Linux)."
  echo "Use scripts/cpp-migration/Test-ResourceGate.ps1 on Windows."
  exit 77
fi

gate_script="$(cd "$(dirname "$0")" && pwd)/invoke-resource-gate.sh"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "RESOURCE_GATE_ERROR: not in a worktree" >&2; exit 1; }
common_dir="$(git rev-parse --git-common-dir 2>/dev/null)"
[ -d "$common_dir" ] || common_dir="$repo_root/$common_dir"
gate_path="$common_dir/cpp-migration-heavy.lock"
owner_path="$common_dir/cpp-migration-heavy.owner"

avail_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)"
avail_kib="${avail_kib:-0}"
free_gib="$(awk -v k="$avail_kib" 'BEGIN{printf "%.4f", k/1048576}')"
success_threshold="$(awk -v f="$free_gib" 'BEGIN{printf "%.4f", f*0.5}')"
low_threshold="$(awk -v f="$free_gib" 'BEGIN{printf "%.4f", f+10}')"

GATE_OUT=""; GATE_CODE=0
invoke_gate() {
  local outfile; outfile="$(mktemp)"
  bash "$gate_script" "$@" > "$outfile" 2>&1
  GATE_CODE=$?
  GATE_OUT="$(cat "$outfile")"
  rm -f "$outfile"
}

clean_lock() { rm -f "$gate_path" "$owner_path" 2>/dev/null; }

pass=0; fail=0
check() {  # name condition detail
  if [ "$2" = 1 ]; then echo "[PASS] $1: $3"; pass=$((pass+1)); else echo "[FAIL] $1: $3"; fail=$((fail+1)); fi
}

# (a) Probe succeeds
clean_lock
invoke_gate Probe -m "$success_threshold"
[ $GATE_CODE -eq 0 ] && echo "$GATE_OUT" | grep -q RESOURCE_READY && ok=1 || ok=0
check "(a) Probe succeeds" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (b) concurrent holder -> busy
clean_lock
(
  exec 200>"$gate_path"
  flock 200
  echo "pid=$BASHPID action=Test root=x time=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$owner_path"
  invoke_gate Probe -m "$success_threshold"
)
[ $GATE_CODE -eq 75 ] && echo "$GATE_OUT" | grep -q RESOURCE_BUSY && ok=1 || ok=0
check "(b) concurrent busy" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (c) huge MinFreeGiB -> low memory
clean_lock
invoke_gate Probe -m "$low_threshold"
[ $GATE_CODE -eq 75 ] && echo "$GATE_OUT" | grep -q RESOURCE_LOW_MEMORY && ok=1 || ok=0
check "(c) low memory" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (d) stale lock recovery
# The recorded owner must be a DEAD pid. pid 1 is init and is always alive on
# Linux, so kill -0 would succeed and recovery would (correctly) be refused -
# use a pid that cannot exist instead.
clean_lock
touch "$gate_path" "$owner_path"
echo "pid=999999 action=Test root=x time=2020-01-01T00:00:00Z" > "$owner_path"
touch -d "$(date -d '90 minutes ago' +%Y-%m-%dT%H:%M:%S)" "$gate_path" "$owner_path"
invoke_gate Probe -m "$success_threshold"
[ $GATE_CODE -eq 0 ] && echo "$GATE_OUT" | grep -q RESOURCE_STALE_LOCK_RECOVERED && echo "$GATE_OUT" | grep -q RESOURCE_READY && ok=1 || ok=0
check "(d) stale lock recovered" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (e) Jobs 99 clamped to 8
clean_lock
invoke_gate Probe -m "$success_threshold" -j 99
[ $GATE_CODE -eq 0 ] && echo "$GATE_OUT" | grep -q 'jobs=8' && echo "$GATE_OUT" | grep -q RESOURCE_GATE_WARNING && ok=1 || ok=0
check "(e) Jobs clamp to 8" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (f) invalid usage -> 64
clean_lock
invoke_gate Probe -m notanumber
[ $GATE_CODE -eq 64 ] && echo "$GATE_OUT" | grep -q RESOURCE_GATE_ERROR && ok=1 || ok=0
check "(f) invalid usage" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (g) Build with missing build dir -> refuse
clean_lock
invoke_gate Build -b "$repo_root/build/__gate_test_missing__" -m "$success_threshold"
[ $GATE_CODE -eq 1 ] && echo "$GATE_OUT" | grep -q RESOURCE_GATE_ERROR && echo "$GATE_OUT" | grep -q "Configure first" && ok=1 || ok=0
check "(g) Build missing build dir refused" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

# (h) Exec propagates the child exit code and marks the child as gated
clean_lock
invoke_gate Exec -m "$success_threshold" -- sh -c 'test "$PWB_GATE_HELD" = 1 || exit 9; exit 7'
if [ $GATE_CODE -eq 7 ]; then ok=1; else ok=0; fi
check "(h) Exec propagates child exit code and sets PWB_GATE_HELD" "$ok" "exit=$GATE_CODE out=$GATE_OUT"

clean_lock
echo "SELF-TEST: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
