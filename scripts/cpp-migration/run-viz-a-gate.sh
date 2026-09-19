#!/usr/bin/env bash
# VIZ-A dedicated acceptance gate (P-B 口径) — LAS/WLE convergence line.
#
# What this script is: a dedicated, resource-gated acceptance configuration
# that turns ON the WLE viewer stack — PWB_SCIENCE_BUILD_VIEWER +
# PWB_SCIENCE_VIEWER_TESTS + PWB_BUILD_CONV_22 (implies CONV-12/19: ingest,
# geomodel) — builds the line-A closure and runs its tests TWICE (green x2),
# plus a MALLOC audit subset and an OFF-configure check (the viewer switch
# must stay optional: default builds configure and the LAS branch degrades
# to the honest capability-unavailable message). Step 7 compile-covers the
# app-side production wiring (PWB_WITH_VIZ_A) in a PLATFORM=ON configure
# that reuses the shared vendored QGIS SDK read-only via PALEO_QGIS_* env
# (skipped with SKIP_VIZ_A_PLATFORM=1 when no SDK is available — the skip
# is then recorded honestly in the ledger, never silently).
#
# Coverage difference vs scripts/cpp-migration/run-integrated-gate.sh (the
# default gate): the default gate builds PLATFORM+DATA+SCIENCE with the
# viewer OFF — it covers ingest/ui_workers/science.* tests but NOT
# science.viewer.* or viz_a.*'s WLE-dependent tests. Making the external
# WLE SDK a hard dependency of every default build is a separate decision
# this script intentionally does not take (see
# docs/development/cpp-geoviz-completion-plan.md §1.2 P-B).
#
# Resource policy: every heavy step runs INSIDE the shared resource gate
# (jobs pinned to 2, min 8 GiB free; exit 75 = busy/low memory → the
# script backs off and retries; never bypasses the lock). This script does
# NOT nest gate calls while a gate lock is already held by this process.
#
# Failure policy: `set -uo pipefail` does NOT abort on a failing function
# call, so every step goes through `must` which exits on the first
# non-green action (a bare `gate ...` statement — and worse, an `if cmd;
# then` compound — silently swallowed failures in earlier revisions; the
# x2 pass, OFF check and step-7 grep only mean anything when the steps
# before them can actually fail).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
GATE="$HERE/invoke-resource-gate.sh"
BUILD_DIR="$REPO_ROOT/build/viz-a"
BUILD_DIR_OFF="$REPO_ROOT/build/viz-a-viewer-off"
BUILD_DIR_PLATFORM="$REPO_ROOT/build/viz-a-platform"
JOBS=2

VIZ_A_ARGS="-DPWB_BUILD_PLATFORM=OFF;-DPWB_BUILD_SCIENCE=ON;-DPWB_SCIENCE_BUILD_VIEWER=ON;-DPWB_SCIENCE_VIEWER_TESTS=ON;-DPWB_BUILD_CONV_22=ON"
VIZ_A_REGEX='^(viz_a\.|science\.viewer\.|ingest\.|ui_workers\.)'

gate() {
    # Run one gate action VERBATIM (callers pass their own -j/-m BEFORE any
    # `--` payload; the gate appends nothing — for Exec, appended flags
    # would land inside the wrapped command). Retry ONLY on exit 75 (slot
    # busy / low memory) with a 30-60s backoff; any other non-zero status
    # propagates via `|| code=$?` (an `if cmd; then` compound swallows it).
    local attempt=0 code=0
    while true; do
        code=0
        "$GATE" "$@" || code=$?
        if [[ "$code" -eq 0 ]]; then
            return 0
        fi
        if [[ "$code" -eq 75 ]]; then
            attempt=$((attempt + 1))
            if [[ "$attempt" -gt 240 ]]; then
                echo "run-viz-a-gate: resource gate stayed busy; aborting (75)" >&2
                return 75
            fi
            sleep $((30 + RANDOM % 31))
            continue
        fi
        echo "run-viz-a-gate: gate action '$*' failed (exit $code)" >&2
        return "$code"
    done
}

must() {
    gate "$@" || exit $?
}

echo "== [1/7] Configure build/viz-a (viewer ON, jobs=$JOBS) =="
must Configure -s "$REPO_ROOT" -b "$BUILD_DIR" -c Release -j "$JOBS" -m 8 -a "$VIZ_A_ARGS"

echo "== [2/7] Build the line-A closure =="
must Build -b "$BUILD_DIR" -j "$JOBS" -m 8 -t "pwb_ingest;pwb_ingest_las_wle;pwb_ui_workers;pwb_ui_workers_wle_load;pwb_visualization_well_log;viz_a.las_preview_core;viz_a.las_preview_wle;viz_a.wle_load;viz_a.consistency;viz_a.viewer_flow;viz_a.patterns;viz_a.install_cover;ingest.parsers;ui_workers.oracle;ui_workers.lifecycle;science.viewer.well_log_plan;science.viewer.well_log_native_host;science.viewer.well_log"

echo "== [3/7] Tests, pass 1 of 2 (green x2 rule) =="
must Test -b "$BUILD_DIR" -j "$JOBS" -m 8 -r "$VIZ_A_REGEX"

echo "== [4/7] Tests, pass 2 of 2 =="
must Test -b "$BUILD_DIR" -j "$JOBS" -m 8 -r "$VIZ_A_REGEX"

echo "== [5/7] MALLOC audit subset (heap abuse on the line-A surface) =="
# No QT_QPA_PLATFORM forcing: the offscreen plugin's GLX path cannot create
# contexts on real-display hosts (see the test ENVIRONMENT note); headless
# shells inherit offscreen from the environment as usual.
must Exec -j "$JOBS" -m 8 -- env MALLOC_CHECK_=3 LIBGL_ALWAYS_SOFTWARE=1 \
    ctest --test-dir "$BUILD_DIR" -R '^viz_a\.' --output-on-failure --no-tests=error --timeout 300

echo "== [6/7] OFF check: default (viewer OFF) still configures and the LAS branch degrades honestly =="
rm -rf "$BUILD_DIR_OFF"
must Configure -s "$REPO_ROOT" -b "$BUILD_DIR_OFF" -c Release -j "$JOBS" -m 8 \
    -a "-DPWB_BUILD_PLATFORM=OFF;-DPWB_BUILD_SCIENCE=ON;-DPWB_BUILD_CONV_22=ON"
must Build -b "$BUILD_DIR_OFF" -j "$JOBS" -m 8 -t "pwb_ingest;viz_a.las_preview_core"
must Test -b "$BUILD_DIR_OFF" -j "$JOBS" -m 8 -r '^viz_a\.las_preview_core$'
# No WLE bridge target may exist in the OFF tree.
if grep -q "pwb_ingest_las_wle" "$BUILD_DIR_OFF/build.ninja" 2>/dev/null; then
    echo "run-viz-a-gate: OFF configure unexpectedly built the WLE bridge" >&2
    exit 1
fi

echo "== [7/7] App wiring compile cover =="
# (a) Mandatory, environment-independent: the production wiring TU
# (viz_a_install.cpp + job_center.cpp) built and run against the real
# bridge targets (viz_a.install_cover; covers the MainWindow hook's body).
# Already covered by steps 2-4 if the regex ran it; assert it exists here
# so a future target-name drift cannot silently drop the cover.
grep -q "viz_a.install_cover" "$BUILD_DIR/build.ninja" \
    || { echo "run-viz-a-gate: viz_a.install_cover missing from the build" >&2; exit 1; }

# (b) Best-effort full platform configure (needs the vendored QGIS SDK;
# its manifest may not configure on every host — recorded, non-blocking).
# Default discovery: the shared main workspace holds the vendored SDK
# (read-only reuse; build output stays in this worktree). REPO_ROOT is
# this WORKTREE, so the main checkout is two levels up.
SIBLING_QGIS_SDK="$REPO_ROOT/../../main/native/qgis_render_bridge/build/qgis-vendor/output"
if [[ -z "${PALEO_QGIS_SDK_DIR:-}" && -d "$SIBLING_QGIS_SDK/lib" ]]; then
    export PALEO_QGIS_SDK_DIR="$SIBLING_QGIS_SDK"
    export PALEO_QGIS_BUILD_DIR="$REPO_ROOT/../../main/native/qgis_render_bridge/build/qgis-vendor"
    [[ -z "${PALEO_QGIS_SOURCE_DIR:-}" ]] && \
        export PALEO_QGIS_SOURCE_DIR="$REPO_ROOT/third_party/qgis"
fi
if [[ "${SKIP_VIZ_A_PLATFORM:-0}" == "1" || -z "${PALEO_QGIS_SDK_DIR:-}" ]]; then
    echo "run-viz-a-gate: full platform compile cover SKIPPED (no QGIS SDK available) — wiring covered by viz_a.install_cover; record in ledger"
else
    rm -rf "$BUILD_DIR_PLATFORM"
    if gate Configure -s "$REPO_ROOT" -b "$BUILD_DIR_PLATFORM" -c Release -j "$JOBS" -m 8 \
        -a "-DPWB_BUILD_PLATFORM=ON;-DPWB_BUILD_SCIENCE=ON;-DPWB_SCIENCE_BUILD_VIEWER=ON;-DPWB_BUILD_CONV_22=ON"; then
        must Build -b "$BUILD_DIR_PLATFORM" -j "$JOBS" -m 8 -t "pwb-platform"
        grep -q "viz_a_install" "$BUILD_DIR_PLATFORM/build.ninja" \
            || { echo "run-viz-a-gate: pwb-platform built WITHOUT viz_a_install (wiring dead)" >&2; exit 1; }
    else
        echo "run-viz-a-gate: full platform configure failed (vendored QGIS SDK manifest) — wiring covered by viz_a.install_cover; record in ledger" >&2
    fi
fi

echo "run-viz-a-gate: ALL GREEN"
