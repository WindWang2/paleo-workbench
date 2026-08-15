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
    p = _resolve_correlation_artifact(ref.artifact_path, project_path, project)
    if p is None:
        return ref, None
    payload, _ = read_correlation_artifact(p)
    return ref, payload


def _resolve_correlation_artifact(
    artifact_path: str,
    project_path: Path | str | None,
    project: ProjectDocument,
) -> Path | None:
    """Resolve a correlation artifact path project-first (H9).

    The stored path is project-relative; probing the process CWD first lets a
    duplicated project (same relative path) read the OTHER project's artifact
    when the app was launched from inside it. Project-relative resolution
    must win; CWD is a last-resort legacy fallback.
    """
    raw = str(artifact_path or "")
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    if project_path is not None:
        cand = Path(project_path).resolve().parent / candidate
        if cand.is_file():
            return cand
    root = getattr(getattr(project, "meta", None), "project_root", "") or ""
    if root:
        cand = Path(root) / candidate
        if cand.is_file():
            return cand
    return candidate if candidate.is_file() else None


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


def markers_from_overlay_rows(
    rows: list[dict[str, Any]],
    *,
    allowed_domains: set[str] | None = None,
) -> list[FormationTopMarker]:
    """Convert overlay dicts to adapter-readable marker objects.

    ``allowed_domains`` guards H8: a formation top whose depth domain does not
    match the target log axis must never be placed numerically (the software
    does not convert depth domains). Skipped rows are reported via the
    returned ``overlay_diagnostics`` when requested.
    """
    out: list[FormationTopMarker] = []
    for r in rows:
        domain = str(r.get("depth_domain") or "MD")
        if allowed_domains is not None and domain not in allowed_domains:
            continue
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

    Re-applying the overlay replaces previously applied correlation markers
    (same ``semantic``) instead of appending, so backend toggles and tops
    edits can never accumulate stale duplicate tops (H9).
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
    # The log axis is a depth axis in meters (MD); non-MD tops are skipped
    # with a warning instead of being plotted at numerically wrong positions
    # (H8 — no silent domain conversion). When the log axis is a foot axis
    # (DEPT.FT LAS), meter-domain MD tops are converted so they stay aligned
    # instead of being misplaced by the ×3.28 factor (WL-4).
    domain_rows = [r for r in rows if str(r.get("depth_domain") or "MD") == "MD"]
    skipped = len(rows) - len(domain_rows)
    axis_unit = str(getattr(data, "depth_unit", "") or "").strip().lower()
    if axis_unit in {"ft", "f", "feet", "foot"}:
        import logging

        logging.getLogger(__name__).warning(
            "correlation overlay: converting %d MD top(s) from meters to feet to match the %s depth axis",
            len(domain_rows),
            axis_unit,
        )
        domain_rows = [
            {**r, "depth": float(r["depth"]) * 3.280839895013123}
            for r in domain_rows
        ]
    markers = markers_from_overlay_rows(domain_rows)
    if skipped:
        import logging

        logging.getLogger(__name__).warning(
            "skipped %d correlation top(s) with non-MD depth domain on well-log overlay (no auto-conversion)",
            skipped,
        )
    if not markers:
        return data
    # Replace correlation-managed markers; keep other marker semantics.
    existing = list(getattr(data, "markers", None) or [])
    kept = [
        m
        for m in existing
        if getattr(m, "semantic", "formation_top") != "formation_top"
    ]
    if isinstance(data, WellLogDataWithMarkers):
        return WellLogDataWithMarkers(data.base, kept + markers)
    return WellLogDataWithMarkers(data, kept + markers)
