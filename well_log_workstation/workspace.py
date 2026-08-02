"""Directory workspace + workspace.json catalog (decision F / #213 / #217).

Engine Manifest is per-well data only — never the whole-project container.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

WORKSPACE_FILENAME = "workspace.json"
WELLS_DIRNAME = "wells"
PLOTS_DIRNAME = "plots"
TEMPLATES_DIRNAME = "templates"
SCHEMA_VERSION = 1

PlotType = Literal["single_well", "correlation"]


@dataclass
class WellCatalogEntry:
    id: str
    name: str
    # Relative to workspace root (posix-style preferred in JSON).
    path: str = ""


@dataclass
class PlotCatalogEntry:
    id: str
    name: str
    type: PlotType = "single_well"
    well_ids: list[str] = field(default_factory=list)
    template_id: str | None = None
    # Relative path under plots/ for future metadata file (#220).
    path: str = ""


@dataclass
class Workspace:
    """In-memory catalog bound to a filesystem root."""

    root: Path
    name: str
    wells: list[WellCatalogEntry] = field(default_factory=list)
    plots: list[PlotCatalogEntry] = field(default_factory=list)
    default_template_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def wells_dir(self) -> Path:
        return self.root / WELLS_DIRNAME

    @property
    def plots_dir(self) -> Path:
        return self.root / PLOTS_DIRNAME

    @property
    def templates_dir(self) -> Path:
        return self.root / TEMPLATES_DIRNAME

    @property
    def catalog_path(self) -> Path:
        return self.root / WORKSPACE_FILENAME


class WorkspaceError(Exception):
    """User-facing workspace I/O or validation error."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _to_json_dict(ws: Workspace) -> dict[str, Any]:
    return {
        "schemaVersion": ws.schema_version,
        "name": ws.name,
        "defaultTemplateId": ws.default_template_id,
        "wells": [asdict(w) for w in ws.wells],
        "plots": [asdict(p) for p in ws.plots],
    }


def _from_json_dict(root: Path, data: dict[str, Any]) -> Workspace:
    version = int(data.get("schemaVersion", 0))
    if version != SCHEMA_VERSION:
        raise WorkspaceError(
            f"unsupported workspace schemaVersion={version} "
            f"(expected {SCHEMA_VERSION})"
        )
    wells = [
        WellCatalogEntry(
            id=str(w["id"]),
            name=str(w.get("name") or w["id"]),
            path=str(w.get("path") or ""),
        )
        for w in data.get("wells") or []
    ]
    plots: list[PlotCatalogEntry] = []
    for p in data.get("plots") or []:
        ptype = str(p.get("type") or "single_well")
        if ptype not in ("single_well", "correlation"):
            ptype = "single_well"
        plots.append(
            PlotCatalogEntry(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                type=ptype,  # type: ignore[arg-type]
                well_ids=[str(x) for x in (p.get("well_ids") or [])],
                template_id=p.get("template_id"),
                path=str(p.get("path") or ""),
            )
        )
    return Workspace(
        root=root.resolve(),
        name=str(data.get("name") or root.name),
        wells=wells,
        plots=plots,
        default_template_id=data.get("defaultTemplateId"),
        schema_version=version,
    )


def create_workspace(path: Path | str, *, name: str | None = None) -> Workspace:
    """Create skeleton directories and an empty ``workspace.json``."""
    root = Path(path).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        # Allow empty dir; reject non-empty without catalog to avoid clobber.
        if (root / WORKSPACE_FILENAME).exists():
            raise WorkspaceError(f"workspace already exists: {root}")
        # non-empty without catalog
        raise WorkspaceError(f"directory is not empty: {root}")

    root.mkdir(parents=True, exist_ok=True)
    (root / WELLS_DIRNAME).mkdir(exist_ok=True)
    (root / PLOTS_DIRNAME).mkdir(exist_ok=True)
    (root / TEMPLATES_DIRNAME).mkdir(exist_ok=True)

    ws = Workspace(root=root, name=name or root.name)
    save_workspace(ws)
    return ws


def open_workspace(path: Path | str) -> Workspace:
    """Load catalog from an existing workspace directory."""
    root = Path(path).expanduser().resolve()
    catalog = root / WORKSPACE_FILENAME
    if not catalog.is_file():
        raise WorkspaceError(f"not a workspace (missing {WORKSPACE_FILENAME}): {root}")
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"failed to read catalog: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("workspace.json root must be an object")
    ws = _from_json_dict(root, data)
    # Ensure skeleton dirs exist (tolerant open).
    ws.wells_dir.mkdir(exist_ok=True)
    ws.plots_dir.mkdir(exist_ok=True)
    ws.templates_dir.mkdir(exist_ok=True)
    return ws


def save_workspace(ws: Workspace) -> None:
    """Write ``workspace.json`` atomically-ish (write temp then replace)."""
    ws.root.mkdir(parents=True, exist_ok=True)
    path = ws.catalog_path
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(_to_json_dict(ws), indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def add_well(
    ws: Workspace,
    *,
    name: str,
    path: str = "",
    well_id: str | None = None,
) -> WellCatalogEntry:
    """Append a well catalog entry and persist."""
    entry = WellCatalogEntry(id=well_id or _new_id(), name=name, path=path)
    ws.wells.append(entry)
    save_workspace(ws)
    return entry


def add_plot(
    ws: Workspace,
    *,
    name: str,
    plot_type: PlotType = "single_well",
    well_ids: list[str] | None = None,
    template_id: str | None = None,
    path: str = "",
    plot_id: str | None = None,
) -> PlotCatalogEntry:
    """Append a plot catalog entry and persist."""
    entry = PlotCatalogEntry(
        id=plot_id or _new_id(),
        name=name,
        type=plot_type,
        well_ids=list(well_ids or []),
        template_id=template_id,
        path=path,
    )
    ws.plots.append(entry)
    save_workspace(ws)
    return entry
