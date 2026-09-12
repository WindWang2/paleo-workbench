"""Edit sessions — business-object level orchestration over working copies.

V11 (docs/development/data-fabric-v11/05 §2). Deliberately STATELESS: an
edit session is not a second persistence layer — it groups the existing
per-file working-copy registry (``working_copies`` table, #1211/#1232) by
the business object being edited (entity + role). Crash recovery, discard
and commit semantics remain exactly those of the underlying registry, so
there is one recovery story, not two.

Typical flow::

    session = open_edit_session(service, project, "well", well_id, "tops")
    path    = session.primary_path()          # editable copy of active tops
    ... user edits (external tool or in-app) ...
    session.commit(new_name="tops edited")    # → new immutable versions
    # or: session.cancel()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from paleo_workbench.catalog.models import CatalogError, DataStage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.service import DataCatalogService


@dataclass
class CheckoutRef:
    working_id: str
    source_version_id: str
    path: Path
    state: str
    dirty_hint: bool
    asset_id: str
    asset_name: str


@dataclass
class EditSessionReport:
    committed_version_ids: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def open_edit_session(
    service: "DataCatalogService",
    project: Any,
    entity_type: str,
    entity_id: str,
    role: str,
    *,
    stage: DataStage = DataStage.DERIVED,
) -> "EditSession":
    """Check out the entity's primary (or sole) asset current version.

    Live uncommitted copies are REUSED (never clobbered — the #1211
    contract). When the role has no primary yet but exactly one member,
    that member is used; empty roles raise a honest error.
    """
    from paleo_workbench.project.domain import links_for_entity

    links = [
        link
        for link in links_for_entity(project, entity_type, entity_id)
        if link.role == role and not link.unresolved
    ]
    if not links:
        raise CatalogError(
            f"实体 {entity_id} 没有角色 {role} 的资产，无法开启编辑会话"
        )
    primary = next((link for link in links if link.is_primary), links[0])
    maps = service._ensure_maps()
    version_id = None
    asset = maps.asset_by_id.get(primary.asset_id)
    if asset is None:
        raise CatalogError(f"资产 {primary.asset_id} 不在目录中")
    if asset.current_version_id:
        version_id = asset.current_version_id
    else:
        versions = maps.versions_by_asset.get(asset.id, ())
        if not versions:
            raise CatalogError(f"资产 {asset.name} 没有任何版本")
        version_id = versions[-1].id
    # Bundle versions check out as whole directories; single-file versions
    # as plain file copies (both registries share the working_copies table).
    version = service.get_version(version_id)
    if version.members:
        working_path = service.create_bundle_working_copy(version_id)
    else:
        working_path = service.create_working_copy(version_id)
    return EditSession(
        service=service,
        entity_type=entity_type,
        entity_id=entity_id,
        role=role,
        stage=stage,
        checkouts=[
            CheckoutRef(
                working_id="",
                source_version_id=version_id,
                path=working_path,
                state="checked_out",
                dirty_hint=False,
                asset_id=asset.id,
                asset_name=asset.name,
            )
        ],
    )


class EditSession:
    """A group of working copies being edited as one business object."""

    def __init__(
        self,
        *,
        service: "DataCatalogService",
        entity_type: str,
        entity_id: str,
        role: str,
        stage: DataStage,
        checkouts: list[CheckoutRef],
    ):
        self._service = service
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.role = role
        self.stage = stage
        self.checkouts = checkouts

    def primary_path(self) -> Path:
        return self.checkouts[0].path

    def _refresh_registry_state(self) -> None:
        for checkout in self.checkouts:
            status = self._service.working_copy_state(checkout.path)
            if status is not None:
                checkout.working_id = status["working_id"]
                checkout.state = status["state"]
                checkout.dirty_hint = bool(status.get("dirty_hint"))

    def status(self) -> dict[str, Any]:
        self._refresh_registry_state()
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "role": self.role,
            "checkouts": [
                {
                    "working_id": c.working_id,
                    "source_version_id": c.source_version_id,
                    "path": str(c.path),
                    "state": c.state,
                    "dirty_hint": c.dirty_hint,
                    "asset_name": c.asset_name,
                }
                for c in self.checkouts
            ],
        }

    def commit(
        self,
        *,
        new_name: str | None = None,
        as_new_asset: bool = False,
    ) -> EditSessionReport:
        """Promote every checkout to a new immutable version.

        Per-file commits are individually atomic; a mid-session failure keeps
        already-committed files committed and reports the split honestly
        (a session is a macro, not a transaction — commit_working_copy owns
        atomicity at the version level).
        """
        report = EditSessionReport()
        self._refresh_registry_state()
        for checkout in self.checkouts:
            try:
                source_version = self._service.get_version(checkout.source_version_id)
                if source_version is not None and source_version.members:
                    version = self._service.commit_bundle_working_copy(
                        checkout.path,
                        asset_id=None if as_new_asset else checkout.asset_id,
                        name=new_name or checkout.asset_name,
                        stage=self.stage,
                        parent_version_ids=[checkout.source_version_id],
                    )
                else:
                    version = self._service.commit_working_copy(
                        checkout.path,
                        asset_id=None if as_new_asset else checkout.asset_id,
                        name=new_name or checkout.asset_name,
                        stage=self.stage,
                        parent_version_ids=[checkout.source_version_id],
                    )
                report.committed_version_ids.append(version.id)
            except CatalogError as exc:
                report.issues.append(
                    f"{checkout.asset_name}: 提交失败 — {exc}"
                )
            except Exception as exc:  # pragma: no cover - defensive
                report.issues.append(
                    f"{checkout.asset_name}: 提交异常 — {exc.__class__.__name__}: {exc}"
                )
        return report

    def cancel(self) -> EditSessionReport:
        """Discard every checkout (explicit abandon — the only sanctioned
        way to destroy uncommitted edits besides committing)."""
        report = EditSessionReport()
        for checkout in self.checkouts:
            try:
                if self._service.discard_working_copy(checkout.path):
                    report.cancelled.append(str(checkout.path))
            except CatalogError as exc:
                report.issues.append(f"{checkout.asset_name}: 丢弃失败 — {exc}")
        return report
