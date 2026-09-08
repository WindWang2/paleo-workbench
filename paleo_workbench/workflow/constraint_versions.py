"""Constraint lifecycle — authoritative document content → catalog DERIVED
DataVersions (V8 M2).

Pre-V8 state: constraints lived only as project-document models with content
fingerprints stamped by the geometry sync-back. Interpolation fingerprints
made factor tasks dirty on constraint edits, but nothing could answer "which
constraint VERSION did this result use", old constraint states were not
inspectable or comparable, and integrated compilations treated
``constraints:current`` as permanently UNKNOWN.

This module gives constraints a real data lifecycle WITHOUT a second
database — the catalog (one asset per constraint group, one immutable
DataVersion per commit, one DataRun per commit with provenance) is the
version authority; the project document stays the live editing surface:

.. code-block:: text

    QGIS edit session → stage save (geometry sync-back, #1237)
        ↓ explicit commit (commit_constraint_group)
    catalog DERIVED DataVersion + DataRun  [no-op when content unchanged]
        ↓ pin at interpolation time (content hashes on the task)
    FactorMapTask parameters["constraint_pins"]
        ↓ factor grids / products (existing fingerprints + lineage)
    Compilation Input Set: constraints:<group>:<version> pins
        ↓ integrated freshness: pinned vs current committed (real STALE)

Semantics:
* RAW/DERIVED — constraints are interpretation products, committed as
  ``stage=DERIVED``; the digitized vector layer is the RAW source recorded
  via ``properties["layer_id"]`` in each line.
* edit → commit — a commit is EXPLICIT; unchanged content commits nothing
  (no silent overwrite, no version spam).
* version identity — ``content_hash`` (canonical sha256, same rounding as
  the sync-back fingerprint) travels on every version, run and pin, so
  freshness never depends on wall-clock time.
* honest UNKNOWN — a factor task interpolated while a group had never been
  committed pins the content hash but ``version_id=None``; freshness says
  UNKNOWN, never a fabricated STALE/CLEAN.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService

__all__ = [
    "CONSTRAINT_ASSET_TYPE",
    "ConstraintCommitReport",
    "commit_constraint_group",
    "commit_all_constraints",
    "constraint_group_content_hash",
    "current_constraint_version",
    "constraint_pins_for_task",
    "pinned_constraint_pins",
    "constraint_pins_staleness",
    "compare_constraint_versions",
    "resolve_constraint_ref",
]

CONSTRAINT_ASSET_TYPE = "constraints"
CONSTRAINT_COMMIT_OPERATION = "constraint_commit"


@dataclass(frozen=True, slots=True)
class ConstraintCommitReport:
    """Outcome of one constraint-group commit (data only)."""

    group_id: str
    group_name: str
    committed: bool  # a NEW version was created
    reason: str  # "changed" | "unchanged" | "no_content"
    asset_id: str | None = None
    version_id: str | None = None  # NEW version, or the unchanged match
    previous_version_id: str | None = None
    run_id: str | None = None
    content_hash: str | None = None
    line_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "committed": self.committed,
            "reason": self.reason,
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "previous_version_id": self.previous_version_id,
            "run_id": self.run_id,
            "content_hash": self.content_hash,
            "line_count": self.line_count,
        }


def _canonical_line(line: Any) -> dict[str, Any]:
    coordinates = [
        [round(float(p[0]), 9), round(float(p[1]), 9)]
        for p in (getattr(line, "coordinates", None) or [])
        if isinstance(p, (list, tuple)) and len(p) >= 2
    ]
    properties = dict(getattr(line, "properties", None) or {})
    payload: dict[str, Any] = {
        "line_id": str(getattr(line, "id", "") or ""),
        "name": str(getattr(line, "name", "") or ""),
        "role": str(getattr(line, "role", "") or ""),
        "active": bool(getattr(line, "active", True)),
        "target_horizon": str(getattr(line, "target_horizon", "") or ""),
        "coordinates": coordinates,
    }
    for key in ("azimuth_deg", "semi_major", "semi_minor"):
        value = getattr(line, key, None)
        if value is not None:
            payload[key] = float(value)
    # Scientific identity carried by the sync-back stamps (kind + geometry
    # fingerprint) rides along; free-form UI properties stay out of identity.
    for key in ("constraint_kind", "content_fingerprint", "layer_id"):
        if key in properties:
            payload[key] = str(properties[key])
    return payload


def _canonical_group_payload(group: Any) -> dict[str, Any]:
    lines = sorted(
        (_canonical_line(line) for line in (group.lines or [])),
        key=lambda entry: entry["line_id"],
    )
    return {
        "group_id": str(getattr(group, "id", "") or ""),
        "name": str(getattr(group, "name", "") or ""),
        "target_horizon": str(getattr(group, "target_horizon", "") or ""),
        "crs": getattr(group, "crs", None),
        "lines": lines,
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def constraint_group_content_hash(group: Any) -> tuple[str, int]:
    """Content hash over the group's GEOMETRIC content (active, digitized lines).

    The hash is ID-FREE and ORDER-FREE: line ids are auto-generated per
    model instance (they differ between saves of identical content), so
    identity strips ``line_id``/``group_id`` and sorts lines by their
    canonical serialization — same content, same hash, regardless of line
    ordering or object identity. Lines without coordinates never count; an
    undigitized draft constraint is not content yet.
    """
    payload = _canonical_group_payload(group)
    content_lines = [
        {k: v for k, v in line.items() if k != "line_id"}
        for line in payload["lines"]
        if line["active"] and line["coordinates"] and len(line["coordinates"]) >= 2
    ]
    content_lines.sort(
        key=lambda line: json.dumps(line, sort_keys=True, ensure_ascii=False)
    )
    content = {k: v for k, v in payload.items() if k != "group_id"}
    content["lines"] = content_lines
    return _payload_hash(content), len(content_lines)


def _constraint_assets(catalog: DataCatalogService) -> list[Any]:
    return [
        asset
        for asset in (getattr(catalog.document, "assets", None) or [])
        if str(getattr(asset, "type", "") or "") == CONSTRAINT_ASSET_TYPE
    ]


def _asset_for_group(catalog: DataCatalogService, group_id: str) -> Any | None:
    for asset in _constraint_assets(catalog):
        meta = dict(getattr(asset, "metadata", None) or {})
        if str(meta.get("constraint_group_id") or "") == str(group_id):
            return asset
    return None


def _latest_version(catalog: DataCatalogService, asset_id: str) -> Any | None:
    versions = [
        v
        for v in (getattr(catalog.document, "versions", None) or [])
        if str(getattr(v, "asset_id", "") or "") == str(asset_id)
    ]
    if not versions:
        return None
    versions.sort(key=lambda v: (getattr(v, "version_number", 0) or 0))
    return versions[-1]


def _write_payload(payload: dict[str, Any]) -> Path:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="constraint-commit-")
    path = Path(tmp) / "constraints.json"
    path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def commit_constraint_group(
    project: Any,
    catalog: DataCatalogService,
    group: Any,
    *,
    actor: str = "",
    notes: str = "",
) -> ConstraintCommitReport:
    """Commit one constraint group's authoritative content as a DERIVED version.

    Content-unchanged commits are no-ops returning the matching version —
    re-committing the same geometry never creates a version (no silent
    overwrite, no spam). The first commit creates the group's asset through
    the sanctioned atomic path (:meth:`register_result_asset`); later commits
    append immutable versions to that ONE asset via :meth:`register_version`.
    The DataRun records actor/notes/line count for the provenance chain.
    """
    content_hash, n_lines = constraint_group_content_hash(group)
    group_id = str(getattr(group, "id", "") or "")
    group_name = str(getattr(group, "name", "") or "")
    if n_lines == 0:
        return ConstraintCommitReport(
            group_id=group_id,
            group_name=group_name,
            committed=False,
            reason="no_content",
            content_hash=None,
            line_count=0,
        )

    asset = _asset_for_group(catalog, group_id)
    previous = _latest_version(catalog, str(asset.id)) if asset is not None else None
    if previous is not None:
        prev_meta = dict(getattr(previous, "metadata", None) or {})
        if str(prev_meta.get("content_hash") or "") == content_hash:
            return ConstraintCommitReport(
                group_id=group_id,
                group_name=group_name,
                committed=False,
                reason="unchanged",
                asset_id=str(asset.id),
                version_id=str(previous.id),
                previous_version_id=str(previous.id),
                content_hash=content_hash,
                line_count=n_lines,
            )

    payload = _canonical_group_payload(group)
    version_metadata = {
        "constraint_group_id": group_id,
        "content_hash": content_hash,
        "line_count": n_lines,
        "actor": str(actor or ""),
        "notes": str(notes or ""),
    }
    run = catalog.register_run(
        CONSTRAINT_COMMIT_OPERATION,
        input_version_ids=[str(previous.id)] if previous is not None else [],
        parameters={
            "constraint_group_id": group_id,
            "content_hash": content_hash,
            "n_lines": n_lines,
            "actor": str(actor or ""),
            "notes": str(notes or ""),
        },
        generator="constraint-lifecycle-v1",
        status="running",
    )
    payload_path = _write_payload(payload)
    try:
        if asset is None:
            # First commit: asset + version + run linkage in one atomic op.
            version = catalog.register_result_asset(
                name=f"constraints:{group_name or group_id}",
                type=CONSTRAINT_ASSET_TYPE,
                format="json",
                asset_metadata={
                    "constraint_group_id": group_id,
                    "group_name": group_name,
                    "target_horizon": str(getattr(group, "target_horizon", "") or ""),
                },
                source_path=payload_path,
                stage=DataStage.DERIVED,
                run_id=str(run.id),
                version_metadata=version_metadata,
            )
            asset_id = str(
                next(
                    a.id
                    for a in _constraint_assets(catalog)
                    if str(
                        dict(getattr(a, "metadata", None) or {}).get(
                            "constraint_group_id"
                        )
                        or ""
                    )
                    == group_id
                )
            )
        else:
            version = catalog.register_version(
                str(asset.id),
                payload_path,
                DataStage.DERIVED,
                parent_version_ids=[str(previous.id)]
                if previous is not None
                else [],
                run_id=str(run.id),
                metadata=version_metadata,
            )
            asset_id = str(asset.id)
    except Exception:
        catalog.update_run_status(str(run.id), "failed")
        raise
    catalog.update_run_status(str(run.id), "complete")
    return ConstraintCommitReport(
        group_id=group_id,
        group_name=group_name,
        committed=True,
        reason="changed",
        asset_id=asset_id,
        version_id=str(version.id),
        previous_version_id=str(previous.id) if previous is not None else None,
        run_id=str(run.id),
        content_hash=content_hash,
        line_count=n_lines,
    )


def commit_all_constraints(
    project: Any,
    catalog: DataCatalogService,
    *,
    actor: str = "",
    notes: str = "",
) -> list[ConstraintCommitReport]:
    """Commit every constraint group in the project document."""
    groups = list(getattr(project, "constraint_layers", None) or [])
    return [
        commit_constraint_group(project, catalog, group, actor=actor, notes=notes)
        for group in groups
    ]


def current_constraint_version(
    catalog: DataCatalogService, group_id: str
) -> Any | None:
    """Latest committed catalog version for a constraint group (None = never)."""
    asset = _asset_for_group(catalog, str(group_id))
    if asset is None:
        return None
    return _latest_version(catalog, str(asset.id))


def constraint_pins_for_task(
    task: Any, project: Any, catalog: DataCatalogService | None = None
) -> list[dict[str, Any]]:
    """Pin the constraint state a factor task is being computed against.

    Called at interpolation time. Each relevant group (matching the task's
    target horizon, or project-wide groups) pins its CURRENT content hash and
    the latest committed version id when a catalog is available (None keeps
    the pin honest: content known, version binding absent → UNKNOWN).
    """
    horizon = str(getattr(task, "target_horizon", "") or "")
    pins: list[dict[str, Any]] = []
    for group in getattr(project, "constraint_layers", None) or []:
        group_horizon = str(getattr(group, "target_horizon", "") or "")
        if horizon and group_horizon and group_horizon != horizon:
            continue
        content_hash, n_lines = constraint_group_content_hash(group)
        if n_lines == 0:
            continue
        version_id: str | None = None
        if catalog is not None:
            version = current_constraint_version(catalog, str(group.id))
            if version is not None:
                meta = dict(getattr(version, "metadata", None) or {})
                if str(meta.get("content_hash") or "") == content_hash:
                    version_id = str(version.id)
        pins.append(
            {
                "group_id": str(group.id),
                "group_name": str(getattr(group, "name", "") or ""),
                "content_hash": content_hash,
                "line_count": n_lines,
                "version_id": version_id,
            }
        )
    return pins


def pinned_constraint_pins(task: Any) -> list[dict[str, Any]]:
    """Recover the constraint pins recorded on a task (empty = none recorded)."""
    params = dict(getattr(task, "parameters", None) or {})
    pins = params.get("constraint_pins")
    if not isinstance(pins, list):
        return []
    return [dict(pin) for pin in pins if isinstance(pin, dict)]


def _version_by_content_hash(
    catalog: DataCatalogService, group_id: str, content_hash: str
) -> Any | None:
    """Latest committed version of a group whose content hash matches."""
    asset = _asset_for_group(catalog, str(group_id))
    if asset is None:
        return None
    matches = [
        v
        for v in (getattr(catalog.document, "versions", None) or [])
        if str(getattr(v, "asset_id", "") or "") == str(asset.id)
        and str(
            dict(getattr(v, "metadata", None) or {}).get("content_hash") or ""
        )
        == str(content_hash)
    ]
    if not matches:
        return None
    matches.sort(key=lambda v: (getattr(v, "version_number", 0) or 0))
    return matches[-1]


def constraint_pins_staleness(
    task: Any, project: Any, catalog: DataCatalogService | None = None
) -> dict[str, Any]:
    """Per-group freshness of a task's pinned constraints.

    ``state`` per group: ``current`` (document content == pin AND the pinned
    version is the latest commit), ``stale_content`` (the live document
    geometry changed since the pin — re-interpolation is dirty),
    ``stale_version`` (a NEWER commit exists), ``unknown`` (pin has no
    version binding / group vanished). Aggregate verdict never fabricates:
    unpinned groups are reported as ``unpinned``, not stale.

    Pins record a content hash at interpolation time (catalog access is not
    guaranteed there); the version binding resolves LAZILY here — the pin's
    hash identifies exactly one committed state (content-addressed), so a
    matching commit IS the pinned version, deterministically.
    """
    pins = pinned_constraint_pins(task)
    pin_by_group = {str(pin.get("group_id")): pin for pin in pins}
    task_horizon = str(getattr(task, "target_horizon", "") or "")
    groups = {}
    for group in getattr(project, "constraint_layers", None) or []:
        group_horizon = str(getattr(group, "target_horizon", "") or "")
        # Same dependency scoping as the pin itself: a group bound to a
        # different horizon is NOT a dependency of this task — it can never
        # make the task stale (nor count as unpinned for it).
        if task_horizon and group_horizon and group_horizon != task_horizon:
            continue
        groups[str(getattr(group, "id", "") or "")] = group
    entries: list[dict[str, Any]] = []
    for group_id, group in groups.items():
        content_hash, n_lines = constraint_group_content_hash(group)
        if n_lines == 0:
            continue
        pin = pin_by_group.get(group_id)
        if pin is None:
            entries.append(
                {"group_id": group_id, "state": "unpinned", "line_count": n_lines}
            )
            continue
        state = "current"
        detail = ""
        pinned_version: str | None = None
        if catalog is not None:
            # Late binding: the pin's content hash addresses the committed
            # version it was computed against.
            bound = _version_by_content_hash(
                catalog, group_id, str(pin.get("content_hash") or "")
            )
            pinned_version = str(bound.id) if bound is not None else None
        if str(pin.get("content_hash") or "") != content_hash:
            state = "stale_content"
            detail = "constraint geometry changed after this task was computed"
        elif catalog is not None:
            if pinned_version is None:
                state = "unknown"
                detail = (
                    "pin content was never committed — no version baseline "
                    "exists (commit the constraints to make this decidable)"
                )
            else:
                latest = current_constraint_version(catalog, group_id)
                if latest is not None and str(latest.id) != pinned_version:
                    state = "stale_version"
                    detail = (
                        f"pinned {pinned_version[:12]}… is not the latest "
                        f"commit {str(latest.id)[:12]}…"
                    )
        else:
            state = "unknown" if pin.get("version_id") is None else "current"
        entries.append(
            {
                "group_id": group_id,
                "state": state,
                "detail": detail,
                "pinned_version_id": pinned_version or pin.get("version_id"),
                "line_count": n_lines,
            }
        )
    # groups that vanished since the pin
    for group_id, pin in pin_by_group.items():
        if group_id not in groups:
            entries.append(
                {
                    "group_id": group_id,
                    "state": "missing",
                    "detail": "pinned constraint group no longer exists",
                    "pinned_version_id": pin.get("version_id"),
                }
            )
    worst = "current"
    rank = {"current": 0, "unpinned": 1, "unknown": 2, "missing": 3,
            "stale_version": 4, "stale_content": 5}
    for entry in entries:
        if rank.get(entry["state"], 2) > rank.get(worst, 0):
            worst = entry["state"]
    return {"state": worst, "groups": entries}


def compare_constraint_versions(
    catalog: DataCatalogService, version_a: str, version_b: str
) -> dict[str, Any]:
    """Line-level diff between two committed constraint versions.

    Lines are matched by ``line_id``; the diff reports added / removed /
    changed (geometry, role, active) lines with per-line content hashes so
    downstream tooling can attribute staleness to ONE edited constraint.
    """
    def _load(version_id: str) -> dict[str, Any]:
        version = catalog.get_version(version_id)
        source = getattr(version, "source_uri", "") or ""
        if not source:
            raise ValueError(
                f"constraint version {version_id!r} has no payload location"
            )
        return json.loads(Path(source).read_text(encoding="utf-8"))

    a = _load(version_a)
    b = _load(version_b)

    def _index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {line["line_id"]: line for line in payload.get("lines", [])}

    ia, ib = _index(a), _index(b)
    added = sorted(set(ib) - set(ia))
    removed = sorted(set(ia) - set(ib))
    changed: list[dict[str, Any]] = []
    unchanged = 0
    for line_id in sorted(set(ia) & set(ib)):
        if ia[line_id] == ib[line_id]:
            unchanged += 1
            continue
        changes = [
            key
            for key in ("coordinates", "role", "active", "azimuth_deg",
                        "semi_major", "semi_minor", "content_fingerprint")
            if ia[line_id].get(key) != ib[line_id].get(key)
        ]
        changed.append({"line_id": line_id, "changes": changes})

    def _hash(payload: dict[str, Any]) -> str:
        return _payload_hash(payload)

    return {
        "version_a": version_a,
        "version_b": version_b,
        "group_id_a": a.get("group_id"),
        "group_id_b": b.get("group_id"),
        "same_group": a.get("group_id") == b.get("group_id"),
        "content_hash_a": _hash(a),
        "content_hash_b": _hash(b),
        "lines_added": added,
        "lines_removed": removed,
        "lines_changed": changed,
        "lines_unchanged": unchanged,
        "identical": _hash(a) == _hash(b),
    }


def resolve_constraint_ref(
    project: Any, catalog: DataCatalogService | None, ref: str
) -> dict[str, Any]:
    """Resolve a compilation-input constraint ref to its freshness verdict.

    ``constraints:current`` — compares the live document content against the
    latest commit: CLEAN when equal, STALE when a commit exists and differs,
    UNKNOWN when nothing was ever committed (the pre-V8 honest state).
    ``constraints:<group_id>:<version_id>`` — pinned commit vs latest commit.
    """
    from paleo_workbench.mapping_workspace.dependencies import FreshnessStatus

    ref = str(ref or "")
    if ref == "constraints:current":
        groups = getattr(project, "constraint_layers", None) or []
        worst: str | None = None
        details: list[str] = []
        for group in groups:
            content_hash, n_lines = constraint_group_content_hash(group)
            if n_lines == 0:
                continue
            if catalog is None:
                worst = worst or "unknown"
                details.append(
                    f"{group.name or group.id}: no catalog — cannot compare"
                )
                continue
            latest = current_constraint_version(catalog, str(group.id))
            if latest is None:
                worst = worst or "unknown"
                details.append(
                    f"{group.name or group.id}: never committed — no baseline"
                )
                continue
            meta = dict(getattr(latest, "metadata", None) or {})
            if str(meta.get("content_hash") or "") == content_hash:
                details.append(f"{group.name or group.id}: matches latest commit")
            else:
                worst = "stale"
                details.append(
                    f"{group.name or group.id}: document content differs from "
                    f"latest commit {str(latest.id)[:12]}…"
                )
        status = {
            None: FreshnessStatus.CURRENT if details else FreshnessStatus.UNKNOWN,
            "unknown": FreshnessStatus.UNKNOWN,
            "stale": FreshnessStatus.STALE,
        }[worst]
        return {"status": status, "detail": "; ".join(details) or "no constraints"}

    if ref.startswith("constraints:"):
        parts = ref.split(":")
        group_id = parts[1] if len(parts) > 1 else ""
        version_id = parts[2] if len(parts) > 2 else ""
        if not version_id or catalog is None:
            return {
                "status": FreshnessStatus.UNKNOWN,
                "detail": "pinned constraint ref without version or catalog",
            }
        latest = current_constraint_version(catalog, group_id)
        if latest is None:
            return {
                "status": FreshnessStatus.UNKNOWN,
                "detail": f"constraint group {group_id!r} has no commits",
            }
        if str(latest.id) == version_id:
            return {"status": FreshnessStatus.CURRENT, "detail": "pinned commit is latest"}
        return {
            "status": FreshnessStatus.SUPERSEDED,
            "detail": (
                f"constraint group has a newer commit {str(latest.id)[:12]}… "
                f"(pinned {version_id[:12]}…)"
            ),
        }
    return {"status": FreshnessStatus.UNKNOWN, "detail": f"unrecognized ref {ref!r}"}
