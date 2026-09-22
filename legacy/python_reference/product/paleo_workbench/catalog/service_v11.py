"""V11 Data Fabric service surface — mixin over :class:`DataCatalogService`.

Kept in its own module purely for file size; the methods below are mixed into
``DataCatalogService`` (see ``service.py``) so the single-writer invariant,
locking discipline and dirty-set persistence are inherited, not duplicated.
There is exactly ONE catalog service class — this file adds API surface to it.

New capabilities (docs/development/data-fabric-v11/05, 06, 04):

- **Typed lineage ports** — :meth:`set_run_ports` is the single write entry
  that keeps ``input_ports``/``output_ports`` consistent with the flat
  ``input_version_ids``/``output_version_ids`` lists (ports ⊆ flat).
- **Compound (bundle) versions** — :meth:`register_bundle_version` places a
  member directory atomically, per-member checksums plus an aggregate;
  working copies of bundles copy/commit whole trees.
- **Pin (governance overlay)** — :meth:`pin_version` / :meth:`unpin_version`
  / :meth:`is_pinned`. Stored in ``version.metadata["pin"]`` — a governance
  mutation like ``trashed`` that never touches payload/path/sha identity.
- **Retention classes** — ``version.metadata["retention_class"]`` vocabulary
  plus cleanup-eligibility evaluation (double gate: policy AND downstream
  dependency).
- **Lifecycle status** — one read for stage/retention/pin/working-copy/
  downstream/recomputability that explain/impact/UI share.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING

from paleo_workbench.catalog.db import DirtySet
from paleo_workbench.catalog.models import (
    CatalogError,
    DataRun,
    DataStage,
    DataVersion,
    ImmutableVersionError,
    RunPort,
    VersionMember,
    aggregate_member_sha256,
)
from paleo_workbench.catalog.storage import working_dir_for
from paleo_workbench.project.models import _now_iso

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from paleo_workbench.catalog.service import DataCatalogService

# Retention vocabulary (05-version-lifecycle §3). Open-but-curated: unknown
# stored values read back verbatim and are treated conservatively ("retain")
# by eligibility evaluation.
RETENTION_CLASSES = ("cache", "recomputable", "retain", "user")

_DEFAULT_RETENTION_FOR_STAGE = {
    DataStage.RAW: "retain",
    DataStage.INTERMEDIATE: "recomputable",
    DataStage.DERIVED: "user",
    DataStage.OUTPUT: "user",
}

# Soft limits guarding pathological documents from turning into accidental
# filesystem walks (11-scale). Registrations exceeding them fail loudly.
MAX_BUNDLE_MEMBERS = 64
MAX_RUN_PORTS = 256


class DataFabricV11Mixin:
    """V11 API surface; mixed into ``DataCatalogService`` (single class)."""

    # ------------------------------------------------------------------
    # Typed lineage ports
    # ------------------------------------------------------------------

    def set_run_ports(
        self: "DataCatalogService",
        run_id: str,
        *,
        input_ports: Iterable[RunPort | dict[str, Any]] | None = None,
        output_ports: Iterable[RunPort | dict[str, Any]] | None = None,
    ) -> DataRun:
        """Replace a run's typed port bindings (single write entry).

        Invariants enforced here:

        - every port version id must reference a committed version AND be a
          member of the corresponding flat id list after this call (the flat
          lists are extended with any port id they lack — ports are a
          refinement of the flat lists, never a divergence);
        - port counts stay within :data:`MAX_RUN_PORTS`.

        Either or both directions may be given; a direction that is omitted
        keeps its existing ports untouched.
        """
        with self._lock:
            run = self.get_run(run_id)  # raises CatalogError when unknown
            self._apply_run_ports(
                run,
                input_ports=input_ports,
                output_ports=output_ports,
                validate_versions=True,
            )
            self._save(DirtySet(runs={run.id: None}))
            return run

    def _apply_run_ports(
        self: "DataCatalogService",
        run: DataRun,
        *,
        input_ports: Iterable[RunPort | dict[str, Any]] | None,
        output_ports: Iterable[RunPort | dict[str, Any]] | None,
        validate_versions: bool,
    ) -> None:
        """The ONE port-assignment core shared by every write entry
        (``set_run_ports``, ``register_run``, ``create_derived``).

        Maintains ports ⊆ flat io lists and the total port budget; version
        existence is validated when the ids come from callers (True) and
        skipped for freshly-built versions not yet in the maps (False).
        Only the directions actually given are replaced.
        """
        maps = self._ensure_maps() if validate_versions else None
        new_inputs = self._coerce_ports(input_ports, "input")
        new_outputs = self._coerce_ports(output_ports, "output")
        total = len(new_inputs) + len(new_outputs)
        if input_ports is None:
            total += len(run.input_ports)
        if output_ports is None:
            total += len(run.output_ports)
        if total > MAX_RUN_PORTS:
            raise CatalogError(
                f"Run {run.id} exceeds the port budget ({total} > {MAX_RUN_PORTS})"
            )
        for port in (*new_inputs, *new_outputs):
            if maps is not None and port.version_id not in maps.version_by_id:
                raise CatalogError(
                    f"Port references unknown version {port.version_id}"
                )
        if input_ports is not None:
            run.input_ports = new_inputs
            for port in new_inputs:
                if port.version_id not in run.input_version_ids:
                    run.input_version_ids.append(port.version_id)
        if output_ports is not None:
            run.output_ports = new_outputs
            for port in new_outputs:
                if port.version_id not in run.output_version_ids:
                    run.output_version_ids.append(port.version_id)

    @staticmethod
    def _coerce_ports(
        ports: Iterable[RunPort | dict[str, Any]] | None, direction: str
    ) -> list[RunPort]:
        if ports is None:
            return []
        out: list[RunPort] = []
        for item in ports:
            if isinstance(item, RunPort):
                out.append(item)
            elif isinstance(item, dict):
                out.append(RunPort(role=str(item.get("role", direction)), **{
                    key: value for key, value in item.items() if key != "role"
                }))
            else:
                raise CatalogError(f"Invalid port spec: {item!r}")
        return out

    def inputs_by_role(
        self: "DataCatalogService",
        run_id: str,
        role: str,
    ) -> list[RunPort]:
        """Ordered input port bindings for one role (docs 06 §4)."""
        ports = self.ports_for_run(run_id)
        return [p for p in ports["input"] if p.role == role]

    def runs_consuming(
        self: "DataCatalogService",
        *,
        role: str | None = None,
        version_id: str | None = None,
    ) -> list[DataRun]:
        """Runs whose INPUT ports match the role and/or version (docs 06 §4)."""
        maps = self._ensure_maps()
        out = []
        for run in maps.run_by_id.values():
            ports = list(run.input_ports)
            if not ports and version_id is not None and version_id in run.input_version_ids:
                out.append(run)  # legacy untyped run still counts as consuming
                continue
            for port in ports:
                if role is not None and port.role != role:
                    continue
                if version_id is not None and port.version_id != version_id:
                    continue
                out.append(run)
                break
        return out

    def ports_for_run(self: "DataCatalogService", run_id: str) -> dict[str, list[RunPort]]:
        """Typed ports of one run; anonymous ports synthesized for old runs."""
        run = self.get_run(run_id)
        inputs = list(run.input_ports) or [
            RunPort(role="input", version_id=vid, required=True)
            for vid in run.input_version_ids
        ]
        outputs = list(run.output_ports) or [
            RunPort(role="output", version_id=vid, required=True)
            for vid in run.output_version_ids
        ]
        return {"input": inputs, "output": outputs}

    # ------------------------------------------------------------------
    # Compound (bundle) versions
    # ------------------------------------------------------------------

    def register_bundle_version(
        self: "DataCatalogService",
        asset_id: str,
        source_dir: str | Path,
        stage: DataStage,
        *,
        member_specs: list[VersionMember] | None = None,
        parent_version_ids: Iterable[str] = (),
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        move: bool = False,
    ) -> DataVersion:
        """Commit a new compound (multi-file) version from *source_dir*.

        ``member_specs`` (optional) refine members with roles/ordinals/
        requiredness keyed by ``rel_path``; every regular file under
        *source_dir* becomes a member regardless (a bundle never silently
        drops files). Payload placement is atomic (all members or nothing),
        per-member checksums are recorded, and the version's ``sha256`` is
        the aggregate (:func:`aggregate_member_sha256`).
        """
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            raise CatalogError(f"Bundle source directory not found: {source_dir}")
        spec_by_rel: dict[str, VersionMember] = {}
        for spec in member_specs or ():
            rel = Path(spec.rel_path).as_posix()
            self._validate_member_rel_path(rel)
            if rel in spec_by_rel:
                raise CatalogError(f"Duplicate member rel_path: {rel}")
            spec_by_rel[rel] = spec
        # Spec sanity BEFORE any bytes move: every spec must name a real file
        # under the source dir (specs refine reality; they never invent it).
        source_files = {
            p.relative_to(source_dir).as_posix()
            for p in source_dir.rglob("*")
            if p.is_file()
        }
        if not source_files:
            raise CatalogError(f"Bundle source directory is empty: {source_dir}")
        unexpected = sorted(set(spec_by_rel) - source_files)
        if unexpected:
            raise CatalogError(f"Member specs reference missing files: {unexpected}")
        if len(source_files) > MAX_BUNDLE_MEMBERS:
            raise CatalogError(
                f"Bundle exceeds member budget"
                f" ({len(source_files)} > {MAX_BUNDLE_MEMBERS});"
                f" split the directory or import as separate assets"
            )
        # P1-4: member names are the version-scoped identity (SQLite PK) —
        # duplicates would silently drop rows in the index. ONE unified
        # used-name pool across spec names, bare names and rel-path
        # fallbacks (disjoint pools are how collisions sneaked through),
        # with a final hard assertion as the backstop.
        used_names: set[str] = set()
        auto_names: dict[str, str] = {}
        for rel in sorted(source_files):
            spec = spec_by_rel.get(rel)
            if spec is not None:
                if spec.name in used_names:
                    raise CatalogError(
                        f"Duplicate member name {spec.name!r} in specs"
                    )
                used_names.add(spec.name)
                continue
            for candidate in (Path(rel).name, rel):
                if candidate and candidate not in used_names:
                    used_names.add(candidate)
                    auto_names[rel] = candidate
                    break
            if rel not in auto_names:
                # bare name AND rel path both taken: numeric suffix
                base = Path(rel).name
                suffix = 2
                while f"{base}~{suffix}" in used_names:
                    suffix += 1
                auto_names[rel] = f"{base}~{suffix}"
                used_names.add(auto_names[rel])
        with self._lock:
            asset = self._asset_or_raise(asset_id)
            if run_id is not None:
                self.get_run(run_id)  # raises before any payload is placed
        from paleo_workbench.catalog.storage import (
            STAGE_DIRS,
            ensure_catalog_layout,
            place_managed_tree,
        )

        with self._payload_staging_lease(self._staging_target(stage, asset_id)):
            version = DataVersion(
                asset_id=asset.id,
                version_number=0,  # assigned at commit
                stage=stage,
                managed=True,
                source_uri=source_dir.resolve().as_posix(),
                format=asset.metadata.get("format", ""),
                parent_version_ids=list(parent_version_ids),
                run_id=run_id,
                metadata=dict(metadata or {}),
            )
            # Copy-then-delete (P1-2): a failed commit must leave the user's
            # source directory intact — move semantics that unlink during
            # placement destroy uncommitted edits when the metadata commit
            # is refused (e.g. the #411 cross-instance stale-write guard).
            placed = place_managed_tree(
                source_dir, self.project_path, stage, asset.id, version.id,
                keep_source=True,
            )
            # The version payload path is the member DIRECTORY, derived from
            # the authoritative layout — NEVER from the sorted file list
            # (P1-1: the alphabetically-first member can live in a
            # subdirectory, which used to corrupt every derived path).
            project_dir = Path(self.project_path).expanduser().resolve().parent
            version_dir_rel = (
                ensure_catalog_layout(Path(self.project_path))
                / STAGE_DIRS[stage]
                / asset.id
                / version.id
            ).relative_to(project_dir).as_posix()
            prefix = version_dir_rel + "/"
            members: list[VersionMember] = []
            for ordinal, (file_rel, digest, size) in enumerate(placed):
                member_rel = file_rel[len(prefix):]
                spec = spec_by_rel.get(member_rel)
                members.append(
                    VersionMember(
                        name=spec.name if spec else auto_names.get(member_rel, Path(member_rel).name),
                        rel_path=member_rel,
                        member_role=spec.member_role if spec else "",
                        ordinal=spec.ordinal if spec else ordinal,
                        required=spec.required if spec else True,
                        sha256=digest,
                        size_bytes=size,
                    )
                )
            member_names = [m.name for m in members]
            if len(set(member_names)) != len(member_names):
                raise CatalogError(
                    "Bundle member names are not unique (internal error)"
                )
            version.members = members
            version.path = version_dir_rel
            version.size_bytes = sum(m.size_bytes or 0 for m in members)
            version.sha256 = aggregate_member_sha256(members)
            with self._lock:
                try:
                    asset = self._asset_or_raise(asset_id)
                except CatalogError:
                    self._rollback_bundle(version_dir_rel)
                    raise
                if any(v.id == version.id for v in self.document.versions):
                    self._rollback_bundle(version_dir_rel)
                    raise ImmutableVersionError(
                        f"Version {version.id} is already committed and immutable"
                    )
                run: DataRun | None = None
                if run_id is not None:
                    try:
                        run = self.get_run(run_id)
                    except CatalogError:
                        self._rollback_bundle(version_dir_rel)
                        raise
                version.version_number = self._next_version_number(asset.id)
                previous_current = asset.current_version_id
                self._add_version(version)
                asset.current_version_id = version.id
                run_output_added = False
                if run is not None and version.id not in run.output_version_ids:
                    run.output_version_ids.append(version.id)
                    run_output_added = True
                dirty = DirtySet(assets={asset.id: None}, versions={version.id: None})
                if run is not None:
                    dirty.mark_runs(run.id)
                try:
                    self._save(dirty)
                except Exception:
                    if run is not None and run_output_added:
                        run.output_version_ids.remove(version.id)
                    self._remove_version(version)
                    asset.current_version_id = previous_current
                    self._rollback_bundle(version_dir_rel)
                    raise
                if move:
                    # Only now (metadata committed) is it safe to consume the
                    # source directory — the copy-then-delete half of P1-2.
                    shutil.rmtree(source_dir, ignore_errors=True)
                return version

    def _rollback_bundle(self: "DataCatalogService", version_dir_rel: str) -> None:
        project_dir = Path(self.project_path).expanduser().resolve().parent
        shutil.rmtree(project_dir / version_dir_rel, ignore_errors=True)

    @staticmethod
    def _validate_member_rel_path(rel_path: str) -> None:
        candidate = Path(rel_path)
        if candidate.is_absolute() or ".." in candidate.parts or not rel_path:
            raise CatalogError(
                f"Unsafe member rel_path {rel_path!r}: must stay inside the"
                " version payload directory"
            )

    def member_path(self: "DataCatalogService", version_id: str, member: VersionMember | str) -> Path:
        """Absolute path of one bundle member (validated to stay in-bounds)."""
        version = self._version_or_raise(version_id)
        rel = member.rel_path if isinstance(member, VersionMember) else str(member)
        self._validate_member_rel_path(rel)
        base = self.resolve_path(version)
        return base / rel

    def verify_bundle_integrity(self: "DataCatalogService", version_id: str) -> dict[str, Any]:
        """Per-member + aggregate integrity report for a bundle version."""
        from paleo_workbench.catalog.checksum import sha256_file

        version = self._version_or_raise(version_id)
        if not version.members:
            return {"bundle": False, "status": "unknown"}
        report: dict[str, Any] = {"bundle": True, "members": [], "status": "verified"}
        worst = "verified"
        rank = {"verified": 0, "unknown": 1, "modified": 2, "missing": 3}
        for member in version.members:
            path = self.member_path(version_id, member)
            entry: dict[str, Any] = {
                "name": member.name,
                "rel_path": member.rel_path,
                "status": "unknown",
            }
            if not path.is_file():
                entry["status"] = "missing"
            else:
                digest = sha256_file(path)
                if member.sha256 is None:
                    entry["status"] = "unknown"
                elif digest != member.sha256:
                    entry["status"] = "modified"
                    entry["actual_sha256"] = digest
                else:
                    entry["status"] = "verified"
            if rank[entry["status"]] > rank[worst]:
                worst = entry["status"]
            report["members"].append(entry)
        if worst == "verified":
            recomputed = aggregate_member_sha256(version.members)
            if recomputed is not None and version.sha256 not in (None, recomputed):
                worst = "modified"
        report["status"] = worst
        return report

    def create_bundle_working_copy(
        self: "DataCatalogService", version_id: str, *, allow_replace: bool = False
    ) -> Path:
        """Check out a whole bundle version as a mutable directory copy."""
        version = self._version_or_raise(version_id)
        if not version.members:
            raise CatalogError(f"Version {version_id} is not a bundle")
        live = None
        try:
            live = self._index.get_live_working_copy_for_source(version.id)
        except Exception:
            live = None
        payload_dir = self.resolve_path(version)
        if not payload_dir.is_dir():
            raise CatalogError(f"Bundle payload not available: {payload_dir}")
        project_dir = Path(self.project_path).expanduser().resolve().parent
        if live is not None:
            existing = project_dir / live["path"]
            if existing.is_dir():
                if not allow_replace:
                    return existing
                shutil.rmtree(existing, ignore_errors=True)
                try:
                    self._index.remove_working_copy(live["working_id"])
                except Exception:
                    pass
            else:
                try:
                    self._index.remove_working_copy(live["working_id"])
                except Exception:
                    pass
        target_dir = working_dir_for(Path(self.project_path)) / version.id
        if target_dir.exists() and any(target_dir.iterdir()) and not allow_replace:
            return target_dir
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy member-by-member (writable), preserving relative layout.
        for member in version.members:
            src = self.member_path(version_id, member)
            dst = target_dir / member.rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        try:
            rel = target_dir.relative_to(project_dir).as_posix()
            self._index.register_working_copy(
                source_version_id=version.id,
                path=rel,
                display_name=target_dir.name,
                payload_mtime_ns=None,
                # Directory stat size is metadata noise, not payload size —
                # leaving source_size_bytes None keeps the registry's dirty
                # hint from crying wolf on every bundle checkout.
                source_size_bytes=None,
            )
        except Exception:
            pass  # registry is lifecycle bookkeeping, never a checkout gate
        return target_dir

    def commit_bundle_working_copy(
        self: "DataCatalogService",
        working_dir: str | Path,
        *,
        asset_id: str | None = None,
        name: str | None = None,
        stage: DataStage = DataStage.DERIVED,
        parent_version_ids: Iterable[str] | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataVersion:
        """Promote a bundle working-copy directory to a new immutable version."""
        working_dir = Path(working_dir)
        if not working_dir.is_dir():
            raise CatalogError(f"Working directory not found: {working_dir}")
        wc_row = self.working_copy_state(working_dir)
        if parent_version_ids is None:
            parent = wc_row["source_version_id"] if wc_row else None
            parent_version_ids = [parent] if parent else []
        working_id = wc_row["working_id"] if wc_row else None
        if working_id is not None:
            try:
                self._index.update_working_copy_state(working_id, "committing")
            except Exception:
                pass
        try:
            if asset_id is None:
                asset_name = name or working_dir.name
                with self._lock:
                    asset = self._new_asset(asset_name, None, None, metadata)
                    self._add_asset(asset)
                    self._pending_commit_assets.add(asset.id)
                try:
                    committed = self.register_bundle_version(
                        asset.id, working_dir, stage,
                        parent_version_ids=parent_version_ids,
                        run_id=run_id, metadata=metadata, move=True,
                    )
                except Exception:
                    with self._lock:
                        if asset in self.document.assets:
                            self._remove_asset(asset)
                    raise
                finally:
                    with self._lock:
                        self._pending_commit_assets.discard(asset.id)
            else:
                committed = self.register_bundle_version(
                    asset_id, working_dir, stage,
                    parent_version_ids=parent_version_ids,
                    run_id=run_id, metadata=metadata, move=True,
                )
        except Exception:
            if working_id is not None:
                try:
                    self._index.update_working_copy_state(working_id, "dirty")
                except Exception:
                    pass
            raise
        if working_id is not None:
            try:
                self._index.remove_working_copy(working_id)
            except Exception:
                pass
        return committed

    # ------------------------------------------------------------------
    # Pin (governance overlay)
    # ------------------------------------------------------------------

    def pin_version(self: "DataCatalogService", version_id: str, reason: str = "") -> DataVersion:
        """Pin a version: cleanup-blocked and staleness-exempt ("pinned to a
        known-old input by decision", not "wrong")."""
        with self._lock:
            version = self._version_or_raise(version_id)
            version.metadata["pin"] = {"reason": str(reason or ""), "pinned_at": _now_iso()}
            self._save(DirtySet(versions={version.id: None}))
            return version

    def unpin_version(self: "DataCatalogService", version_id: str) -> DataVersion:
        with self._lock:
            version = self._version_or_raise(version_id)
            if "pin" in version.metadata:
                del version.metadata["pin"]
                self._save(DirtySet(versions={version.id: None}))
            return version

    def is_pinned(self: "DataCatalogService", version_id: str) -> bool:
        try:
            version = self.get_version(version_id)
        except CatalogError:
            return False
        pin = version.metadata.get("pin")
        return isinstance(pin, dict) and bool(pin)

    # ------------------------------------------------------------------
    # Retention classes & cleanup eligibility
    # ------------------------------------------------------------------

    def set_retention_class(
        self: "DataCatalogService", version_id: str, retention_class: str
    ) -> DataVersion:
        """Assign/override a version's retention class (policy metadata)."""
        if retention_class not in RETENTION_CLASSES:
            raise CatalogError(
                f"Unknown retention class {retention_class!r};"
                f" expected one of {RETENTION_CLASSES}"
            )
        with self._lock:
            version = self._version_or_raise(version_id)
            version.metadata["retention_class"] = retention_class
            self._save(DirtySet(versions={version.id: None}))
            return version

    def retention_class(self: "DataCatalogService", version_id: str) -> str:
        """Effective retention class: explicit assignment, else stage default."""
        try:
            version = self.get_version(version_id)
        except CatalogError:
            return "retain"
        stored = version.metadata.get("retention_class")
        if isinstance(stored, str) and stored in RETENTION_CLASSES:
            return stored
        # Unknown stored values are treated conservatively.
        if isinstance(stored, str) and stored:
            return "retain"
        return _DEFAULT_RETENTION_FOR_STAGE.get(version.stage, "retain")

    def cleanup_eligibility(self: "DataCatalogService", version_id: str) -> dict[str, Any]:
        """Double-gate cleanup evaluation: policy class AND dependencies.

        A version is cleanup-eligible only when its retention class allows
        deletion AND nothing depends on it (downstream lineage, pin, live
        working copy). RAW is never eligible (source of truth by contract).
        """
        version = self._version_or_raise(version_id)
        blockers: list[str] = []
        klass = self.retention_class(version_id)
        if klass in ("retain", "user"):
            blockers.append(f"retention_class={klass}")
        if version.stage is DataStage.RAW:
            blockers.append("raw_stage")
        if self.is_pinned(version_id):
            blockers.append("pinned")
        maps = self._ensure_maps()
        live_children = [
            child.id
            for child in maps.children_by_parent.get(version.id, ())
            if not child.trashed
        ]
        if live_children:
            blockers.append(f"downstream_versions={len(live_children)}")
        # Note: runs CONSUMING this version are provenance, not blockers —
        # they reference history; the payload dependency is the child edges.
        try:
            live_wc = self._index.get_live_working_copy_for_source(version_id)
        except Exception:
            live_wc = None
        if live_wc is not None:
            blockers.append("live_working_copy")
        if version.trashed:
            blockers.append("already_trashed")
        return {
            "version_id": version_id,
            "eligible": not blockers,
            "blockers": blockers,
            "retention_class": klass,
            "downstream_count": len(live_children),
        }

    # ------------------------------------------------------------------
    # Lifecycle status (shared read for explain / impact / UI)
    # ------------------------------------------------------------------

    def version_lifecycle_status(self: "DataCatalogService", version_id: str) -> dict[str, Any]:
        version = self._version_or_raise(version_id)
        maps = self._ensure_maps()
        producing_run = maps.run_by_id.get(version.run_id) if version.run_id else None
        dependent_runs = [
            run for run in maps.run_by_id.values()
            if version.id in run.input_version_ids
        ]
        try:
            live_wc = self._index.get_live_working_copy_for_source(version_id)
        except Exception:
            live_wc = None
        return {
            "version_id": version_id,
            "asset_id": version.asset_id,
            "stage": version.stage.value,
            "bundle": bool(version.members),
            "member_count": len(version.members),
            "retention_class": self.retention_class(version_id),
            "pinned": self.is_pinned(version_id),
            "trashed": version.trashed,
            "live_working_copy": bool(live_wc),
            "producing_run_id": version.run_id,
            "producing_operation": producing_run.operation if producing_run else None,
            "recomputable": producing_run is not None,
            "dependent_run_count": len(dependent_runs),
            "downstream_count": len(maps.children_by_parent.get(version.id, ())),
        }

    # ------------------------------------------------------------------
    # Heuristic port backfill (docs 06 §5 / 10 §3.2)
    # ------------------------------------------------------------------

    # Operation → output port role. ONLY output roles are derivable from
    # operation semantics; which historical input played sonic vs density is
    # NOT recoverable, so inputs stay anonymous (honesty over completeness).
    _OPERATION_OUTPUT_ROLES = {
        "prediction": "prediction",
        "factor_map": "factor_grid",
        "factor_fusion": "fusion_result",
        "map_compile": "map_product",
        "time_depth_calibration": "calibrated_td",
        "stratigraphic_correlation": "correlation",
        "fault_interpretation": "interpretation",
        "horizon_interpretation": "interpretation",
        "qc": "qc_report",
        "export": "export",
    }

    def migrate_run_ports(self: "DataCatalogService") -> dict[str, int]:
        """One-time, idempotent output-port backfill for pre-V11 runs.

        Deterministic: a run's output role comes from a fixed
        operation→role table over the run's own metadata. Runs that already
        carry ports are untouched; unknown operations are left anonymous.
        Returns counts ({"runs_annotated": n, "ports_added": m}).
        """
        annotated = 0
        added = 0
        with self._lock:
            maps = self._ensure_maps()
            touched: list[DataRun] = []
            for run in maps.run_by_id.values():
                if run.output_ports:
                    continue
                role = self._OPERATION_OUTPUT_ROLES.get(run.operation)
                if role is None:
                    continue
                known_outputs = [
                    vid for vid in run.output_version_ids
                    if vid in maps.version_by_id
                ]
                if not known_outputs:
                    continue
                run.output_ports = [
                    RunPort(role=role, version_id=vid, ordinal=ordinal)
                    for ordinal, vid in enumerate(known_outputs)
                ]
                annotated += 1
                added += len(run.output_ports)
                touched.append(run)
            if touched:
                dirty = DirtySet()
                for run in touched:
                    dirty.mark_runs(run.id)
                self._save(dirty)
        return {"runs_annotated": annotated, "ports_added": added}
