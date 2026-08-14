"""Horizon interpretation lifecycle: draft → immutable version → lineage → reopen.

Follows the FactorGrid artifact-first pattern:
* Project save / explicit "save interpretation version" owns artifact write
* Catalog registers DERIVED DataVersion + run lineage
* ProjectDocument holds current version reference (not "latest file mtime")
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.catalog import (
    DataStage,
    DataVersionRef,
    get_catalog,
    sha256_file_or_none,
)
from paleo_workbench.project.models import (
    HorizonInterpretationRef,
    ProjectDocument,
)
from paleo_workbench.project.paths import artifact_dir_for
from paleo_workbench.viz.interpretation_artifact import (
    INTERP_ARTIFACT_SUFFIX,
    read_interpretation_artifact,
    scientific_fingerprint,
    write_interpretation_artifact,
)
from paleo_workbench.viz.interpretation_draft import (
    HorizonInterpretationDraft,
    InterpretationSaveSnapshot,
)

_log = logging.getLogger("paleo_workbench.interpretation")


def _id(prefix: str = "interp") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def open_draft_from_array(
    z: np.ndarray,
    *,
    horizon_key: str,
    name: str | None = None,
    interpretation_id: str | None = None,
    vertical_domain: str = "time",
    crs: str | None = None,
    parent_version_id: str | None = None,
    source_version_ids: list[str] | None = None,
    generation: int = 0,
) -> HorizonInterpretationDraft:
    """Start a mutable draft from a baseline Z grid (RAW seed or loaded version)."""
    return HorizonInterpretationDraft(
        interpretation_id=interpretation_id or _id(),
        horizon_key=horizon_key,
        name=name or horizon_key,
        baseline_z=z,
        vertical_domain=vertical_domain,
        crs=crs,
        parent_version_id=parent_version_id,
        source_version_ids=source_version_ids,
        generation=generation,
    )


def _canonical_version_id(
    cat, provisional: str, *, domain_task_id: str, fingerprint: str
) -> str | None:
    """Resolve the canonical catalog version id for a provisional token.

    Pre-catalog saves store a throwaway ``ver_<uuid>`` token in the artifact
    descriptor; the catalog assigns a different id. Resolve by domain task +
    scientific fingerprint so lineage never references a nonexistent version
    (H7).
    """
    if not provisional:
        return None
    try:
        if cat is not None and cat.resolve_version(provisional) is not None:
            return provisional
    except Exception:
        pass
    if cat is None:
        return None
    try:
        for run in cat.list_runs():
            if run.domain_task_id != domain_task_id:
                continue
            params = getattr(run, "parameters", None) or {}
            if params.get("scientific_fingerprint") != fingerprint:
                continue
            outs = list(run.output_version_ids or [])
            if outs:
                return outs[0]
    except Exception:
        return None
    return None


def open_draft_from_version(
    artifact_path: Path | str,
    *,
    interpretation_id: str | None = None,
    generation: int = 0,
) -> HorizonInterpretationDraft:
    """Load an immutable version artifact as a new draft baseline."""
    z, desc = read_interpretation_artifact(artifact_path)
    parent_version_id = desc.get("version_id") or desc.get("parent_version_id")
    if parent_version_id:
        from paleo_workbench.catalog import get_catalog

        try:
            cat = get_catalog()
        except Exception:
            cat = None
        canonical = _canonical_version_id(
            cat,
            str(parent_version_id),
            domain_task_id=str(desc.get("interpretation_id") or ""),
            fingerprint=str(desc.get("scientific_fingerprint") or ""),
        )
        if canonical:
            parent_version_id = canonical
    return HorizonInterpretationDraft(
        interpretation_id=interpretation_id
        or str(desc.get("interpretation_id") or _id()),
        horizon_key=str(desc.get("horizon_key") or "horizon"),
        name=str(desc.get("name") or desc.get("horizon_key") or "horizon"),
        baseline_z=z,
        vertical_domain=str(desc.get("vertical_domain") or "time"),
        crs=desc.get("crs"),
        parent_version_id=str(parent_version_id or "") or None,
        source_version_ids=list(desc.get("source_version_ids") or []),
        generation=generation,
    )


def save_draft_as_new_version(
    draft: HorizonInterpretationDraft,
    project: ProjectDocument,
    project_path: Path | str,
    *,
    catalog=None,
    expected_generation: int | None = None,
    expected_fingerprint: str | None = None,
) -> tuple[HorizonInterpretationRef | None, str]:
    """Freeze draft → write immutable artifact → register catalog → update project.

    Returns ``(ref, message)``. On generation/fingerprint mismatch returns
    ``(None, reason)`` without mutating project when the draft advanced mid-save.
    """
    path = Path(project_path)
    if expected_generation is not None and int(expected_generation) != int(
        draft.generation
    ):
        return None, "stale_generation"
    snap = draft.to_save_snapshot()
    if expected_fingerprint is not None and expected_fingerprint != snap.scientific_fingerprint:
        # Caller scheduled save for older content; still allow save of *current*
        # content only if they pass expected_fingerprint=None.
        return None, "fingerprint_mismatch_at_schedule"

    # No-op detection (mirrors correlation/fault lifecycles): saving identical
    # scientific content must not mint a duplicate immutable version.
    existing_ref = _find_interpretation_ref(project, snap.interpretation_id)
    if existing_ref is not None and existing_ref.scientific_fingerprint == snap.scientific_fingerprint:
        return existing_ref, "noop_unchanged"

    # A live draft that advanced mid-save is handled below: the version freezes
    # the snapshot content and the draft simply stays dirty (no adopt).

    interp_dir = artifact_dir_for(path) / "interpretations"
    version_token = _id("ver")
    artifact_name = f"{snap.horizon_key}_{version_token}"
    descriptor = {
        "interpretation_id": snap.interpretation_id,
        "horizon_key": snap.horizon_key,
        "name": snap.name,
        "vertical_domain": snap.vertical_domain,
        "crs": snap.crs,
        "parent_version_id": snap.parent_version_id,
        "source_version_ids": list(snap.source_version_ids),
        "scientific_fingerprint": snap.scientific_fingerprint,
        "version_id": version_token,  # provisional; catalog may assign canonical
        "kind": "horizon_interpretation",
    }
    try:
        artifact = write_interpretation_artifact(
            snap.z,
            interp_dir,
            artifact_name,
            descriptor=descriptor,
        )
    except OSError as exc:
        return None, f"artifact_write_failed:{exc}"

    checksum = sha256_file_or_none(artifact)
    try:
        version_ref = register_interpretation_version(
            name=f"{snap.name} interpretation",
            path=artifact.as_posix(),
            checksum=checksum,
            parent_version_id=snap.parent_version_id,
            source_version_ids=list(snap.source_version_ids),
            scientific_fingerprint=snap.scientific_fingerprint,
            domain_task_id=snap.interpretation_id,
            catalog=catalog,
        )
    except Exception:
        # Compensate: the staged artifact must not linger as a ghost file when
        # catalog registration failed (H7 failure injection).
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    version_id = version_ref.version_id if version_ref is not None else version_token
    managed_path = version_ref.path if version_ref is not None else artifact.as_posix()

    # Relative path for project portability when under artifacts dir.
    try:
        rel = Path(managed_path).resolve().relative_to(path.resolve().parent)
        store_path = rel.as_posix()
    except ValueError:
        store_path = managed_path

    ref = HorizonInterpretationRef(
        id=snap.interpretation_id,
        name=snap.name,
        horizon_key=snap.horizon_key,
        current_version_id=version_id,
        artifact_path=store_path,
        parent_version_id=snap.parent_version_id,
        status="clean",
        vertical_domain=snap.vertical_domain,
        shape=[int(snap.shape[0]), int(snap.shape[1])],
        source_version_ids=list(snap.source_version_ids),
        scientific_fingerprint=snap.scientific_fingerprint,
        display={},
    )
    _upsert_interpretation_ref(project, ref)

    # Only mark draft clean if scientific content still matches saved snapshot.
    if draft.scientific_fingerprint_now() == snap.scientific_fingerprint:
        draft.adopt_saved_version(version_id=version_id, fingerprint=snap.scientific_fingerprint)
    # else: version exists, draft remains dirty (user edited during save)

    return ref, "ok"


def register_interpretation_version(
    *,
    name: str,
    path: str,
    checksum: str | None,
    parent_version_id: str | None,
    source_version_ids: list[str],
    scientific_fingerprint: str,
    domain_task_id: str,
    catalog=None,
) -> DataVersionRef | None:
    """Register DERIVED interpretation version via CatalogPort."""
    from paleo_workbench.catalog.lifecycle import register_horizon_interpretation_run

    _run, version = register_horizon_interpretation_run(
        name=name,
        path=path,
        checksum=checksum,
        source_version_ids=source_version_ids,
        parent_version_id=parent_version_id,
        scientific_fingerprint=scientific_fingerprint,
        domain_task_id=domain_task_id,
        catalog=catalog,
    )
    return version


def load_interpretation_z(
    project_path: Path | str,
    ref: HorizonInterpretationRef,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Load current version Z for a project reference."""
    raw = ref.artifact_path
    if not raw:
        raise FileNotFoundError("interpretation has no artifact_path")
    p = Path(raw)
    if not p.is_file():
        p = Path(project_path).resolve().parent / raw
    return read_interpretation_artifact(p)


def restore_draft_from_project_ref(
    project: ProjectDocument,
    project_path: Path | str,
    *,
    interpretation_id: str | None = None,
) -> HorizonInterpretationDraft | None:
    """Reopen selected/current interpretation as a new draft baseline."""
    refs = list(getattr(project, "horizon_interpretations", None) or [])
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
    z, desc = load_interpretation_z(project_path, ref)
    return HorizonInterpretationDraft(
        interpretation_id=ref.id,
        horizon_key=ref.horizon_key,
        name=ref.name,
        baseline_z=z,
        vertical_domain=ref.vertical_domain or str(desc.get("vertical_domain") or "time"),
        crs=desc.get("crs"),
        parent_version_id=ref.current_version_id,
        source_version_ids=list(ref.source_version_ids or []),
        generation=0,
    )


def classify_stale(
    ref: HorizonInterpretationRef,
    *,
    current_source_version_ids: list[str] | tuple[str, ...] | None = None,
    current_crs: str | None = None,
    current_vertical_domain: str | None = None,
) -> str:
    """Return ``current`` or ``stale`` based on scientific dependency drift.

    Display-only changes are not inputs here — callers must not pass color/opacity.
    """
    if current_vertical_domain is not None and current_vertical_domain != ref.vertical_domain:
        return "stale"
    # CRS drift is NOT classifiable here: HorizonInterpretationRef carries no
    # saved CRS (only the opaque scientific fingerprint does), so there is
    # nothing to compare ``current_crs`` against. Callers that track a CRS
    # change must treat affected interpretations as stale themselves
    # (re-open + re-save re-fingerprints the new CRS).
    if current_source_version_ids is not None:
        expected = set(ref.source_version_ids or [])
        actual = set(current_source_version_ids)
        if expected and expected != actual:
            return "stale"
    return "current"


def _upsert_interpretation_ref(
    project: ProjectDocument, ref: HorizonInterpretationRef
) -> None:
    items = list(getattr(project, "horizon_interpretations", None) or [])
    for i, existing in enumerate(items):
        if existing.id == ref.id:
            items[i] = ref
            project.horizon_interpretations = items
            return
    items.append(ref)
    project.horizon_interpretations = items


def _find_interpretation_ref(
    project: ProjectDocument, interpretation_id: str
) -> HorizonInterpretationRef | None:
    for ref in getattr(project, "horizon_interpretations", None) or []:
        if ref.id == interpretation_id:
            return ref
    return None
