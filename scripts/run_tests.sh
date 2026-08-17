#!/usr/bin/env bash
# Local test runner for paleo-workbench + geo-viz-engine.
#
# Pins the interpreter, forces offscreen/software GL, and — critically — puts the
# *submodule* geo-viz-engine checkout ahead of the conda editable installs, which
# on this workstation point at a different sibling clone.
#
#   scripts/run_tests.sh workbench [pytest args...]   # tests/ in this repo
#   scripts/run_tests.sh engine    [pytest args...]   # geo-viz-engine tests
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT/geo-viz-engine"

export CONDA_PREFIX=/opt/miniconda3
export PYTHONHOME=/opt/miniconda3
# Put the conda interpreter first on PATH: the shell's default `python3`
# (/usr/sbin/python3, 3.14 here) has no PySide6, and setting PYTHONHOME alone
# leaves it resolving to that interpreter and failing with
# "No module named 'encodings'".
export PATH="$CONDA_PREFIX/bin:$PATH"
export QT_QPA_PLATFORM=offscreen
export LIBGL_ALWAYS_SOFTWARE=1
# pyqtgraph.opengl reaches for GLX directly and dies on this host's :1 display
# even under the offscreen QPA plugin, so hide it.
unset DISPLAY

engine_pythonpath() {
    # Omit the bare engine root when it contains a committed native .so
    # (same rule as paleo_workbench.env_bootstrap / packaging #435).
    local paths=""
    if ! compgen -G "$ENGINE"/*.so > /dev/null && ! compgen -G "$ENGINE"/*.pyd > /dev/null; then
        paths="$ENGINE"
    fi
    for pkg in "$ENGINE"/packages/*/; do
        if [ -n "$paths" ]; then
            paths="$paths:${pkg%/}"
        else
            paths="${pkg%/}"
        fi
    done
    printf '%s' "$paths"
}

target="${1:-workbench}"
shift || true

case "$target" in
workbench)
    cd "$ROOT"
    # Root pyproject already sets pythonpath to the submodule packages.
    # --continue-on-collection-errors lets the run finish when some modules
    # fail to import (e.g. unbuilt native extensions on a fresh checkout);
    # collection errors STILL make pytest exit non-zero, so this does NOT
    # mask real import regressions — grep the summary for "error" lines.
    exec python3 -m pytest -p no:randomly --continue-on-collection-errors "$@"
    ;;
engine)
    cd "$ENGINE"
    export PYTHONPATH="$(engine_pythonpath)"
    exec python3 -m pytest -p no:randomly \
        tests packages/geoviz_well_seismic_3d/tests packages/geoviz_well_log/tests \
        "$@"
    ;;
*)
    echo "usage: $0 {workbench|engine} [pytest args...]" >&2
    exit 2
    ;;
esac
