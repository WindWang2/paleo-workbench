"""Fault interpretation lifecycle: draft → immutable DERIVED → reopen (Stage 12).

Scientific authority is map-plane polylines (project CRS), not screen coords.
ConstraintLine role=break remains a separate factor constraint path.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from paleo_workbench.catalog import get_catalog, sha256_file_or_none
from paleo_workbench.project.models import (
    ConstraintLayers,
    FaultInterpretationRef,
    ProjectDocument,
)
from paleo_workbench.project.paths import artifact_dir_for
from paleo_workbench.workflow.correlation_artifact import (
    read_fault_artifact,
    scientific_fingerprint_fault,
    write_fault_artifact,
)
from paleo_workbench.workflow.stratigraphy_models import (
    FaultInterpretationDraft,
    FaultInterpretationPayload,
    FaultTrace,
)

_log = logging.getLogger("paleo_workbench.fault_interp")


def _id(prefix: str = "fault") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_fault_draft(
    *,
    name: str = "断层解释",
    traces: list[FaultTrace] | None = None,
    source_version_ids: list[str] | None = None,
    crs: str = "",
    interpretation_id: str | None = None,
    parent_version_id: str | None = None,
) -> FaultInterpretationDraft:
    iid = interpretation_id or _id()
    payload = FaultInterpretationPayload(
        interpretation_id=iid,
        name=name,
        traces=list(traces or []),
        source_version_ids=list(source_version_ids or []),
        parent_version_id=parent_version_id,
        crs=crs,
    )
    return FaultInterpretationDraft(
        interpretation_id=iid,
        name=name,
        payload=payload,
        dirty=True,
    )


def draft_from_constraint_layers(
    layers: ConstraintLayers,
    *,
    name: str = "断层约束",
    crs: str = "",
) -> FaultInterpretationDraft:
    """Lift break polylines into a scientific fault draft (copy, not mutate)."""
    traces: list[FaultTrace] = []
    for line in getattr(layers, "lines", None) or []:
        if getattr(line, "role", "") not in {"break", "fault"}:
            continue
        coords = list(getattr(line, "coordinates", None) or getattr(line, "points", None) or [])
        # ConstraintLine uses vertices as list of [x,y] in model
        poly = []
        for pt in coords:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                poly.append([float(pt[0]), float(pt[1])])
        if len(poly) < 2:
            continue
        traces.append(
            FaultTrace(
                name=getattr(line, "name", "") or "",
                polyline=poly,
                role="break" if getattr(line, "role", "") == "break" else "fault",
            )
        )
    return new_fault_draft(name=name, traces=traces, crs=crs)


def open_fault_draft_from_version(
    artifact_path: Path | str,
    *,
    interpretation_id: str | None = None,
) -> FaultInterpretationDraft:
    payload, _ = read_fault_artifact(artifact_path)
    iid = interpretation_id or payload.interpretation_id or _id()
    payload.interpretation_id = iid
    fp = scientific_fingerprint_fault(payload)
    return FaultInterpretationDraft(
        interpretation_id=iid,
        name=payload.name or "断层解释",
        payload=payload,
        dirty=False,
        last_saved_fingerprint=fp,
    )


def draft_fingerprint(draft: FaultInterpretationDraft) -> str:
    return scientific_fingerprint_fault(draft.payload)


def save_fault_draft(
    draft: FaultInterpretationDraft,
    project: ProjectDocument,
    project_path: Path | str,
    *,
    catalog=None,
    force_new_version: bool = False,
) -> tuple[FaultInterpretationRef | None, str]:
    path = Path(project_path)
    fp = draft_fingerprint(draft)
    existing = _find_ref(project, draft.interpretation_id)
    if not force_new_version and existing and existing.scientific_fingerprint == fp:
        draft.dirty = False
        draft.last_saved_fingerprint = fp
        return existing, "noop_unchanged"
    if not force_new_version and draft.last_saved_fingerprint == fp and existing:
        draft.dirty = False
        return existing, "noop_unchanged"

    parent = draft.payload.parent_version_id
    if existing and existing.current_version_id and not parent:
        parent = existing.current_version_id
        draft.payload.parent_version_id = parent

    fault_dir = artifact_dir_for(path) / "faults"
    version_token = _id("ver")
    artifact = write_fault_artifact(
        draft.payload,
        fault_dir,
        f"{draft.interpretation_id}_{version_token}",
    )
    checksum = sha256_file_or_none(artifact)

    from paleo_workbench.catalog.lifecycle import register_fault_interpretation_run

    _run, version = register_fault_interpretation_run(
        name=f"{draft.name} fault",
        path=artifact.as_posix(),
        checksum=checksum,
        source_version_ids=list(draft.payload.source_version_ids),
        parent_version_id=parent,
        scientific_fingerprint=fp,
        domain_task_id=draft.interpretation_id,
        catalog=catalog,
    )
    version_id = version.version_id if version is not None else version_token
    managed_path = version.path if version is not None else artifact.as_posix()
    try:
        rel = Path(managed_path).resolve().relative_to(path.resolve().parent)
        store_path = rel.as_posix()
    except ValueError:
        store_path = managed_path

    ref = FaultInterpretationRef(
        id=draft.interpretation_id,
        name=draft.name,
        current_version_id=version_id,
        artifact_path=store_path,
        parent_version_id=parent,
        status="clean",
        source_version_ids=list(draft.payload.source_version_ids),
        scientific_fingerprint=fp,
        crs=draft.payload.crs,
        display=dict(draft.display or {}),
    )
    _upsert_ref(project, ref)
    draft.dirty = False
    draft.last_saved_fingerprint = fp
    draft.payload.parent_version_id = version_id
    return ref, "ok"


def restore_fault_draft_from_project(
    project: ProjectDocument,
    project_path: Path | str,
    *,
    interpretation_id: str | None = None,
) -> FaultInterpretationDraft | None:
    refs = list(getattr(project, "fault_interpretations", None) or [])
    if not refs:
        return None
    ref = None
    if interpretation_id:
        for r in refs:
            if r.id == interpretation_id:
                ref = r
                break
    if ref is None:
        ref = refs[0]
    if not ref.artifact_path:
        return None
    p = Path(ref.artifact_path)
    if not p.is_file():
        p = Path(project_path).resolve().parent / ref.artifact_path
    draft = open_fault_draft_from_version(p, interpretation_id=ref.id)
    draft.payload.parent_version_id = ref.current_version_id
    draft.last_saved_fingerprint = ref.scientific_fingerprint or draft_fingerprint(draft)
    draft.dirty = False
    return draft


def _find_ref(project: ProjectDocument, iid: str) -> FaultInterpretationRef | None:
    for r in getattr(project, "fault_interpretations", None) or []:
        if r.id == iid:
            return r
    return None


def _upsert_ref(project: ProjectDocument, ref: FaultInterpretationRef) -> None:
    items = list(getattr(project, "fault_interpretations", None) or [])
    for i, existing in enumerate(items):
        if existing.id == ref.id:
            items[i] = ref
            project.fault_interpretations = items
            return
    items.append(ref)
    project.fault_interpretations = items
