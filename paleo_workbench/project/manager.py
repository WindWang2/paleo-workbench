"""Portable project persistence with bounded runtime snapshots.

``ProjectDocument`` remains the project/business authority.  The small runtime
snapshot in this module is deliberately *not* persisted and is only used to
avoid repeating work when a live document has not changed.  The on-disk
``*.paleo.json`` file remains one complete, portable snapshot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from copy import deepcopy
from enum import Enum
import json
import os
import tempfile
from pathlib import Path
from typing import Any
import weakref

logger = logging.getLogger(__name__)

from pydantic import ValidationError

from paleo_workbench.catalog.storage import fsync_dir, safe_unlink
from paleo_workbench.project.factor_grid_artifacts import persist_factor_grid_artifacts
from paleo_workbench.project.models import ProjectDocument, _now_iso
from paleo_workbench.project.paths import (
    ensure_artifact_layout,
    project_dir_for,
    relativize_path,
    resolve_project_path,
)


class ProjectStaleWriteError(OSError):
    """Raised when the on-disk project file advanced past this session's baseline.

    ``*.paleo.json`` is rewritten as one whole document; a second process
    holding an older in-memory snapshot would silently overwrite the first
    process's commits (last-writer-wins, #411).  Save-time stale detection
    refuses the overwrite instead.
    """


class ProjectDirtyDomain(str, Enum):
    """Runtime-only domains used to explain a bounded project save."""

    PROJECT_METADATA = "project_metadata"
    RESOURCES = "resources"
    INTERPRETATIONS = "interpretations"
    FACTOR_TASKS = "factor_tasks"
    PREDICTIONS = "predictions"
    MAP_DOCUMENTS = "map_documents"
    QC = "qc"
    EXPORTS = "exports"


_DOMAIN_BY_SECTION = {
    "meta": ProjectDirtyDomain.PROJECT_METADATA,
    "coordinate": ProjectDirtyDomain.PROJECT_METADATA,
    "stratigraphy": ProjectDirtyDomain.PROJECT_METADATA,
    "joint_analysis": ProjectDirtyDomain.PROJECT_METADATA,
    "resources": ProjectDirtyDomain.RESOURCES,
    "well_tables": ProjectDirtyDomain.INTERPRETATIONS,
    "constraint_layers": ProjectDirtyDomain.INTERPRETATIONS,
    "contour_drafts": ProjectDirtyDomain.INTERPRETATIONS,
    "horizon_interpretations": ProjectDirtyDomain.INTERPRETATIONS,
    "correlation_interpretations": ProjectDirtyDomain.INTERPRETATIONS,
    "fault_interpretations": ProjectDirtyDomain.INTERPRETATIONS,
    "version_sets": ProjectDirtyDomain.INTERPRETATIONS,
    "compilation_runs": ProjectDirtyDomain.FACTOR_TASKS,
    "factor_map_tasks": ProjectDirtyDomain.FACTOR_TASKS,
    "prediction_tasks": ProjectDirtyDomain.PREDICTIONS,
    "paleomap_documents": ProjectDirtyDomain.MAP_DOCUMENTS,
    "user_vector_layers": ProjectDirtyDomain.MAP_DOCUMENTS,
    "map_qgis_project_xml": ProjectDirtyDomain.MAP_DOCUMENTS,
    "map_products": ProjectDirtyDomain.EXPORTS,
    "quality_reports": ProjectDirtyDomain.QC,
    "export_artifacts": ProjectDirtyDomain.EXPORTS,
}


@dataclass(frozen=True)
class ProjectPersistenceSnapshot:
    """Last known persisted state for one live :class:`ProjectDocument`.

    ``runtime_sections`` use the document's absolute runtime paths; portable
    sections keep the already-normalized JSON-ready values.  Reusing an
    unchanged portable section avoids a full ``Path.resolve`` walk during an
    unrelated metadata save, without creating another editable project model.
    """

    project_path: Path
    runtime_sections: dict[str, Any]
    portable_sections: dict[str, Any]
    # mtime of the on-disk project file at load / last save. A save whose
    # file advanced past it means another process wrote since we last looked
    # (#411 stale-write detection).
    disk_mtime_ns: int | None = None
    # Some old portable projects still contain inline numerical grids.  They
    # need one artifact migration even when their in-memory representation is
    # otherwise identical to the just-loaded document.
    pending_sections: frozenset[str] = frozenset()

    def changed_sections(self, current: dict[str, Any]) -> set[str]:
        return {
            name
            for name, value in current.items()
            if self.runtime_sections.get(name) != value
            or name in self.pending_sections
        }

    def dirty_domains(self, current: dict[str, Any]) -> set[ProjectDirtyDomain]:
        return {
            _DOMAIN_BY_SECTION.get(name, ProjectDirtyDomain.PROJECT_METADATA)
            for name in self.changed_sections(current)
        }


@dataclass(frozen=True)
class ProjectSaveStats:
    """Diagnostics for local benchmarks and focused tests (not persisted)."""

    wrote_project_file: bool
    dirty_domains: frozenset[ProjectDirtyDomain]
    factor_artifacts_persisted: int = 0


@dataclass(frozen=True)
class PreparedSave:
    """Detached, write-ready state captured by :meth:`ProjectManager.prepare_save`.

    Everything here is plain JSON-compatible data copied out of the live
    document on the GUI thread, so :meth:`ProjectManager.execute_save` can run
    on a worker thread without racing user edits (#1040). ``runtime_sections``
    is the comparison view the commit snapshot publishes: mutations landing
    after the prepare call stay dirty for the next save.
    """

    payload_data: dict[str, Any]
    runtime_sections: dict[str, Any]
    changed_sections: frozenset[str]
    updated_at: str
    factor_changes: int = 0


# Pydantic documents are mutable and intentionally do not carry persistence
# bookkeeping.  A weak identity map gives a document one ephemeral snapshot
# without changing its JSON schema or keeping closed projects alive.
_SNAPSHOTS: dict[int, tuple[weakref.ref[ProjectDocument], ProjectPersistenceSnapshot]] = {}


def _snapshot_for(project: ProjectDocument) -> ProjectPersistenceSnapshot | None:
    entry = _SNAPSHOTS.get(id(project))
    if entry is None:
        return None
    reference, snapshot = entry
    if reference() is project:
        return snapshot
    _SNAPSHOTS.pop(id(project), None)
    return None


def _remember_snapshot(project: ProjectDocument, snapshot: ProjectPersistenceSnapshot) -> None:
    key = id(project)

    def _forget(_reference: weakref.ref[ProjectDocument], *, _key: int = key) -> None:
        _SNAPSHOTS.pop(_key, None)

    _SNAPSHOTS[key] = (weakref.ref(project, _forget), snapshot)


# Sections whose values carry filesystem paths and therefore need portable
# normalization (relativization against the project dir) — applied at save
# for changed sections and at load for the session snapshot, so an untouched
# legacy section saved with absolute paths normalizes on load the same way a
# save of that section would (load/save symmetry, #1170).
_PATH_BEARING_SECTIONS = frozenset(
    {
        "resources",
        "export_artifacts",
        "paleomap_documents",
        "factor_map_tasks",
        "horizon_interpretations",
    }
)


def _runtime_sections(project: ProjectDocument) -> dict[str, Any]:
    """Return a detached comparison view, omitting runtime-only root binding."""

    sections = project.model_dump(mode="json")
    sections["meta"] = dict(sections["meta"])
    sections["meta"]["project_root"] = "."
    return sections


def project_backup_path(project_path: str | Path) -> Path:
    """Return the single bounded last-known-good project metadata backup."""

    path = Path(project_path)
    return path.with_name(f"{path.name}.bak")


def _file_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _cleanup_project_temps(project_path: Path) -> None:
    """Remove only stale temp files that this manager itself could create."""

    prefix = f".{project_path.name}."
    try:
        candidates = project_path.parent.glob(f"{prefix}*.tmp")
        for candidate in candidates:
            try:
                if candidate.is_file():
                    candidate.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _relativize_reference_layers(data: dict[str, Any], project_path: Path) -> None:
    for doc in data.get("paleomap_documents") or []:
        for layer in doc.get("reference_layers") or []:
            source = layer.get("source_path")
            if not source:
                continue
            path, external = relativize_path(source, project_path)
            layer["source_path"] = path
            layer["external"] = external


def _resolve_reference_layers(project: ProjectDocument, project_path: Path) -> None:
    for doc in project.paleomap_documents:
        for layer in doc.reference_layers:
            source = layer.source_path
            if not source:
                continue
            layer.source_path = resolve_project_path(source, project_path)
            # File presence check on the resolved absolute path (status offline).
            path = Path(layer.source_path)
            if not path.is_file():
                layer.status = "offline"
                layer.error_message = layer.error_message or "参考图源文件不可用"
            elif layer.status == "offline":
                layer.status = "ready"
                if layer.error_message == "参考图源文件不可用":
                    layer.error_message = ""


def _relativize_factor_grid_artifacts(data: dict[str, Any], project_path: Path) -> None:
    for task in data.get("factor_map_tasks") or []:
        artifact_path = task.get("grid_artifact_path")
        if not artifact_path:
            continue
        stored, _ = relativize_path(artifact_path, project_path)
        task["grid_artifact_path"] = stored


def _resolve_factor_grid_artifacts(project: ProjectDocument, project_path: Path) -> None:
    for task in project.factor_map_tasks:
        if task.grid_artifact_path:
            task.grid_artifact_path = resolve_project_path(
                task.grid_artifact_path, project_path
            )


def _relativize_interpretation_artifacts(
    data: dict[str, Any], project_path: Path
) -> None:
    """Keep managed interpretation payload references portable like factor grids."""

    for interpretation in data.get("horizon_interpretations") or []:
        artifact_path = interpretation.get("artifact_path")
        if not artifact_path:
            continue
        stored, _ = relativize_path(artifact_path, project_path)
        interpretation["artifact_path"] = stored


def _resolve_interpretation_artifacts(
    project: ProjectDocument, project_path: Path
) -> None:
    for interpretation in project.horizon_interpretations:
        if interpretation.artifact_path:
            interpretation.artifact_path = resolve_project_path(
                interpretation.artifact_path, project_path
            )


def _resolve_project_paths(project: ProjectDocument, project_path: Path) -> None:
    project_dir = project_dir_for(project_path)
    for resource in project.resources:
        resource.path = resolve_project_path(
            resource.path, project_path, project_dir=project_dir
        )
    for artifact in project.export_artifacts:
        artifact.output_path = resolve_project_path(
            artifact.output_path, project_path, project_dir=project_dir
        )
    _resolve_reference_layers(project, project_path)
    _resolve_factor_grid_artifacts(project, project_path)
    _resolve_interpretation_artifacts(project, project_path)


def _pending_persistence_sections(project: ProjectDocument) -> frozenset[str]:
    """Return legacy sections that require one write-side migration.

    The normal session snapshot makes ``open → Save`` a no-op.  Old projects
    carrying an inline factor grid are the deliberate exception: Stage 3's
    artifact-first contract requires migration to an immutable artifact on the
    first save, even though no user-visible model field changed after load.
    """

    for task in project.factor_map_tasks:
        if task.parameters.get("grid_z") is not None:
            return frozenset({"factor_map_tasks"})
    return frozenset()


def _portable_section(section: str, value: Any, project_path: Path) -> Any:
    """Normalize only a changed section for portable project JSON."""

    project_dir = project_dir_for(project_path)
    if section == "resources":
        for resource in value:
            path, external = relativize_path(
                resource["path"], project_path, project_dir=project_dir
            )
            resource["path"] = path
            resource["external"] = external
    elif section == "export_artifacts":
        for artifact in value:
            output_path, _ = relativize_path(
                artifact["output_path"], project_path, project_dir=project_dir
            )
            artifact["output_path"] = output_path
    elif section == "paleomap_documents":
        _relativize_reference_layers({"paleomap_documents": value}, project_path)
    elif section == "factor_map_tasks":
        _relativize_factor_grid_artifacts({"factor_map_tasks": value}, project_path)
    elif section == "horizon_interpretations":
        _relativize_interpretation_artifacts(
            {"horizon_interpretations": value}, project_path
        )
    return value


class ProjectManager:
    """Read/write one portable project JSON with crash-safe metadata recovery."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.last_save_stats = ProjectSaveStats(False, frozenset())
        self.last_recovery_message: str | None = None

    def _portable_payload(
        self,
        project: ProjectDocument,
        runtime_sections: dict[str, Any],
        changed_sections: set[str],
    ) -> dict[str, Any]:
        snapshot = _snapshot_for(project)
        can_reuse = (
            snapshot is not None
            and snapshot.project_path == self.project_path
        )
        payload: dict[str, Any] = {}
        for section, value in runtime_sections.items():
            if can_reuse and section not in changed_sections:
                payload[section] = snapshot.portable_sections[section]
            else:
                # ``model_dump`` already produced a detached JSON-compatible
                # section; its in-place path normalization cannot mutate the
                # live ProjectDocument or the previous snapshot.
                payload[section] = _portable_section(section, value, self.project_path)
        if can_reuse and snapshot is not None:
            # #1170: unknown sections preserved at load ride along verbatim.
            for section, value in snapshot.portable_sections.items():
                if section not in payload:
                    payload[section] = value
        return payload

    def _write_payload(self, payload: str) -> None:
        """Atomically replace project metadata and retain one good revision."""

        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        backup = project_backup_path(self.project_path)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.project_path.name}.",
            suffix=".tmp",
            dir=str(self.project_path.parent),
        )
        old_moved = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.project_path.exists():
                os.replace(self.project_path, backup)
                old_moved = True
            os.replace(tmp_name, self.project_path)
            # Best effort on platforms/filesystems where opening a directory is
            # unsupported.  The file itself has already been flushed.
            fsync_dir(self.project_path.parent)
        except Exception:
            safe_unlink(tmp_name)
            if old_moved and not self.project_path.exists() and backup.exists():
                try:
                    os.replace(backup, self.project_path)
                    fsync_dir(self.project_path.parent)
                except OSError:
                    pass
            raise

    def save(self, project: ProjectDocument) -> bool:
        """Persist changed project metadata; return whether JSON was rewritten.

        A full portable JSON is still written for a changed project.  For a
        clean live document this method avoids factor-artifact probing, path
        translation, JSON encoding, fsync and replacement entirely.

        Composed of the three #1040 phases: :meth:`prepare_save` (GUI thread —
        diff, stale guard, detached payload build), :meth:`execute_save`
        (worker thread — serialize + atomic write), :meth:`commit_save`
        (GUI thread — publish snapshot). Synchronous callers keep this facade.
        """
        prepared = self.prepare_save(project)
        if prepared is None:
            self.last_save_stats = ProjectSaveStats(False, frozenset())
            return False
        stats = self.execute_save(prepared)
        self.commit_save(project, prepared, stats)
        return True

    def prepare_save(self, project: ProjectDocument) -> PreparedSave | None:
        """GUI-phase of a save: decide what to write and build a detached payload.

        Performs the WorkArea sync, section diff, stale-write guard and factor
        artifact externalization, then materializes the JSON-ready payload.
        Heavy file I/O (serialize + write + fsync) is deliberately left to
        :meth:`execute_save` so this phase is safe on the GUI thread (#1040).
        Returns ``None`` when the live document is clean and nothing needs
        rewriting.
        """
        # Keep the WorkArea CRS projection honest at the persistence boundary
        # (ADR 0059: coordinate stays canonical; workarea mirrors it).  A sync
        # here means the section diff below sees the updated workarea too.
        try:
            from paleo_workbench.project.domain import sync_workarea_with_coordinate

            sync_workarea_with_coordinate(project)
        except Exception:
            pass

        runtime_sections = _runtime_sections(project)
        snapshot = _snapshot_for(project)
        same_path = snapshot is not None and snapshot.project_path == self.project_path
        changed_sections = (
            snapshot.changed_sections(runtime_sections) if same_path else set(runtime_sections)
        )
        if same_path and not changed_sections:
            return None

        if same_path and snapshot.disk_mtime_ns is not None:
            current = _file_mtime_ns(self.project_path)
            if current is not None and current != snapshot.disk_mtime_ns:
                # Another process wrote the project since this session loaded
                # or last saved it; a whole-document overwrite would silently
                # drop that process's commits (last-writer-wins, #411).
                raise ProjectStaleWriteError(
                    f"工程文件已被其他实例修改（{self.project_path.name}）；"
                    "为避免覆盖他人提交，保存已中止。请重新打开工程后重试。"
                )

        factor_changes = 0
        if not same_path or "factor_map_tasks" in changed_sections:
            # Only inspect numerical factor payloads when the task domain has
            # changed (or on an initial/save-as persistence boundary).
            factor_changes = len(persist_factor_grid_artifacts(project, self.project_path))
            if factor_changes:
                runtime_sections = _runtime_sections(project)
                changed_sections = (
                    snapshot.changed_sections(runtime_sections)
                    if same_path
                    else set(runtime_sections)
                )

        updated_at = _now_iso()
        payload_data = self._portable_payload(project, runtime_sections, changed_sections)
        payload_data["meta"] = dict(payload_data["meta"])
        payload_data["meta"]["updated_at"] = updated_at
        # The persisted file is portable.  Runtime consumers receive the
        # concrete root from ProjectController on open, while document paths
        # have already been resolved independently of this hint.
        payload_data["meta"]["project_root"] = "."
        # The commit snapshot must compare equal against the next live dump:
        # mirror the meta overrides onto the runtime view captured here.
        runtime_sections["meta"] = dict(runtime_sections["meta"])
        runtime_sections["meta"]["updated_at"] = updated_at
        runtime_sections["meta"]["project_root"] = "."
        return PreparedSave(
            payload_data=payload_data,
            runtime_sections=runtime_sections,
            changed_sections=frozenset(changed_sections),
            updated_at=updated_at,
            factor_changes=factor_changes,
        )

    def execute_save(self, prepared: PreparedSave) -> ProjectSaveStats:
        """Worker-phase of a save: serialize and atomically write the payload.

        Touches only the detached data captured by :meth:`prepare_save` plus
        the project file itself — never the live ``ProjectDocument`` — so it
        is safe to run on an ``OwnedWorkerJob`` thread while the GUI keeps
        serving the user (#1040).
        """
        # Ensure a new project owns the same durable artifact layout before its
        # portable metadata references it. Existing clean sessions do not reach
        # this point and therefore do no directory/artifact work.
        ensure_artifact_layout(self.project_path)
        payload = json.dumps(prepared.payload_data, ensure_ascii=False, indent=2)
        self._write_payload(payload)
        dirty_domains = frozenset(
            _DOMAIN_BY_SECTION.get(section, ProjectDirtyDomain.PROJECT_METADATA)
            for section in prepared.changed_sections
        )
        return ProjectSaveStats(True, dirty_domains, prepared.factor_changes)

    def commit_save(self, project: ProjectDocument, prepared: PreparedSave, stats: ProjectSaveStats) -> None:
        """GUI-phase after the write: publish post-save state onto the document."""
        project.meta.updated_at = prepared.updated_at
        _remember_snapshot(
            project,
            ProjectPersistenceSnapshot(
                project_path=self.project_path,
                runtime_sections=prepared.runtime_sections,
                portable_sections=prepared.payload_data,
                disk_mtime_ns=_file_mtime_ns(self.project_path),
                pending_sections=frozenset(),
            ),
        )
        self.last_save_stats = stats

    def _load_data(self) -> tuple[dict[str, Any], ProjectDocument, bool]:
        """Read canonical metadata, falling back to one last-known-good copy."""

        self.last_recovery_message = None
        try:
            data = json.loads(self.project_path.read_text(encoding="utf-8"))
            return data, ProjectDocument.model_validate(data), False
        except (OSError, ValueError, TypeError, ValidationError) as original_error:
            backup = project_backup_path(self.project_path)
            if not backup.is_file():
                raise original_error
            try:
                data = json.loads(backup.read_text(encoding="utf-8"))
                project = ProjectDocument.model_validate(data)
            except (OSError, ValueError, TypeError, ValidationError):
                raise original_error
            try:
                os.replace(backup, self.project_path)
                fsync_dir(self.project_path.parent)
            except OSError:
                pass
            self.last_recovery_message = "已恢复上一次完整工程元数据版本"
            return data, project, True

    def load(self) -> ProjectDocument:
        _cleanup_project_temps(self.project_path)
        data, project, _recovered = self._load_data()
        # Validate portable schema first, then resolve the handful of runtime
        # path-bearing fields in the authoritative business document.  Keeping
        # ``data`` untouched lets the session retain its already-portable
        # sections without another all-resource relativization pass.
        _resolve_project_paths(project, self.project_path)
        # The persisted hint stays portable (``."``), while runtime consumers
        # receive the concrete root without turning an immediate clean save
        # into a false metadata mutation.
        project.meta.project_root = str(self.project_path.resolve().parent)
        runtime_sections = _runtime_sections(project)
        # Portable snapshot for the session. Unknown top-level sections ride
        # along untouched (extra="allow" keeps them in the runtime dump,
        # #1170); path-bearing sections are normalized the same way a save
        # would normalize them, so load and save agree on legacy
        # absolute-path representations instead of an untouched section
        # keeping them until it happens to change (#1170).
        portable_sections = {
            section: data.get(section, runtime_sections[section])
            for section in runtime_sections
        }
        for section in sorted(_PATH_BEARING_SECTIONS - {"paleomap_documents"}):
            portable_sections[section] = _portable_section(
                section,
                deepcopy(portable_sections[section]),
                self.project_path,
            )
        # Reference-layer status is runtime-derived from source availability;
        # retain its normalized portable representation so a later unrelated
        # save does not accidentally resurrect an obsolete ``ready`` status.
        # #1170: normalize every path-bearing section (not just two), and
        # preserve unknown on-disk sections verbatim instead of dropping
        # them on the next save (downgrade data-loss guard + warning).
        for section in (
            "resources",
            "export_artifacts",
            "paleomap_documents",
            "factor_map_tasks",
            "horizon_interpretations",
        ):
            if section in portable_sections:
                portable_sections[section] = _portable_section(
                    section,
                    deepcopy(portable_sections[section]),
                    self.project_path,
                )
        unknown_sections = sorted(set(data) - set(runtime_sections))
        for section in unknown_sections:
            portable_sections[section] = deepcopy(data[section])
        if unknown_sections:
            logger.warning(
                "project file has unknown sections %s (newer schema?) — "
                "preserved verbatim, not interpreted",
                unknown_sections,
            )
        # #1170: sections whose load-time normalization differs from disk
        # need one write-side migration even though the live document is
        # otherwise identical to what was loaded (legacy absolute paths).
        pending = set(_pending_persistence_sections(project))
        for section in (
            "resources",
            "export_artifacts",
            "paleomap_documents",
            "factor_map_tasks",
            "horizon_interpretations",
        ):
            if section in data and portable_sections.get(section) != data.get(section):
                pending.add(section)
        portable_sections["meta"] = dict(portable_sections.get("meta", {}))
        portable_sections["meta"]["project_root"] = "."
        _remember_snapshot(
            project,
            ProjectPersistenceSnapshot(
                project_path=self.project_path,
                runtime_sections=runtime_sections,
                portable_sections=portable_sections,
                disk_mtime_ns=_file_mtime_ns(self.project_path),
                pending_sections=frozenset(pending),
            ),
        )
        return project
