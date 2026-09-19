#!/usr/bin/env bash
# VIZ-A dedicated acceptance gate (P-B 口径) — LAS/WLE convergence line.
#
# What this script is: a dedicated, resource-gated acceptance configuration
# that turns ON the WLE viewer stack — PWB_SCIENCE_BUILD_VIEWER +
# PWB_SCIENCE_VIEWER_TESTS + PWB_BUILD_CONV_22 (implies CONV-12/19: ingest,
# geomodel) — builds the line-A closure and runs its tests TWICE (green x2),
# plus a MALLOC audit subset and an OFF-configure check (the viewer switch
# must stay optional: default builds configure and the LAS branch degrades
# to the honest capability-unavailable message).
#
# Coverage difference vs scripts/cpp-migration/run-integrated-gate.sh (the
# default gate): the default gate builds PLATFORM+DATA+SCIENCE with the
# viewer OFF — it covers ingest/ui_workers/science.* tests but NOT
# science.viewer.* or viz_a.*'s WLE-dependent tests, and the app LAS
# wiring (PWB_WITH_VIZ_A) is compile-covered only in this gate. Making the
# external WLE SDK a hard dependency of every default build is a separate
# decision this script intentionally does not take (see
# docs/development/cpp-geoviz-completion-plan.md §1.2 P-B).
#
# Resource policy: every heavy step runs INSIDE the shared resource gate
# (jobs pinned to 2, min 8 GiB free; exit 75 = busy/low memory → the
# script backs off and retries; never bypasses the lock). This script does
# NOT nest gate calls while a gate lock is already held by this process.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
GATE="$HERE/invoke-resource-gate.sh"
BUILD_DIR="$REPO_ROOT/build/viz-a"
BUILD_DIR_OFF="$REPO_ROOT/build/viz-a-viewer-off"
JOBS=2

# The CMake switch set defining the VIZ-A closure.
VIZ_A_ARGS="-DPWB_BUILD_PLATFORM=OFF;-DPWB_BUILD_SCIENCE=ON;-DPWB_SCIENCE_BUILD_VIEWER=ON;-DPWB_SCIENCE_VIEWER_TESTS=ON;-DPWB_BUILD_CONV_22=ON"

# Test selection: line-A tests + the viewer suite + the affected regression
# surfaces (ingest parsers, ui_workers oracle/lifecycle, science core).
VIZ_A_REGEX='^(viz_a\.|science\.viewer\.|ingest\.|ui_workers\.)'

gate() {
    # Retry on exit 75 (slot busy / low memory) with a 30-60s backoff.
    local attempt=0
    while true; do
        if "$GATE" "$@" -j "$JOBS" -m 8; then
            return 0
        fi
        local code=$?
        if [[ "$code" == "75" ]]; then
            attempt=$((attempt + 1))
            if [[ "$attempt" -gt 120 ]]; then
                echo "run-viz-a-gate: resource gate stayed busy for ~2h; aborting" >&2
                return 75
            fi
            sleep $((30 + RANDOM % 31))
            continue
        fi
        echo "run-viz-a-gate: gate action failed (exit $code)" >&2
        return "$code"
    done
}

echo "== [1/6] Configure build/viz-a (viewer ON, jobs=$JOBS) =="
gate Configure -s "$REPO_ROOT" -b "$BUILD_DIR" -c Release -a "$VIZ_A_ARGS"

echo "== [2/6] Build the line-A closure =="
gate Build -b "$BUILD_DIR" -t "pwb_ingest;pwb_ingest_las_wle;pwb_ui_workers;pwb_ui_workers_wle_load;pwb_visualization_well_log;viz_a.las_preview_core;viz_a.las_preview_wle;viz_a.wle_load;viz_a.consistency;viz_a.viewer_flow;viz_a.patterns;ingest.parsers;ui_workers.oracle;ui_workers.lifecycle"

echo "== [3/6] Tests, pass 1 of 2 (green x2 rule) =="
gate Test -b "$BUILD_DIR" -r "$VIZ_A_REGEX"

echo "== [4/6] Tests, pass 2 of 2 =="
gate Test -b "$BUILD_DIR" -r "$VIZ_A_REGEX"

echo "== [5/6] MALLOC audit subset (heap abuse on the line-A surface) =="
gate Exec -m 8 -- env MALLOC_CHECK_=3 QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
    ctest --test-dir "$BUILD_DIR" -R '^viz_a\.' --output-on-failure --no-tests=error --timeout 300

echo "== [6/6] OFF check: default (viewer OFF) still configures and the LAS branch degrades honestly =="
rm -rf "$BUILD_DIR_OFF"
gate Configure -s "$REPO_ROOT" -b "$BUILD_DIR_OFF" -c Release \
    -a "-DPWB_BUILD_PLATFORM=OFF;-DPWB_BUILD_SCIENCE=ON;-DPWB_BUILD_CONV_22=ON"
gate Build -b "$BUILD_DIR_OFF" -t "pwb_ingest;viz_a.las_preview_core"
gate Test -b "$BUILD_DIR_OFF" -r '^viz_a\.las_preview_core$'
# No WLE bridge target may exist in the OFF tree.
if grep -q "pwb_ingest_las_wle" "$BUILD_DIR_OFF/build.ninja" 2>/dev/null; then
    echo "run-viz-a-gate: OFF configure unexpectedly built the WLE bridge" >&2
    exit 1
fi

echo "run-viz-a-gate: ALL GREEN"
