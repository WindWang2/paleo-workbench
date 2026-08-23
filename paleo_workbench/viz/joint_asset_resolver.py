"""Hybrid asset path resolver for the well–seismic joint page (#59 / wayfinder #67)."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from paleo_workbench.project.paths import is_within_directory
from paleo_workbench.project.models import ProjectDocument, ResourceItem


@dataclass
class JointAssetPaths:
    """Filesystem paths resolved for joint scene load."""

    segy: Path | None = None
    well_head: Path | None = None
    well_head_asset_id: str | None = None
    td_dir: Path | None = None
    tops: Path | None = None
    horizons: list[Path] = field(default_factory=list)
    las_files: list[Path] = field(default_factory=list)
    source: str = ""  # "project" | "data" | "mixed" | "empty"
    warnings: list[str] = field(default_factory=list)

    def has_minimum(self) -> bool:
        """Need at least SEGY or wells to attempt a useful scene."""
        return self.segy is not None or self.well_head is not None


def _resolve_resource_path(path: Path, project: ProjectDocument) -> Path:
    """Resolve a resource path against the project root when it is relative.

    Saved projects store project-relative paths; checking them against the
    process CWD silently dropped every joint asset after reopen. Absolute
    paths pass through unchanged; relative joins are confined to the project
    root (no ``..`` escape).
    """
    if path.is_absolute() or path.exists():
        return path
    root = str(getattr(getattr(project, "meta", None), "project_root", "") or "").strip()
    if not root or root in {".", ".."}:
        return path
    root_path = Path(root).expanduser().resolve()
    joined = (root_path / path).resolve()
    if not is_within_directory(joined, root_path):
        return path  # escape attempt — do not open files outside the project root
    return joined


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
    result.well_head_asset_id = (
        from_project.well_head_asset_id or from_data.well_head_asset_id
    )
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
                previous_path = getattr(result, attr)
                setattr(result, attr, p)
                if key == "well_head" and (
                    previous_path is None
                    or previous_path.resolve() != p.resolve()
                ):
                    result.well_head_asset_id = _path_asset_id(p)
        if hints.get("horizons"):
            raw_h = hints["horizons"]
            # Support single path or pipe-separated multi-horizon list
            candidates = [Path(p.strip()) for p in str(raw_h).split("|") if p.strip()]
            found = [p for p in candidates if p.exists()]
            if found:
                result.horizons = found
            else:
                hp = Path(raw_h)
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
        path = _resolve_resource_path(Path(res.path), project)
        if not path.exists():
            continue
        rtype = (res.type or "").lower()
        fmt = (res.format or path.suffix.lower().lstrip(".")).lower()
        name = (res.name or path.name).lower()
        # Declared type / file format win over path-substring heuristics so
        # names like STD-1.las or files under a 井位/ folder keep their slot.
        is_segy = fmt in {"sgy", "segy"} or rtype in {"seismic", "segy"}
        is_las = fmt == "las" or rtype in {"well_log", "las"}
        is_well_head = rtype in {"well_head", "wellhead"}
        is_td = rtype in {"time_depth", "td"}
        is_horizon = rtype in {"horizon", "layer"}
        is_tops = rtype in {"well_tops", "tops"}
        if not any((is_segy, is_las, is_well_head, is_td, is_horizon, is_tops)):
            if "wellhead" in name or (
                path.parent.name == "井位" and fmt in {"dat", "csv", "txt", "xlsx", "xls"}
            ):
                is_well_head = True
            elif name == "td" or name.startswith("td.") or "时深" in str(path):
                is_td = True
            elif fmt == "dat" and "层位" in str(path):
                is_horizon = True
            elif "tops" in name or "分层" in str(path):
                is_tops = True
        if is_segy:
            if out.segy is None:
                out.segy = path
        elif is_well_head:
            if out.well_head is None:
                out.well_head = path
                out.well_head_asset_id = res.id
        elif is_td:
            if path.is_dir() and out.td_dir is None:
                out.td_dir = path
            elif path.is_file() and out.td_dir is None:
                out.td_dir = path.parent
        elif is_horizon:
            out.horizons.append(path)
        elif is_las:
            out.las_files.append(path)
        elif is_tops:
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
        out.well_head_asset_id = "demo:well-head"
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


def _path_asset_id(path: Path) -> str:
    digest = sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]
    return f"path:{digest}"
