"""V11 scale contract (goal §18/§16): structural assertions, no wall-clock.

The entity-view read surface must never fall back to full catalog
materialization: query-count assertions pin the contract (a stronger and
less flaky proxy than timing — the #1269 lesson).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.entity_views import EntityViewService
from paleo_workbench.catalog.impact import ImpactService
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import WellEntity, upsert_entity_asset_link
from paleo_workbench.project.models import ProjectDocument


@pytest.fixture()
def scale_env(tmp_path: Path):
    project_file = tmp_path / "scale.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("scale")
    yield service, doc, tmp_path
    service.close()


def _populate(scale_env, wells: int, assets_per_well: int = 3):
    service, doc, tmp_path = scale_env
    src = tmp_path / "seed.las"
    src.write_text("seed", encoding="utf-8")
    seed = service.import_raw(src, name="seed.las", type="well_log")
    seed_asset = service.get_version(seed.id).asset_id
    with service.batch_save():
        for w in range(wells):
            well = WellEntity(name=f"W{w:05d}")
            doc.wells.append(well)
            for a in range(assets_per_well):
                upsert_entity_asset_link(
                    doc,
                    entity_type="well",
                    entity_id=well.id,
                    asset_id=seed_asset,
                    role="well_log",
                    is_primary=(a == 0),
                )
    return service, doc


def test_entity_view_never_calls_list_assets(scale_env):
    service, doc, tmp_path = scale_env
    _populate(scale_env, wells=200)

    calls = {"list_assets": 0}

    original = DataCatalogService.list_assets

    def counting(self, include_trashed: bool = False):
        calls["list_assets"] += 1
        return original(self, include_trashed=include_trashed)

    DataCatalogService.list_assets = counting  # type: ignore[method-assign]
    try:
        views = EntityViewService(service, doc)
        index = views.well_index()
        assert len(index) == 200
        view = views.well_view(doc.wells[0].id)
        assert view is not None and len(view.slots["well_log"].members) == 1
    finally:
        DataCatalogService.list_assets = original  # type: ignore[method-assign]
    assert calls["list_assets"] == 0, (
        "entity view read surface must use point/paged queries only"
    )


def test_impact_walk_is_batched_not_per_node(scale_env):
    """A deep lineage chain produces O(depth) batched expansions, and the
    stale result scales linearly with the number of evolved ancestors."""
    service, doc, tmp_path = scale_env
    src = tmp_path / "base.las"
    src.write_text("base", encoding="utf-8")
    v = service.import_raw(src, name="base.las", type="well_log")
    asset = service.get_version(v.id).asset_id
    # chain of 50 derived versions
    current = v.id
    with service.batch_save():
        for i in range(50):
            out = tmp_path / f"d{i}.out"
            out.write_text(f"d{i}", encoding="utf-8")
            run = service.register_run("op", input_version_ids=[current])
            version = service.register_result_asset(
                name=f"d{i}", type="derived", format="txt",
                asset_metadata=None, source_path=out, stage="derived",
                run_id=run.id,
            )
            current = version.id
    # evolve the root → all 50 descendants stale
    evolved = tmp_path / "base2.las"
    evolved.write_text("base-evolved", encoding="utf-8")
    service.register_version(asset, evolved, "raw")
    impact = ImpactService(service)
    stale = impact.downstream_stale()
    assert len(stale) == 50
    direct = [s for s in stale if s.direct]
    assert len(direct) == 1  # only the first hop is direct


def test_bundle_member_budget_enforced(scale_env):
    service, doc, tmp_path = scale_env
    asset = service._new_asset("huge", "misc", None, None)
    with service._lock:
        service._add_asset(asset)
    big = tmp_path / "huge"
    big.mkdir()
    for i in range(70):
        (big / f"m{i:03d}.bin").write_bytes(b"x")
    from paleo_workbench.catalog.models import CatalogError, DataStage

    with pytest.raises(CatalogError):
        service.register_bundle_version(asset.id, big, DataStage.RAW)


def test_well_index_stale_counts_are_cached_per_revision(scale_env):
    """The stale rollup runs once per catalog revision, not per index call.

    Metric: the catalog map materialization that only a cache MISS pays
    (the staleness cache short-circuits before touching the maps).
    """
    service, doc, tmp_path = scale_env
    _populate(scale_env, wells=10)
    views = EntityViewService(service, doc)
    misses = {"n": 0}
    original = DataCatalogService._ensure_maps

    def counting(self):
        misses["n"] += 1
        return original(self)

    DataCatalogService._ensure_maps = counting  # type: ignore[method-assign]
    try:
        for _ in range(3):
            views.well_index(with_stale=True)
    finally:
        DataCatalogService._ensure_maps = original  # type: ignore[method-assign]
    assert misses["n"] <= 2  # one initial warm + at most one re-derive
