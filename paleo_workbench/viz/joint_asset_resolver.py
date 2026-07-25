"""Hybrid asset path resolver for the well–seismic joint page (#59 / wayfinder #67)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem


@dataclass
class JointAssetPaths:
    """Filesystem paths resolved for joint scene load."""

    segy: Path | None = None
    well_head: Path | None = None
    td_dir: Path | None = None
    tops: Path | None = None
    horizons: list[Path] = field(default_factory=list)
    las_files: list[Path] = field(default_factory=list)
    source: str = ""  # "project" | "data" | "mixed" | "empty"
    warnings: list[str] = field(default_factory=list)

    def has_minimum(self) -> bool:
        """Need at least SEGY or wells to attempt a useful scene."""
        return self.segy is not None or self.well_head is not None


def resolve_joint_assets(
    project: ProjectDocument | None,
    *,
    data_root: Path | None = None,
    repo_root: Path | None = None,
) -> JointAssetPaths:
    """Hybrid: project.resources → data/ fallback (wayfinder D)."""
    result = JointAssetPaths()
    from_project = _from_project(project) if project is not None else JointAssetPaths()
    root = data_root
    if root is None and repo_root is not None:
        candidate = repo_root / "data"
        root = candidate if candidate.is_dir() else None
    from_data = _from_data_layout(root) if root is not None else JointAssetPaths()

    result.segy = from_project.segy or from_data.segy
    result.well_head = from_project.well_head or from_data.well_head
    result.td_dir = from_project.td_dir or from_data.td_dir
    result.tops = from_project.tops or from_data.tops
    result.horizons = from_project.horizons or from_data.horizons
    result.las_files = from_project.las_files or from_data.las_files

    # Optional path_hints from joint_analysis persistence (code-review Spec fix)
    if project is not None:
        state = getattr(project, "joint_analysis", None)
        hints = dict(getattr(state, "path_hints", None) or {})
        for key, attr in (
            ("segy", "segy"),
            ("well_head", "well_head"),
            ("td_dir", "td_dir"),
            ("tops", "tops"),
        ):
            raw = hints.get(key)
            if not raw:
                continue
            p = Path(raw)
            if p.exists():
                setattr(result, attr, p)
        if hints.get("horizons"):
            hp = Path(hints["horizons"])
            if hp.exists():
                result.horizons = [hp] if hp.is_file() else list(hp.glob("*.dat"))[:20]

    used_p = any(
        [
            from_project.segy,
            from_project.well_head,
            from_project.td_dir,
            from_project.tops,
            from_project.horizons,
            from_project.las_files,
        ]
    )
    used_d = any(
        [
            from_data.segy,
            from_data.well_head,
            from_data.td_dir,
            from_data.tops,
            from_data.horizons,
            from_data.las_files,
        ]
    )
    if used_p and used_d:
        result.source = "mixed"
    elif used_p:
        result.source = "project"
    elif used_d:
        result.source = "data"
    else:
        result.source = "empty"
        result.warnings.append("未找到 SEGY / 井位等联合分析资产")
    return result


def _from_project(project: ProjectDocument) -> JointAssetPaths:
    out = JointAssetPaths(source="project")
    resources = list(getattr(project, "resources", None) or [])
    for res in resources:
        if not isinstance(res, ResourceItem):
            continue
        path = Path(res.path)
        if not path.exists():
            continue
        rtype = (res.type or "").lower()
        fmt = (res.format or path.suffix.lower().lstrip(".")).lower()
        name = (res.name or path.name).lower()
        if fmt in {"sgy", "segy"} or rtype in {"seismic", "segy"}:
            if out.segy is None:
                out.segy = path
        elif rtype in {"well_head", "wellhead"} or "wellhead" in name or "井位" in str(path):
            if out.well_head is None:
                out.well_head = path
        elif "td" in name or "时深" in str(path) or rtype in {"time_depth", "td"}:
            if path.is_dir() and out.td_dir is None:
                out.td_dir = path
            elif path.is_file() and out.td_dir is None:
                out.td_dir = path.parent
        elif rtype in {"horizon", "layer"} or fmt == "dat" and "层位" in str(path):
            out.horizons.append(path)
        elif fmt == "las" or rtype in {"well_log", "las"}:
            out.las_files.append(path)
        elif "tops" in name or "分层" in str(path) or rtype in {"well_tops", "tops"}:
            if out.tops is None:
                out.tops = path
    return out


def _from_data_layout(data_root: Path) -> JointAssetPaths:
    out = JointAssetPaths(source="data")
    if not data_root.is_dir():
        return out
    # SEGY
    seismic_dir = data_root / "地震体"
    if seismic_dir.is_dir():
        for p in sorted(seismic_dir.glob("*.sgy")) + sorted(seismic_dir.glob("*.segy")):
            out.segy = p
            break
    # Well head
    wh = data_root / "井位" / "ExportWellHead.dat"
    if wh.is_file():
        out.well_head = wh
    # TD
    td = data_root / "时深" / "TD"
    if td.is_dir():
        out.td_dir = td
    # Tops
    tops = data_root / "井分层" / "DC.dat"
    if tops.is_file():
        out.tops = tops
    # Horizons
    hz = data_root / "层位"
    if hz.is_dir():
        out.horizons = sorted(hz.glob("*.dat"))
    # LAS
    las_dir = data_root / "井曲线"
    if las_dir.is_dir():
        out.las_files = sorted(las_dir.glob("*.[Ll][Aa][Ss]"))
    return out
