#!/usr/bin/env bash
# Unified pytest wrapper for the qgis-convergence worktree.
set -uo pipefail
ENGINE=/home/kevin/projects/paleo_project/main/geo-viz-engine
PP="$ENGINE"
for pkg in "$ENGINE"/packages/*/; do
    PP="$PP:${pkg%/}"
done
PP="$PP:/home/kevin/projects/paleo_project/main/well-log-engine"
cd /home/kevin/projects/paleo-qgis-convergence || exit 2
exec env -i \
    HOME="$HOME" TERM="${TERM:-xterm}" LANG="${LANG:-zh_CN.UTF-8}" \
    PATH="/opt/miniconda3/bin:/usr/bin:/bin" \
    QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
    LD_PRELOAD=/home/kevin/projects/paleo_project/round2-notes/libxmlshim.so \
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    PYTHONPATH="$PP" \
    /opt/miniconda3/bin/python3.13 -m pytest -p no:randomly -q "$@"
