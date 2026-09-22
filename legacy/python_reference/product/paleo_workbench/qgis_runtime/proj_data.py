"""proj.db discovery + provisioning for the vendored PROJ (V10 M-A).

Root cause of the V9 ``canvas_destination_crs() == ""`` limitation: the
self-contained vendor bin carries ``proj_9.dll`` but NO proj.db anywhere on
its search path, so every ``QgsCoordinateReferenceSystem`` resolves invalid
— silently. PROJ's search order is: ``PROJ_DATA``/``PROJ_LIB`` env →
``<dll-dir>/../share/proj`` (relative to the library itself) → compiled-in
prefix.

ADR 0060 forbids exporting ``PROJ_DATA`` process-wide (rasterio's newer
bundled libproj would read the incompatible vendored proj.db). The compliant
channel is therefore the **relative** one: deploy proj.db into the vendor's
``output/share/proj/`` so the vendored ``proj_9.dll`` finds it next to
itself, with no env var and no effect on any other libproj in the process.

The conda recipe needs nothing: its ``proj_9.dll`` lives in
``<deps>/Library/bin`` and finds ``<deps>/Library/share/proj/proj.db``
relative to itself already.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from paleo_workbench.qgis_runtime.loader import LoadRecipe
from paleo_workbench.qgis_runtime.paths import QgisRuntimePaths

logger = logging.getLogger(__name__)

_PROVISION_DISABLE_VAR = "PALEO_QGIS_PROVISION_PROJ"


@dataclass(frozen=True)
class ProjDataReport:
    proj_db: Path | None
    source: str  # "env" | "vendor-relative" | "deps" | "deployed" | ""
    deployed: bool = False
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.proj_db is not None


def _proj_db_in(directory: Path) -> Path | None:
    candidate = directory / "proj.db"
    return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


def locate_proj_db(paths: QgisRuntimePaths) -> tuple[Path | None, str]:
    """Return (proj.db path, source) following PROJ's own search order."""
    for var in ("PROJ_DATA", "PROJ_LIB"):
        value = os.environ.get(var, "").strip()
        if value:
            found = _proj_db_in(Path(value))
            if found is not None:
                return found, f"env:{var}"
    if paths.vendor_proj_data is not None:
        found = _proj_db_in(paths.vendor_proj_data)
        if found is not None:
            return found, "vendor-relative"
    if paths.deps_proj_data is not None:
        found = _proj_db_in(paths.deps_proj_data)
        if found is not None:
            return found, "deps"
    return None, ""


def _deploy_into_vendor(source: Path, paths: QgisRuntimePaths) -> Path | None:
    target_dir = paths.vendor_proj_data
    if target_dir is None or paths.vendor_root is None:
        return None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "proj.db"
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
        return target
    except OSError as exc:
        logger.warning("proj.db 部署失败 %s → %s: %s", source, target_dir, exc)
        return None


def ensure_proj_data(
    paths: QgisRuntimePaths, *, recipe: LoadRecipe, allow_deploy: bool = True
) -> ProjDataReport:
    """Make sure the ACTIVE recipe's proj library can reach a proj.db.

    Order: already reachable → nothing to do. Conda recipe: deps-relative
    location is inherently reachable. Vendor recipe: deploy (copy) the deps
    proj.db into ``<vendor>/output/share/proj/`` when a source exists; the
    copy is idempotent and loudly logged. Provisioning can be disabled with
    ``PALEO_QGIS_PROVISION_PROJ=0``.
    """
    found, source = locate_proj_db(paths)
    if found is not None:
        if recipe is LoadRecipe.CONDA_QT or source.startswith("env:"):
            return ProjDataReport(found, source)
        if source == "vendor-relative":
            return ProjDataReport(found, source)
        # source == "deps" under the vendor recipe: the vendor's own
        # proj_9.dll will NOT find the deps copy (different relative root)
        # unless deployed.
    if (
        allow_deploy
        and os.environ.get(_PROVISION_DISABLE_VAR, "").strip().lower()
        not in {"0", "false", "no", "off"}
    ):
        deploy_source = found if found is not None else (
            paths.deps_proj_data / "proj.db" if paths.deps_proj_data is not None else None
        )
        if deploy_source is not None and paths.vendor_proj_data is not None:
            deployed = _deploy_into_vendor(deploy_source, paths)
            if deployed is not None:
                logger.warning(
                    "proj.db 已部署到 vendor 相对路径 %s（来源 %s）— vendored "
                    "proj_9.dll 现在可解析 CRS", deployed, deploy_source
                )
                return ProjDataReport(deployed, "deployed", deployed=True)
        return ProjDataReport(
            found, source if found is not None else "",
            note=(
                "proj.db 不可达且无法部署：vendor 配方需要 "
                "<vendor>/output/share/proj/proj.db（可从 conda deps 前缀 "
                "PALEO_QGIS_DEPS_DIR 复制），CRS 解析将失败"
                if found is None
                else "proj.db 只在 deps 前缀，vendor 配方无法读取且部署失败"
            ),
        )
    return ProjDataReport(found, source if found is not None else "", note="provisioning disabled")
