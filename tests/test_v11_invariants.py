"""V11 invariants (goal §18): immutability, consistency, integrity.

Every test here asserts an invariant the architecture document declares
(docs/development/data-fabric-v11/02 §4) — these are the properties the
system must never lose while evolving.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage, RunPort
from paleo_workbench.catalog.service import DataCatalogService


@pytest.fixture()
def service(tmp_path: Path) -> DataCatalogService:
    project = tmp_path / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    yield svc
    svc.close()


def _raw(service, tmp_path, name, content="c"):
    src = tmp_path / name
    src.write_text(content, encoding="utf-8")
    return service.import_raw(src, name=name, type="well_log")


# 1. committed DataVersion immutability --------------------------------------


def test_committed_version_payload_is_readonly(service, tmp_path):
    version = _raw(service, tmp_path, "a.las")
    payload = service.resolve_path(version)
    import stat

    assert payload.is_file()
    mode = payload.stat().st_mode
    assert not (mode & stat.S_IWRITE), "committed payload must be read-only"


def test_registering_same_version_id_raises(service, tmp_path):
    v1 = _raw(service, tmp_path, "a.las")
    src2 = tmp_path / "b.las"
    src2.write_text("other", encoding="utf-8")
    from paleo_workbench.catalog.models import ImmutableVersionError

    with pytest.raises(ImmutableVersionError):
        service.register_version(
            service.get_version(v1.id).asset_id, src2, DataStage.RAW,
            version_id=v1.id,
        )


def test_pin_and_retention_never_touch_identity(service, tmp_path):
    v1 = _raw(service, tmp_path, "a.las")
    before = (v1.path, v1.sha256, v1.size_bytes)
    service.pin_version(v1.id, reason="x")
    service.set_retention_class(v1.id, "cache")
    after = service.get_version(v1.id)
    assert (after.path, after.sha256, after.size_bytes) == before


# 2. ports ⊆ flat io consistency (across reload) ------------------------------


def test_ports_subset_invariant_holds_after_reload(service, tmp_path):
    v1 = _raw(service, tmp_path, "a.las")
    v2 = _raw(service, tmp_path, "b.las")
    run = service.register_run(
        "op", input_version_ids=[v1.id, v2.id],
        input_ports=[
            RunPort(role="sonic", version_id=v1.id),
            RunPort(role="density", version_id=v2.id),
        ],
        output_ports=[RunPort(role="prediction", version_id=v2.id)],
    )
    assert {p.version_id for p in run.input_ports} <= set(run.input_version_ids)
    project_path = service.project_path
    service.close()
    reopened = DataCatalogService.open(project_path)
    try:
        r = reopened.get_run(run.id)
        assert {p.version_id for p in r.input_ports} <= set(r.input_version_ids)
        assert {p.version_id for p in r.output_ports} <= set(r.output_version_ids)
    finally:
        reopened.close()


def test_manifest_roundtrip_preserves_ports_and_members(service, tmp_path):
    v1 = _raw(service, tmp_path, "a.las")
    run = service.register_run(
        "op", input_version_ids=[v1.id],
        input_ports=[RunPort(role="well_logs", version_id=v1.id, note="hdr")],
    )
    # bundle
    asset = service._new_asset("fam", "geojson", "shp", None)
    with service._lock:
        service._add_asset(asset)
    bundle_dir = tmp_path / "fam"
    bundle_dir.mkdir()
    (bundle_dir / "l.shp").write_bytes(b"s")
    (bundle_dir / "l.dbf").write_bytes(b"d")
    bundle = service.register_bundle_version(asset.id, bundle_dir, DataStage.RAW)

    service.export_manifest()  # checkpoint is explicit; mutations don't rewrite it
    from paleo_workbench.catalog.store import catalog_file_for

    manifest = catalog_file_for(service.project_path)
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    stored_run = next(r for r in data["runs"] if r["id"] == run.id)
    assert stored_run["input_ports"][0]["note"] == "hdr"
    stored_version = next(v for v in data["versions"] if v["id"] == bundle.id)
    assert len(stored_version["members"]) == 2
    # and the manifest loads back (old-version compatibility shape)
    from paleo_workbench.catalog.models import CatalogDocument

    loaded = CatalogDocument.model_validate(data)
    assert loaded.runs[0].input_ports[0].role == "well_logs"
    assert len(loaded.versions[-1].members) == 2


# 3. no dangling REQUIRED lineage (goal §18) ----------------------------------


def test_no_dangling_required_ports_in_document(service, tmp_path):
    v1 = _raw(service, tmp_path, "a.las")
    v2 = _raw(service, tmp_path, "b.las")
    service.register_run(
        "op", input_version_ids=[v1.id, v2.id],
        input_ports=[
            RunPort(role="sonic", version_id=v1.id, required=True),
            RunPort(role="density", version_id=v2.id, required=True),
        ],
    )
    known = {v.id for v in service.document.versions}
    for run in service.document.runs:
        for port in (*run.input_ports, *run.output_ports):
            if port.required:
                assert port.version_id in known, (
                    f"required port of run {run.id} references unknown version"
                )


# 4. compound member consistency ----------------------------------------------


def test_bundle_member_paths_never_escape_payload_dir(service, tmp_path):
    asset = service._new_asset("fam", "geojson", "shp", None)
    with service._lock:
        service._add_asset(asset)
    bundle_dir = tmp_path / "fam"
    bundle_dir.mkdir()
    (bundle_dir / "l.shp").write_bytes(b"s")
    version = service.register_bundle_version(asset.id, bundle_dir, DataStage.RAW)
    base = service.resolve_path(version)
    for member in version.members:
        resolved = (base / member.rel_path).resolve()
        assert str(resolved).startswith(str(base.resolve())), (
            "member escapes the version payload directory"
        )
    # aggregate checksum is recomputable from members alone
    from paleo_workbench.catalog.models import aggregate_member_sha256

    assert aggregate_member_sha256(version.members) == version.sha256


# 5. entity link identity stability -------------------------------------------


def test_entity_link_identity_stable_across_upserts(tmp_path):
    from paleo_workbench.project.domain import (
        WellEntity,
        upsert_entity_asset_link,
    )
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("d")
    well = WellEntity(name="W1")
    doc.wells.append(well)
    link1, created1 = upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id="asset_x",
        role="well_log", is_primary=True,
    )
    link2, created2 = upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id="asset_x",
        role="well_log", is_primary=True,
    )
    assert created1 and not created2
    assert link1.id == link2.id
    assert len(doc.entity_asset_links) == 1
    # second asset in same role demotes the first primary
    _, _ = upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id="asset_y",
        role="well_log", is_primary=True,
    )
    primaries = [
        l for l in doc.entity_asset_links
        if l.role == "well_log" and l.is_primary
    ]
    assert len(primaries) == 1 and primaries[0].asset_id == "asset_y"
