"""Correlation interpretation lifecycle: draft → immutable version → reopen.

Mirrors Stage-8 horizon interpretation without mutating RAW wells.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from paleo_workbench.catalog import get_catalog, sha256_file_or_none
from paleo_workbench.project.models import (
    CorrelationInterpretationRef,
    ProjectDocument,
)
from paleo_workbench.project.paths import artifact_dir_for
from paleo_workbench.workflow.correlation_artifact import (
    read_correlation_artifact,
    scientific_fingerprint_correlation,
    write_correlation_artifact,
)
from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationInterpretationDraft,
    CorrelationMethod,
    CorrelationScientificPayload,
    DepthDomain,
    FormationTop,
)

_log = logging.getLogger("paleo_workbench.correlation")


def _id(prefix: str = "corr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_correlation_draft(
    *,
    name: str = "连井对比",
    well_resource_ids: list[str] | None = None,
    well_version_ids: list[str] | None = None,
    tops: list[FormationTop] | None = None,
    depth_domain: DepthDomain = DepthDomain.MD,
    framework_ref: str = "",
    interpretation_id: str | None = None,
    parent_version_id: str | None = None,
) -> CorrelationInterpretationDraft:
    iid = interpretation_id or _id()
    payload = CorrelationScientificPayload(
        interpretation_id=iid,
        name=name,
        framework_ref=framework_ref,
        depth_domain=depth_domain,
        well_resource_ids=list(well_resource_ids or []),
        well_version_ids=list(well_version_ids or []),
        tops=list(tops or []),
        links=[],
        parent_version_id=parent_version_id,
    )
    return CorrelationInterpretationDraft(
        interpretation_id=iid,
        name=name,
        payload=payload,
        dirty=True,
        last_saved_fingerprint="",
    )


def open_draft_from_version(
    artifact_path: Path | str,
    *,
    interpretation_id: str | None = None,
    generation: int = 0,
) -> CorrelationInterpretationDraft:
    payload, _desc = read_correlation_artifact(artifact_path)
    iid = interpretation_id or payload.interpretation_id or _id()
    payload.interpretation_id = iid
    # Copy-on-edit: parent becomes the loaded version id if present in descriptor
    fp = scientific_fingerprint_correlation(payload)
    return CorrelationInterpretationDraft(
        interpretation_id=iid,
        name=payload.name or "连井对比",
        payload=payload,
        generation=generation,
        dirty=False,
        last_saved_fingerprint=fp,
    )


def draft_fingerprint(draft: CorrelationInterpretationDraft) -> str:
    return scientific_fingerprint_correlation(draft.payload)


def detect_depth_domain_mismatch(tops: list[FormationTop]) -> list[str]:
    """Return distinct depth domains among tops (metadata only)."""
    domains = sorted({t.depth_domain.value for t in tops if t.depth_domain})
    return domains


def save_correlation_draft(
    draft: CorrelationInterpretationDraft,
    project: ProjectDocument,
    project_path: Path | str,
    *,
    catalog=None,
    force_new_version: bool = False,
) -> tuple[CorrelationInterpretationRef | None, str]:
    """Save draft as immutable DERIVED version; no-op if fingerprint unchanged."""
    path = Path(project_path)
    fp = draft_fingerprint(draft)
    # No-op: same scientific content as last save / project ref
    if not force_new_version and draft.last_saved_fingerprint and (
        fp == draft.last_saved_fingerprint
    ):
        ref = _find_ref(project, draft.interpretation_id)
        if ref is not None:
            return ref, "noop_unchanged"
        # Fall through if no ref yet

    existing = _find_ref(project, draft.interpretation_id)
    if (
        not force_new_version
        and existing is not None
        and existing.scientific_fingerprint
        and existing.scientific_fingerprint == fp
    ):
        draft.dirty = False
        draft.last_saved_fingerprint = fp
        return existing, "noop_unchanged"

    parent = draft.payload.parent_version_id
    if existing and existing.current_version_id:
        # Branch from current tip when editing saved product
        if not parent:
            parent = existing.current_version_id
        draft.payload.parent_version_id = parent

    corr_dir = artifact_dir_for(path) / "correlations"
    version_token = _id("ver")
    artifact = write_correlation_artifact(
        draft.payload,
        corr_dir,
        f"{draft.interpretation_id}_{version_token}",
        extra_descriptor={
            "interpretation_id": draft.interpretation_id,
            "version_token": version_token,
        },
    )
    checksum = sha256_file_or_none(artifact)

    from paleo_workbench.catalog.lifecycle import register_stratigraphic_correlation_run

    _run, version = register_stratigraphic_correlation_run(
        name=f"{draft.name} correlation",
        path=artifact.as_posix(),
        checksum=checksum,
        source_version_ids=list(draft.payload.well_version_ids),
        parent_version_id=parent,
        scientific_fingerprint=fp,
        domain_task_id=draft.interpretation_id,
        parameters={
            "depth_domain": draft.payload.depth_domain.value,
            "well_resource_ids": list(draft.payload.well_resource_ids),
            "method_summary": list(draft.payload.method_summary),
            "top_count": len(draft.payload.tops),
            "link_count": len(draft.payload.links),
        },
        catalog=catalog,
    )
    version_id = version.version_id if version is not None else version_token
    managed_path = version.path if version is not None else artifact.as_posix()
    try:
        rel = Path(managed_path).resolve().relative_to(path.resolve().parent)
        store_path = rel.as_posix()
    except ValueError:
        store_path = managed_path

    domains = detect_depth_domain_mismatch(list(draft.payload.tops))
    ref = CorrelationInterpretationRef(
        id=draft.interpretation_id,
        name=draft.name,
        current_version_id=version_id,
        artifact_path=store_path,
        parent_version_id=parent,
        status="clean",
        depth_domain=draft.payload.depth_domain.value,
        depth_domains=domains or [draft.payload.depth_domain.value],
        well_resource_ids=list(draft.payload.well_resource_ids),
        source_version_ids=list(draft.payload.well_version_ids),
        scientific_fingerprint=fp,
        framework_ref=draft.payload.framework_ref,
        display=dict(draft.display or {}),
    )
    _upsert_ref(project, ref)
    draft.dirty = False
    draft.last_saved_fingerprint = fp
    draft.payload.parent_version_id = version_id  # next edit branches from tip
    return ref, "ok"


def restore_draft_from_project_ref(
    project: ProjectDocument,
    project_path: Path | str,
    *,
    interpretation_id: str | None = None,
) -> CorrelationInterpretationDraft | None:
    refs = list(getattr(project, "correlation_interpretations", None) or [])
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
    draft = open_draft_from_version(p, interpretation_id=ref.id)
    # Working copy: parent is current immutable tip
    draft.payload.parent_version_id = ref.current_version_id
    draft.dirty = False
    draft.last_saved_fingerprint = ref.scientific_fingerprint or draft_fingerprint(draft)
    return draft


def tops_from_imported_dict(
    tops_by_well: dict[str, list[tuple[str, float]]],
    *,
    well_name_to_id: dict[str, str] | None = None,
    depth_domain: DepthDomain = DepthDomain.MD,
    method: CorrelationMethod = CorrelationMethod.IMPORTED,
) -> list[FormationTop]:
    """Build FormationTop list from load_well_tops-style structure."""
    name_to_id = well_name_to_id or {}
    out: list[FormationTop] = []
    for well_name, rows in tops_by_well.items():
        wid = name_to_id.get(well_name, "")
        for marker, depth in rows:
            out.append(
                FormationTop(
                    well_id=wid,
                    well_name=well_name,
                    marker=str(marker),
                    depth=float(depth),
                    depth_domain=depth_domain,
                    method=method,
                )
            )
    return out


def resolve_correlation_target_horizon(
    project: ProjectDocument,
) -> str:
    """Preferred target horizon string for factors / maps from current context.

    Order: stratigraphy.target_horizon → first correlation framework_ref →
    first horizon_interpretation.horizon_key.
    """
    th = getattr(getattr(project, "stratigraphy", None), "target_horizon", "") or ""
    if th.strip():
        return th.strip()
    for ref in getattr(project, "correlation_interpretations", None) or []:
        fr = getattr(ref, "framework_ref", "") or ""
        if fr.strip():
            return fr.strip()
    for ref in getattr(project, "horizon_interpretations", None) or []:
        key = getattr(ref, "horizon_key", "") or ""
        if key.strip():
            return key.strip()
    return ""


def _find_ref(
    project: ProjectDocument, interpretation_id: str
) -> CorrelationInterpretationRef | None:
    for r in getattr(project, "correlation_interpretations", None) or []:
        if r.id == interpretation_id:
            return r
    return None


def _upsert_ref(project: ProjectDocument, ref: CorrelationInterpretationRef) -> None:
    items = list(getattr(project, "correlation_interpretations", None) or [])
    for i, existing in enumerate(items):
        if existing.id == ref.id:
            items[i] = ref
            project.correlation_interpretations = items
            return
    items.append(ref)
    project.correlation_interpretations = items
