#!/usr/bin/env bash
# pytest wrapper for the P0+P1 convergence worktree (paleo-p0-p1).
# Same env contract as ../paleo_project/run_env.sh; PYTHONPATH points at THIS
# worktree's geo-viz-engine / well-log-engine submodule checkouts.
set -uo pipefail

ENGINE=/home/kevin/projects/paleo-p0-p1/geo-viz-engine
PP="$ENGINE"
for pkg in "$ENGINE"/packages/*/; do
    PP="$PP:${pkg%/}"
done
PP="$PP:/home/kevin/projects/paleo-p0-p1/well-log-engine"

cd /home/kevin/projects/paleo-p0-p1 || exit 2

if [[ "${1:-}" == "--python" ]]; then
    shift
    exec env -i \
        HOME="$HOME" TERM="${TERM:-xterm}" LANG="${LANG:-zh_CN.UTF-8}" \
        PATH="/opt/miniconda3/bin:/usr/bin:/bin" \
        QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
        LD_PRELOAD=/home/kevin/projects/paleo_project/round2-notes/libxmlshim.so \
        PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
        PYTHONPATH="$PP" \
        /opt/miniconda3/bin/python3.13 "$@"
fi

exec env -i \
    HOME="$HOME" TERM="${TERM:-xterm}" LANG="${LANG:-zh_CN.UTF-8}" \
    PATH="/opt/miniconda3/bin:/usr/bin:/bin" \
    QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
    LD_PRELOAD=/home/kevin/projects/paleo_project/round2-notes/libxmlshim.so \
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    PYTHONPATH="$PP" \
    /opt/miniconda3/bin/python3.13 -m pytest -p no:randomly -q "$@"
