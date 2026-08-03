"""Single-well / correlation plot documents under ``plots/`` (#220).

Host metadata only; multi-track layout still comes from template apply (H).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from well_log_workstation.correlation_links import HorizonLink
from well_log_workstation.workspace import (
    PlotCatalogEntry,
    Workspace,
    WorkspaceError,
    add_plot,
    save_workspace,
)

PLOT_SCHEMA_VERSION = 1
PlotType = Literal["single_well", "correlation"]


@dataclass
class PlotDocument:
    id: str
    name: str
    type: PlotType
    well_ids: list[str]
    template_id: str | None
    # Relative path from workspace root
    path: str
    # Correlation horizon links (#229); empty for single-well
    links: list[HorizonLink] = field(default_factory=list)

    def absolute_path(self, workspace: Workspace) -> Path:
        return workspace.root / self.path


def _plot_rel_path(plot_id: str) -> str:
    return f"plots/{plot_id}.json"


def _to_json(doc: PlotDocument) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": PLOT_SCHEMA_VERSION,
        "id": doc.id,
        "name": doc.name,
        "type": doc.type,
        "well_ids": list(doc.well_ids),
        "template_id": doc.template_id,
    }
    # Always persist links for correlation docs so clear/remove is durable (#230)
    if doc.type == "correlation" or doc.links:
        payload["links"] = [lk.to_json() for lk in doc.links]
    return payload


def _from_json(data: dict[str, Any], *, path: str) -> PlotDocument:
    version = int(data.get("schemaVersion", 0))
    if version != PLOT_SCHEMA_VERSION:
        raise WorkspaceError(
            f"unsupported plot schemaVersion={version} "
            f"(expected {PLOT_SCHEMA_VERSION})"
        )
    ptype = str(data.get("type") or "single_well")
    if ptype not in ("single_well", "correlation"):
        ptype = "single_well"
    links: list[HorizonLink] = []
    for raw in data.get("links") or []:
        if isinstance(raw, dict):
            link = HorizonLink.from_json(raw)
            if link is not None:
                links.append(link)
    return PlotDocument(
        id=str(data["id"]),
        name=str(data.get("name") or data["id"]),
        type=ptype,  # type: ignore[arg-type]
        well_ids=[str(x) for x in (data.get("well_ids") or [])],
        template_id=data.get("template_id"),
        path=path,
        links=links,
    )


def save_plot_document(workspace: Workspace, doc: PlotDocument) -> None:
    """Write plots/<id>.json and ensure catalog entry matches."""
    workspace.plots_dir.mkdir(parents=True, exist_ok=True)
    rel = doc.path or _plot_rel_path(doc.id)
    doc.path = rel
    abs_path = workspace.root / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = abs_path.with_suffix(".json.tmp")
    payload = json.dumps(_to_json(doc), indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(abs_path)

    # Upsert catalog
    existing = next((p for p in workspace.plots if p.id == doc.id), None)
    if existing is None:
        add_plot(
            workspace,
            name=doc.name,
            plot_type=doc.type,
            well_ids=doc.well_ids,
            template_id=doc.template_id,
            path=rel,
            plot_id=doc.id,
        )
    else:
        existing.name = doc.name
        existing.type = doc.type
        existing.well_ids = list(doc.well_ids)
        existing.template_id = doc.template_id
        existing.path = rel
        save_workspace(workspace)


def load_plot_document(workspace: Workspace, plot_id: str) -> PlotDocument:
    """Load plot metadata from disk (catalog path or default plots/<id>.json)."""
    entry = next((p for p in workspace.plots if p.id == plot_id), None)
    rel = entry.path if entry and entry.path else _plot_rel_path(plot_id)
    abs_path = workspace.root / rel
    if not abs_path.is_file():
        raise WorkspaceError(f"图件文件不存在: {rel}")
    try:
        data = json.loads(abs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"无法读取图件: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("图件 JSON 根必须是对象")
    doc = _from_json(data, path=rel)
    if doc.id != plot_id and entry is not None:
        # Prefer catalog id if file was renamed oddly
        doc = PlotDocument(
            id=plot_id,
            name=doc.name,
            type=doc.type,
            well_ids=doc.well_ids,
            template_id=doc.template_id,
            path=rel,
            links=list(doc.links),
        )
    return doc


def create_single_well_plot(
    workspace: Workspace,
    *,
    well_id: str,
    well_name: str,
    template_id: str,
    name: str | None = None,
    plot_id: str | None = None,
) -> PlotDocument:
    """Create and persist a 单井分析图 document (multi-track template binding)."""
    if not any(w.id == well_id for w in workspace.wells):
        raise WorkspaceError("井不在工区目录中")
    pid = plot_id or str(uuid.uuid4())
    doc = PlotDocument(
        id=pid,
        name=name or f"{well_name} 单井分析图",
        type="single_well",
        well_ids=[well_id],
        template_id=template_id,
        path=_plot_rel_path(pid),
    )
    save_plot_document(workspace, doc)
    return doc


def create_correlation_plot(
    workspace: Workspace,
    *,
    well_ids: list[str],
    template_id: str,
    name: str | None = None,
    plot_id: str | None = None,
) -> PlotDocument:
    """Create and persist a 地层对比图-lite document (≥2 wells)."""
    if len(well_ids) < 2:
        raise WorkspaceError("地层对比至少需要 2 口井")
    catalog_ids = {w.id for w in workspace.wells}
    for wid in well_ids:
        if wid not in catalog_ids:
            raise WorkspaceError(f"井不在工区目录中: {wid}")
    names = []
    for wid in well_ids:
        entry = next(w for w in workspace.wells if w.id == wid)
        names.append(entry.name)
    pid = plot_id or str(uuid.uuid4())
    label = name or f"{'–'.join(names[:3])} 地层对比"
    doc = PlotDocument(
        id=pid,
        name=label,
        type="correlation",
        well_ids=list(well_ids),
        template_id=template_id,
        path=_plot_rel_path(pid),
    )
    save_plot_document(workspace, doc)
    return doc


def find_plot_entry(workspace: Workspace, plot_id: str) -> PlotCatalogEntry | None:
    return next((p for p in workspace.plots if p.id == plot_id), None)
