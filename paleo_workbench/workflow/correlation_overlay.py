"""Load correlation interpretation tops for well-log / section overlays (Stage 12)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.correlation_artifact import read_correlation_artifact
from paleo_workbench.workflow.correlation_session import tops_overlay_for_well


def current_correlation_ref(project: ProjectDocument):
    refs = list(getattr(project, "correlation_interpretations", None) or [])
    if not refs:
        return None
    # Prefer last with a current_version_id
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
    """Overlay rows from current correlation version for one well (metadata-sized)."""
    _ref, payload = load_current_correlation_payload(project, project_path)
    if payload is None:
        return []
    return tops_overlay_for_well(
        payload.tops, well_id=well_id, well_name=well_name
    )


def apply_correlation_tops_to_well_log_data(
    data: Any,
    project: ProjectDocument,
    *,
    well_id: str = "",
    well_name: str = "",
    project_path: Path | str | None = None,
) -> Any:
    """Attach ``correlation_tops`` list onto well-log data object if possible.

    Does not mutate RAW LAS; only adds a display/scientific overlay attribute.
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
    try:
        setattr(data, "correlation_tops", rows)
    except Exception:
        pass
    # Also mirror into formation-style intervals when empty facies path needs markers
    if rows and not getattr(data, "formation_tops", None):
        try:
            setattr(
                data,
                "formation_tops",
                [(r["marker"], float(r["depth"])) for r in rows],
            )
        except Exception:
            pass
    return data
