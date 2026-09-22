"""QGIS runtime discovery / loading / health — the single authority (V10 M-A).

Historically the vendored-QGIS runtime location was resolved in five places
with three different default roots (``mapping/qgis_style.py``,
``tests/conftest.py``, ``scripts/run_qgis_env.py``, docs, and machine muscle
memory), and nothing ever verified that PROJ could actually resolve a CRS —
which is how ``canvas_destination_crs() == ""`` became a documented V9
"recipe constraint" instead of a diagnosed runtime failure.

This package owns, in one place:

* **paths** (:mod:`.paths`) — vendor root / deps prefix / PySide6 dir
  discovery (``PALEO_QGIS_BUILD_DIR``, ``PALEO_QGIS_DEPS_DIR`` first).
* **loader** (:mod:`.loader`) — the two Windows load recipes (default
  self-contained vendor vs. ``PALEO_QGIS_CONDA_QT=1`` conda unification)
  plus the Linux protobuf symlink + MSVCP pre-pin, all idempotent, with a
  :class:`~.loader.LoadReport` instead of silent half-preparation.
* **proj_data** (:mod:`.proj_data`) — proj.db discovery and (best-effort,
  loudly logged) provisioning so the vendored ``proj_9.dll`` can resolve
  CRSs without a process-wide ``PROJ_DATA`` env var (ADR 0060 forbids the
  env var: rasterio's bundled libproj would read an incompatible proj.db).
* **health** (:mod:`.health`) — :class:`~.health.QgisRuntimeStatus`, a
  structured probe covering QGIS/PROJ/GDAL versions, providers, CRS
  resolution, transform, and bridge manifest; consumers (UI, ToolContext)
  read this instead of ``try: import qgis_render_bridge``.

Nothing in this package fabricates capability: every unavailable probe is
reported with a reason, never silently defaulted to "fine".
"""

from __future__ import annotations

from paleo_workbench.qgis_runtime.health import (
    QgisRuntimeStatus,
    probe_qgis_runtime,
    reset_runtime_probe_cache,
)
from paleo_workbench.qgis_runtime.loader import (
    LoadRecipe,
    LoadReport,
    prepare_bridge_load,
    resolve_recipe,
)
from paleo_workbench.qgis_runtime.paths import QgisRuntimePaths, resolve_runtime_paths
from paleo_workbench.qgis_runtime.proj_data import (
    ProjDataReport,
    ensure_proj_data,
    locate_proj_db,
)

__all__ = [
    "LoadRecipe",
    "LoadReport",
    "prepare_bridge_load",
    "resolve_recipe",
    "ProjDataReport",
    "QgisRuntimePaths",
    "QgisRuntimeStatus",
    "locate_proj_db",
    "ensure_proj_data",
    "probe_qgis_runtime",
    "reset_runtime_probe_cache",
    "resolve_runtime_paths",
]
