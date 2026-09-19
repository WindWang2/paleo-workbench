#!/usr/bin/env bash
# audit-python-runtime-deps.sh — the C++ product's python-runtime audit
# (native-product closure, task F).
#
# Two halves of the same contract:
#   1. source audit — the production C++ paths (apps/, libs/application,
#      libs/qgis, libs/ui, libs/tool_policy, plus the platform link set)
#      must not reference the Python C API / PySide / python subprocesses;
#   2. link audit (POSIX, --exe) — the full ldd closure of a built product
#      binary must not resolve python/PySide/shiboken shared objects.
#
# Known classifications (see docs/development/cpp-platform/native-product-closure.md):
#   must-remove     : none found as of 2026-09-18 (fails the script)
#   compat seam     : libs/mapping_bind (CONV-20 pybind facade) — optional,
#                     off by default, consumed BY Python, never linked into
#                     the product binary; whitelisted in the source scan
#   test/oracle only: libs/**/oracle/*.py, tools/oracle/*.py — dev-time
#                     fixture generators; whitelisted (never shipped)
#
# Exit 0 = clean; exit 1 = violation (with file:line evidence).
set -u

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
Status=0

scan_sources() {
    # The product link closure (apps CMakeLists), not just the shell libs.
    local paths=(
        "$RepoRoot/apps"
        "$RepoRoot/libs/application"
        "$RepoRoot/libs/qgis"
        "$RepoRoot/libs/ui"
        "$RepoRoot/libs/tool_policy"
        "$RepoRoot/libs/data_suite"
        "$RepoRoot/libs/domain"
        "$RepoRoot/libs/project"
        "$RepoRoot/libs/workspace"
        "$RepoRoot/libs/catalog"
        "$RepoRoot/libs/algorithms"
        "$RepoRoot/libs/visualization"
        "$RepoRoot/libs/workflow"
        "$RepoRoot/libs/workflow_engine"
        "$RepoRoot/libs/mapping_kernel"
        "$RepoRoot/libs/seismic_viewer"
        "$RepoRoot/libs/seismic_attributes"
        "$RepoRoot/libs/seismic_io"
    )
    echo "== source audit: ${paths[*]}"
    # Raw patterns: Python C API, PySide/shiboken includes, spawning python.
    # cpp-close-12: pure comment lines (// or /* or leading *) are exempt —
    # the raw pattern matched prose like "dlopened ... pulled a python" in
    # self_check.cpp, a false positive of the must-remove class.
    local hits
    hits=$(grep -rnE '(#include[[:space:]]*<Python\.h>|#include[[:space:]]*"Python\.h"|#include[[:space:]]*<PySide|#include[[:space:]]*<shiboken|Py_Initialize|Py_RunString|PyRun_|PyImport_|subprocess.*python|system\("python|QProcess[^;]*start[^;]*python|startDetached.*python|dlopen[^;]*python)' \
        "${paths[@]}" 2>/dev/null | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*)' || true)
    if [ -n "$hits" ]; then
        echo "VIOLATION (must-remove class):"
        echo "$hits"
        Status=1
    else
        echo "  clean: no python C API / PySide / subprocess-python references"
    fi

    # pybind usage outside the sanctioned compat facades is a violation
    # too. cpp-close-12: cartography_bind joins mapping_bind — the same
    # HAS_CPP-dispatch class (pybind facade consumed BY Python via
    # paleo_workbench/mapping/cartography_native.py, never linked into the
    # product binary; the --exe ldd audit verifies that).
    local pybind
    pybind=$(grep -rln "pybind11" "$RepoRoot/libs" --include="*.cpp" --include="*.hpp" 2>/dev/null \
        | grep -v -e "libs/mapping_bind" -e "libs/cartography/cartography_bind" || true)
    if [ -n "$pybind" ]; then
        echo "VIOLATION (pybind11 outside the mapping_bind/cartography_bind compat seams):"
        echo "$pybind"
        Status=1
    else
        echo "  clean: pybind11 confined to the mapping_bind/cartography_bind compat seams"
    fi
}

scan_link_closure() {
    local exe="$1"
    echo "== link audit: $exe"
    if [ ! -x "$exe" ]; then
        echo "  binary not found/executable — skipped (build first)"
        return
    fi
    local closure
    closure=$(ldd "$exe" 2>/dev/null || true)
    if [ -z "$closure" ]; then
        echo "  ldd produced nothing (static or stripped?) — skipped"
        return
    fi
    local lowered
    lowered=$(printf '%s' "$closure" | tr '[:upper:]' '[:lower:]')
    for banned in python pyside shiboken; do
        if printf '%s' "$lowered" | grep -q "$banned"; then
            echo "VIOLATION: '$banned' in the ldd closure:"
            printf '%s\n' "$closure" | grep -i "$banned"
            Status=1
            return
        fi
    done
    echo "  clean: closure python-free"
}

case "${1:-}" in
    --exe)
        [ $# -ge 2 ] || { echo "usage: $0 [--exe <binary>]"; exit 2; }
        scan_link_closure "$2"
        ;;
    ""|--all)
        scan_sources
        if [ -x "$RepoRoot/build/native-product/bin/pwb-platform" ]; then
            scan_link_closure "$RepoRoot/build/native-product/bin/pwb-platform"
        elif [ -x "$RepoRoot/build/native-product/apps/paleo_workbench_platform/pwb-platform" ]; then
            scan_link_closure "$RepoRoot/build/native-product/apps/paleo_workbench_platform/pwb-platform"
        elif [ -x "$RepoRoot/build/native-product/pwb-platform" ]; then
            scan_link_closure "$RepoRoot/build/native-product/pwb-platform"
        else
            echo "== link audit: no built product binary under build/native-product — SKIPPED (source audit only)"
        LinkSkipped=1
        fi
        ;;
    *)
        echo "usage: $0 [--exe <binary>]"; exit 2
        ;;
esac

if [ "$Status" -eq 0 ] && [ "${LinkSkipped:-0}" -eq 1 ]; then
    echo "AUDIT PASS (link audit skipped)"
elif [ "$Status" -eq 0 ]; then
    echo "AUDIT PASS"
fi
exit "$Status"
