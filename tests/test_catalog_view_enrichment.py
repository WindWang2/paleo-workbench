"""Issues #1173 / #1171 — data-view enrichment caches (catalog-driven rows).

#1173: ``enrich_view_from_catalog`` rebuilt tag_by_id + version_tag_map
(O(tags + associations)) on EVERY call — and the data page calls it per row
selection. The maps are now cached at module level keyed on document
identity + catalog revision + the service's mutation serial.

#1171: per-asset integrity probes (``resolve_path`` + ``is_file``) and the
export-artifact view (exists + is_file + stat = three syscalls) now route
through the shared ``FsProbeCache`` — one stat per distinct path within a
refresh, consistent results within one materialization.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import ExportArtifact
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    FsProbeCache,
    IntegrityState,
    LineageView,
    _catalog_tag_maps,
    asset_view_from_artifact,
    enrich_view_from_catalog,
)


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path: Path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _make_source(tmp_path: Path, name: str) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(f"payload-{name}".encode())
    return src


def _base_view(asset_id: str) -> AssetView:
    return AssetView(
        id=asset_id,
        name="n",
        type="well_log",
        type_label="测井",
        format="las",
        stage=DataStage.RAW,
        current_version="v1",
        versions=[],
        tags=[],
        managed=True,
        integrity_state=IntegrityState.UNKNOWN,
        checksum=None,
        path="x",
        size_bytes=None,
        size_formatted="—",
        created_at="—",
        modified_at="—",
        source="local",
        lineage=LineageView(),
    )


# ------------------------------------------------------------------- #1173


def test_tag_maps_cached_across_calls_invalidated_on_change(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path, "t.las"))
    service.add_tags(["one", "two"], version_id=v.id)

    maps_a = _catalog_tag_maps(service)
    maps_b = _catalog_tag_maps(service)
    assert maps_a[0] is maps_b[0], "tag_by_id rebuilt between identical calls"
    assert maps_a[1] is maps_b[1], "version_tag_map rebuilt between identical calls"
    assert maps_a[1][v.id] == ["one", "two"]

    # A tag mutation (revision + serial bump) invalidates the cache.
    service.add_tag("three", version_id=v.id)
    maps_c = _catalog_tag_maps(service)
    assert maps_c[0] is not maps_a[0]
    assert maps_c[1][v.id] == ["one", "two", "three"]


def test_tag_maps_invalidate_inside_batch(service, tmp_path):
    """Mutations deferred inside batch_save hold the revision until commit;
    the mutation serial still invalidates the cache (#1139 + #1173)."""
    v = service.import_raw(_make_source(tmp_path, "b.las"))
    maps_before = _catalog_tag_maps(service)
    with service.batch_save():
        service.add_tag("in-batch", version_id=v.id)
        maps_mid = _catalog_tag_maps(service)
    assert maps_mid[0] is not maps_before[0]
    assert "in-batch" in maps_mid[1][v.id]


def test_enrich_view_uses_cached_maps(service, tmp_path, monkeypatch):
    """enrich_view_from_catalog serves version tags from the shared cache."""
    v = service.import_raw(_make_source(tmp_path, "e.las"))
    service.add_tags(["enriched"], version_id=v.id)

    view = enrich_view_from_catalog(_base_view(v.asset_id), service, v.asset_id)
    # Version-level tags arrive through the (cached) version_tag_map.
    assert [tv.tags for tv in view.versions] == [["enriched"]]

    # Two more enrichments must not REBUILD the maps: the objects served
    # after them are the same ones the cache held before (a rebuild would
    # have replaced them).
    maps_before = _catalog_tag_maps(service)
    enrich_view_from_catalog(_base_view(v.asset_id), service, v.asset_id)
    enrich_view_from_catalog(_base_view(v.asset_id), service, v.asset_id)
    maps_after = _catalog_tag_maps(service)
    assert maps_after[0] is maps_before[0], "tag_by_id rebuilt during enrichment"
    assert maps_after[1] is maps_before[1], "version_tag_map rebuilt"


# ------------------------------------------------------------------- #1171


def _artifact(tmp_path: Path, name: str = "map.png") -> ExportArtifact:
    target = tmp_path / "exports" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"png")
    return ExportArtifact(
        linked_id="res_source",
        format="png",
        output_path=str(target),
        generated_at="2026-01-01T00:00:00",
    )


def test_artifact_view_reuses_probe_cache_zero_stat_on_rebuild(tmp_path, monkeypatch):
    """A second build with the SAME cache performs no further syscalls."""
    import paleo_workbench.ui.pages.data_view_models as dvm

    stats = {"n": 0}
    real_stat = dvm.os.stat

    def counting_stat(path, *args, **kwargs):
        stats["n"] += 1
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(dvm.os, "stat", counting_stat)

    artifact = _artifact(tmp_path)
    probe = FsProbeCache()
    first = asset_view_from_artifact(artifact, fs_probe=probe)
    assert stats["n"] >= 1
    assert first.size_bytes == 3  # 'png'
    assert first.integrity_state is not IntegrityState.MISSING

    stats["n"] = 0
    second = asset_view_from_artifact(artifact, fs_probe=probe)
    assert stats["n"] == 0, "cached probe path still issued syscalls"
    assert second.size_bytes == first.size_bytes


def test_artifact_view_missing_file_reports_missing(tmp_path):
    artifact = _artifact(tmp_path, "gone.png")
    Path(artifact.output_path).unlink()
    probe = FsProbeCache()
    view = asset_view_from_artifact(artifact, fs_probe=probe)
    assert view.integrity_state is IntegrityState.MISSING
    assert view.size_bytes is None


def test_enrich_integrity_reports_missing_payload(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path, "m.las"))
    payload = service.resolve_path(v)
    payload.chmod(payload.stat().st_mode | 0o200)  # make writable to unlink
    payload.unlink()

    view = enrich_view_from_catalog(_base_view(v.asset_id), service, v.asset_id)
    assert view.integrity_state is IntegrityState.MISSING


def test_enrich_integrity_verified_for_present_payload(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path, "ok.las"))
    view = enrich_view_from_catalog(_base_view(v.asset_id), service, v.asset_id)
    assert view.integrity_state is IntegrityState.VERIFIED
