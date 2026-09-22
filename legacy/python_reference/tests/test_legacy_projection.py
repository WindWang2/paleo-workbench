"""#1032 — legacy ``resources[]`` projection invariants.

The remove/restore/derive UI paths used to hand-maintain
``ProjectDocument.resources`` next to every catalog mutation, each site with
its own id filtering rule. These tests pin the single projection module that
owns the boundary: catalog-authoritative, bridge-id based, idempotent.
"""

from __future__ import annotations

import pytest

from paleo_workbench.catalog.legacy_projection import (
    legacy_bridge_id,
    remove_legacy_resources_by_ids,
    remove_legacy_resources_for_assets,
    upsert_legacy_resource,
)
from paleo_workbench.catalog.models import DataAsset
from paleo_workbench.project.models import ProjectDocument, ProjectMeta, ResourceItem


def _project() -> ProjectDocument:
    return ProjectDocument(meta=ProjectMeta(name="proj"))


def _resource(rid: str, name: str = "") -> ResourceItem:
    return ResourceItem(
        id=rid,
        name=name or rid,
        path=f"/data/{rid}",
        type="well_log",
        format="las",
    )


def _asset(asset_id: str, legacy_id: str | None = None) -> DataAsset:
    return DataAsset.model_construct(
        id=asset_id,
        name=asset_id,
        type="well_log",
        legacy_resource_id=legacy_id,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def test_bridge_id_prefers_legacy_resource_id():
    assert legacy_bridge_id(_asset("a1", legacy_id="res-9")) == "res-9"
    assert legacy_bridge_id(_asset("a2")) == "a2"


def test_remove_for_assets_drops_mirrored_rows_by_bridge_id():
    project = _project()
    project.resources.append(_resource("res-9"))
    project.resources.append(_resource("keep-me"))

    removed = remove_legacy_resources_for_assets(project, [_asset("a1", "res-9")])

    assert removed == 1
    assert [r.id for r in project.resources] == ["keep-me"]


def test_remove_for_assets_is_noop_without_claimants():
    project = _project()
    project.resources.append(_resource("res-1"))
    assert remove_legacy_resources_for_assets(project, []) == 0
    assert remove_legacy_resources_for_assets(project, [_asset("unrelated", None)]) == 0
    assert len(project.resources) == 1


def test_remove_by_ids_covers_export_artifacts_in_one_pass():
    project = _project()
    project.resources.append(_resource("r1"))
    project.resources.append(_resource("r2"))
    art = _resource("r2")
    project.export_artifacts.append(art)

    removed = remove_legacy_resources_by_ids(project, {"r2"})

    assert removed == 2
    assert [r.id for r in project.resources] == ["r1"]
    assert project.export_artifacts == []


def test_upsert_appends_then_replaces_idempotently():
    project = _project()
    first = _resource("dup", "old name")
    assert upsert_legacy_resource(project, first) is True

    second = _resource("dup", "fresh from catalog")
    assert upsert_legacy_resource(project, second) is True
    assert len(project.resources) == 1
    assert project.resources[0].name == "fresh from catalog"

    # a builder failure must never inject a half-companion
    assert upsert_legacy_resource(project, None) is False
    assert len(project.resources) == 1


def test_remove_then_restore_roundtrip_preserves_single_row():
    project = _project()
    project.resources.append(_resource("res-1"))
    asset = _asset("a-1", "res-1")

    remove_legacy_resources_for_assets(project, [asset])
    assert project.resources == []

    restored = _resource("res-1", "restored")
    upsert_legacy_resource(project, restored)
    remove_legacy_resources_for_assets(project, [asset])  # re-remove
    upsert_legacy_resource(project, restored)  # re-surface
    assert len(project.resources) == 1
    assert project.resources[0] is restored


def test_divergent_bridge_id_still_removes_legacy_row():
    """The divergence #1032 describes: asset id != legacy id. Deriving the
    removal set from the *catalog* entities (not a parallel UI id set) must
    still drop the right legacy row."""
    project = _project()
    project.resources.append(_resource("legacy-x"))
    # catalog knows the asset under a fresh id, bridged to legacy-x
    remove_legacy_resources_for_assets(project, [_asset("cat-new-id", "legacy-x")])
    assert project.resources == []
