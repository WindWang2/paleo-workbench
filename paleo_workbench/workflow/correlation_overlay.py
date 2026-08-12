"""Load correlation interpretation tops for well-log / section overlays (Stage 12).

Maps tops into objects that ``welllog_engine_adapter.adapt_well_log_data`` reads
via ``data.markers`` (depth + label/name). Real ``geoviz.WellLogData`` rejects
unknown setattr fields, so we wrap it rather than mutating pydantic models.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.correlation_artifact import read_correlation_artifact
from paleo_workbench.workflow.correlation_session import tops_overlay_for_well


@dataclass(frozen=True)
class FormationTopMarker:
    """Marker shape accepted by ``_append_markers`` / adapt_well_log_data."""

    id: str
    depth: float
    label: str
    semantic: str = "formation_top"

    @property
    def name(self) -> str:
        return self.label

    @property
    def reference_depth(self) -> float:
        return self.depth


class WellLogDataWithMarkers:
    """Duck-type wrapper: proxies WellLogData attributes + exposes ``markers``.

    Used so production ``adapt_well_log_data`` and multi-well adapters pick up
    correlation tops without requiring a WellLogData schema change.
    """

    __slots__ = ("_base", "markers")

    def __init__(self, base: Any, markers: list[FormationTopMarker] | None = None) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "markers", list(markers or []))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    @property
    def base(self) -> Any:
        return self._base


def current_correlation_ref(project: ProjectDocument):
    refs = list(getattr(project, "correlation_interpretations", None) or [])
    if not refs:
        return None
    for ref in reversed(refs):
        if getattr(ref, "current_version_id", None):
            return ref
    return refs[-1]


def load_current_correlation_payload(
    project: ProjectDocument,
    project_path: Path | str | None = None,
):
    """Load scientific payload of the selected correlation interpretation."""
    ref = current_correlation_ref(project)
    if ref is None or not ref.artifact_path:
        return None, None
    p = Path(ref.artifact_path)
    if not p.is_file() and project_path is not None:
        p = Path(project_path).resolve().parent / ref.artifact_path
    if not p.is_file():
        root = getattr(getattr(project, "meta", None), "project_root", "") or ""
        if root:
            cand = Path(root) / ref.artifact_path
            if cand.is_file():
                p = cand
    if not p.is_file():
        return ref, None
    payload, _ = read_correlation_artifact(p)
    return ref, payload


def formation_tops_overlay_for_well(
    project: ProjectDocument,
    *,
    well_id: str = "",
    well_name: str = "",
    project_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Overlay rows from current correlation version for one well."""
    _ref, payload = load_current_correlation_payload(project, project_path)
    if payload is None:
        return []
    return tops_overlay_for_well(
        payload.tops, well_id=well_id, well_name=well_name
    )


def markers_from_overlay_rows(rows: list[dict[str, Any]]) -> list[FormationTopMarker]:
    """Convert overlay dicts to adapter-readable marker objects."""
    out: list[FormationTopMarker] = []
    for r in rows:
        try:
            depth = float(r.get("depth"))
        except (TypeError, ValueError):
            continue
        if depth != depth:  # NaN
            continue
        out.append(
            FormationTopMarker(
                id=str(r.get("id") or ""),
                depth=depth,
                label=str(r.get("marker") or r.get("label") or ""),
                semantic="formation_top",
            )
        )
    return out


def apply_correlation_tops_to_well_log_data(
    data: Any,
    project: ProjectDocument,
    *,
    well_id: str = "",
    well_name: str = "",
    project_path: Path | str | None = None,
) -> Any:
    """Return data (possibly wrapped) with correlation tops as ``markers``.

    Does not mutate RAW LAS / WellLogData schema. If no tops, returns *data*
    unchanged. Production consumers must pass the return value into
    ``adapt_well_log_data`` / host apply paths.
    """
    if data is None:
        return data
    name = well_name or str(getattr(data, "well_name", "") or "")
    rows = formation_tops_overlay_for_well(
        project,
        well_id=well_id,
        well_name=name,
        project_path=project_path,
    )
    if not rows:
        return data
    markers = markers_from_overlay_rows(rows)
    if not markers:
        return data
    # Merge with any existing markers on a prior wrapper or duck type
    existing = list(getattr(data, "markers", None) or [])
    if isinstance(data, WellLogDataWithMarkers):
        return WellLogDataWithMarkers(data.base, existing + markers)
    return WellLogDataWithMarkers(data, existing + markers)
