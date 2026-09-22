"""Real-data geological scene snapshot builder (explicit demo vs real mode).

Does not inject synthetic wells/faults into a real project. Missing assets are
reported as unavailable rather than fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.joint_asset_resolver import resolve_joint_assets
from paleo_workbench.env_bootstrap import _repo_root


@dataclass(frozen=True, slots=True)
class RealSceneLoadResult:
    """Narrow staged result for host-thread scene binding."""

    mode: str  # "real" | "demo" | "empty"
    generation: int
    source_id: str | None = None
    segy_path: str | None = None
    well_count: int = 0
    has_segy: bool = False
    has_wells: bool = False
    has_las: bool = False
    has_horizons: bool = False
    has_faults: bool = False
    warnings: tuple[str, ...] = ()
    asset_summary: dict[str, Any] = field(default_factory=dict)


def _well_head_count(path: Path | None) -> int:
    """Count well-head rows; 0 when the file is missing or unreadable."""
    if path is None:
        return 0
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(stripped.split()) >= 3:
            count += 1
    return count


def classify_project_mode(project: ProjectDocument | None) -> str:
    """Return ``real`` if minimum real assets exist, else ``empty`` (demo is explicit)."""
    if project is None:
        return "empty"
    paths = resolve_joint_assets(project, repo_root=_repo_root())
    if paths.segy is not None or paths.has_minimum():
        return "real"
    return "empty"


def build_real_scene_snapshot(
    project: ProjectDocument | None,
    *,
    generation: int = 0,
    allow_demo: bool = False,
) -> RealSceneLoadResult:
    """Inspect project assets and return a staged real/demo/empty classification.

    This does **not** load dense volumes — volume binding is owned by
    :class:`~paleo_workbench.viz.joint_host.WellSeismicJointHost`.
    """
    if project is None:
        return RealSceneLoadResult(mode="empty", generation=generation)

    paths = resolve_joint_assets(project, repo_root=_repo_root())
    warnings: list[str] = []
    has_segy = paths.segy is not None and Path(paths.segy).is_file()
    has_wells = paths.well_head is not None
    has_las = bool(paths.las_files)
    has_horizons = bool(paths.horizons)
    has_faults = False
    well_count = _well_head_count(paths.well_head) if has_wells else 0
    if has_wells and well_count <= 0:
        well_count = 1

    if not has_segy and not has_wells:
        if allow_demo:
            return RealSceneLoadResult(
                mode="demo",
                generation=generation,
                warnings=("无真实 SEGY/井数据；可使用显式演示模式",),
            )
        return RealSceneLoadResult(
            mode="empty",
            generation=generation,
            warnings=("缺少 SEGY 与井数据",),
        )

    if not has_segy:
        warnings.append("无 SEGY：三维体不可用")
    if not has_wells:
        warnings.append("无井数据")
    if not has_horizons:
        warnings.append("无层位数据（可选）")
    if not has_faults:
        warnings.append("无断层数据（可选）")

    source_id = None
    segy_path = str(paths.segy) if paths.segy is not None else None
    if segy_path:
        try:
            from paleo_workbench.viz.seismic_volume_source import source_id_for_path

            source_id = source_id_for_path(segy_path)
        except Exception:
            source_id = segy_path

    return RealSceneLoadResult(
        mode="real",
        generation=generation,
        source_id=source_id,
        segy_path=segy_path,
        well_count=int(well_count),
        has_segy=has_segy,
        has_wells=has_wells,
        has_las=bool(has_las),
        has_horizons=bool(has_horizons),
        has_faults=bool(has_faults),
        warnings=tuple(warnings),
        asset_summary={
            "source": getattr(paths, "source", "?"),
            "segy": segy_path,
        },
    )
