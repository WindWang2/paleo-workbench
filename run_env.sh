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
# Native extension sources/built artifacts: map_edit_core lives in the
# geo-viz-engine submodule (built in place by this worktree); the rest live
# in native/ with the MAIN worktree's built .so files (this environment's pip
# editable installs point at stale worktree paths, so the live artifacts go
# on the path explicitly). The welllog binding comes from the engine build.
MAIN=/home/kevin/projects/paleo_project/main
PP="$PP:/home/kevin/projects/paleo-p0-p1/geo-viz-engine/native/map_edit_core/src"
for native_pkg in well_log_core grid_render_core layer_model_core seismic_3d_core; do
    PP="$PP:$MAIN/native/$native_pkg/src"
done
PP="$PP:$MAIN/well-log-engine/build/dev-python/python"

cd /home/kevin/projects/paleo-p0-p1 || exit 2

if [[ "${1:-}" == "--python" ]]; then
    shift
    exec env -i \
        HOME="$HOME" TERM="${TERM:-xterm}" LANG="${LANG:-zh_CN.UTF-8}" \
        PATH="/opt/miniconda3/bin:/usr/bin:/bin" \
        QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
        LD_PRELOAD="/usr/lib/libstdc++.so.6:/home/kevin/projects/paleo_project/round2-notes/libxmlshim.so" \
        PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
        PYTHONPATH="$PP" \
        /opt/miniconda3/bin/python3.13 "$@"
fi

exec env -i \
    HOME="$HOME" TERM="${TERM:-xterm}" LANG="${LANG:-zh_CN.UTF-8}" \
    PATH="/opt/miniconda3/bin:/usr/bin:/bin" \
    QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
    LD_PRELOAD="/usr/lib/libstdc++.so.6:/home/kevin/projects/paleo_project/round2-notes/libxmlshim.so" \
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    PYTHONPATH="$PP" \
    /opt/miniconda3/bin/python3.13 -m pytest -p no:randomly -q "$@"
