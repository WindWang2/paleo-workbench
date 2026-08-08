"""Tests for the Data Catalog seam (Protocol + in-memory reference backend).

These validate the lifecycle semantics the business layer relies on:
- managed RAW immutability + legacy bridge
- run/version/lineage registration
- rerun never overwrites a committed version
- integrity verification (tamper → MODIFIED, recorded checksum preserved)
- (de)serialization round-trip (mirrors Core SQLite rebuild)

Sibling-branch note: when ``feat/data-catalog-core`` lands, the same tests run
against a Core-backed adapter by swapping the backend via ``set_catalog``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    DataRunRef,
    DataStage,
    DataVersionRef,
    InMemoryCatalog,
    IntegrityStatus,
    LineageEdge,
    get_catalog,
    reset_catalog,
    set_catalog,
    sha256_of_file,
)
from paleo_workbench.catalog.backend import _asset_key


@pytest.fixture()
def catalog():
    """A fresh in-memory catalog per test (isolated state)."""
    cat = InMemoryCatalog()
    set_catalog(cat)
    yield cat
    reset_catalog()


# ------------------------------------------------------------------ value types


def test_data_stage_is_input_like():
    assert DataStage.RAW.is_input_like
    assert DataStage.EXTERNAL.is_input_like
    assert not DataStage.INTERMEDIATE.is_input_like
    assert not DataStage.OUTPUT.is_input_like


def test_version_ref_roundtrip_dict():
    ref = DataVersionRef(
        asset_id="asset_1",
        version_id="ver_1",
        name="w.las",
        stage=DataStage.RAW,
        path="/tmp/w.las",
        checksum="deadbeef",
        legacy_resource_id="res_1",
        tags=["input"],
    )
    data = ref.to_dict()
    assert data["stage"] == "RAW"
    restored = DataVersionRef.from_dict(data)
    assert restored == ref
    assert restored.stage is DataStage.RAW
    assert restored.legacy_resource_id == "res_1"


def test_run_ref_roundtrip_dict():
    run = DataRunRef(
        run_id="run_1",
        operation="factor_map",
        input_version_ids=["ver_a"],
        output_version_ids=["ver_b"],
        parameters={"method": "IDW"},
        generator_version="fv1",
        input_snapshot_hash="abc",
    )
    restored = DataRunRef.from_dict(run.to_dict())
    assert restored.run_id == "run_1"
    assert restored.input_version_ids == ["ver_a"]
    assert restored.input_snapshot_hash == "abc"


# --------------------------------------------------------------- managed inputs


def test_managed_input_is_idempotent(catalog: InMemoryCatalog):
    v1 = catalog.register_input(
        name="w.las", path="/proj/w.las", checksum="c1", legacy_resource_id="res_1"
    )
    v2 = catalog.register_input(
        name="w.las", path="/proj/w.las", checksum="c1", legacy_resource_id="res_1"
    )
    assert v1.version_id == v2.version_id
    assert v1.asset_id == v2.asset_id
    assert v1.stage is DataStage.RAW


def test_managed_input_different_checksum_is_new_version(catalog: InMemoryCatalog):
    v1 = catalog.register_input(name="w.las", path="/p/w.las", checksum="c1")
    v2 = catalog.register_input(name="w.las", path="/p/w.las", checksum="c2")
    assert v1.version_id != v2.version_id
    # Same logical asset? No — different checksum means a distinct asset here
    # (the in-memory backend keys on path+checksum).
    assert catalog.list_versions(stage=DataStage.RAW)


def test_external_input_is_not_managed(catalog: InMemoryCatalog):
    v = catalog.register_input(
        name="ext.las", path="/abs/ext.las", checksum=None, external=True
    )
    assert v.stage is DataStage.EXTERNAL
    assert v.external is True
    # Re-registering the same external path still produces a distinct version
    # (external sources are not deduplicated — they may be volatile).
    v2 = catalog.register_input(
        name="ext.las", path="/abs/ext.las", checksum=None, external=True
    )
    assert v2.version_id != v.version_id


def test_legacy_resource_bridge(catalog: InMemoryCatalog):
    catalog.register_input(
        name="w.las", path="/p/w.las", checksum="c1", legacy_resource_id="res_42"
    )
    resolved = catalog.resolve_legacy_resource("res_42")
    assert resolved is not None
    assert resolved.stage is DataStage.RAW
    # Unknown legacy id resolves to None (graceful degradation).
    assert catalog.resolve_legacy_resource("res_missing") is None


# ------------------------------------------------------------------ runs / producers


def test_run_links_inputs_to_outputs(catalog: InMemoryCatalog):
    a = catalog.register_input(name="a", path="/p/a", checksum="ca")
    run = catalog.begin_run(operation="op", input_version_ids=[a.version_id])
    out = catalog.register_output(
        run_id=run.run_id, name="out", path="/p/out", checksum="co"
    )
    catalog.complete_run(run.run_id)
    assert out.producing_run_id == run.run_id
    assert run.output_version_ids == [out.version_id]
    # Edge stored.
    edges = [e for e in catalog._lineage if e.target_version_id == out.version_id]
    assert any(e.source_version_id == a.version_id for e in edges)


def test_register_intermediate_and_output_and_derived_stages(catalog: InMemoryCatalog):
    a = catalog.register_input(name="a", path="/p/a", checksum="ca")
    run = catalog.begin_run(operation="op", input_version_ids=[a.version_id])
    iv = catalog.register_intermediate(run_id=run.run_id, name="i", path="/p/i")
    ov = catalog.register_output(run_id=run.run_id, name="o", path="/p/o")
    dv = catalog.register_derived(run_id=run.run_id, name="d", path="/p/d")
    assert iv.stage is DataStage.INTERMEDIATE
    assert ov.stage is DataStage.OUTPUT
    assert dv.stage is DataStage.DERIVED


# --------------------------------------------------------------------- lineage


def test_lineage_ancestors_and_descendants(catalog: InMemoryCatalog):
    raw = catalog.register_input(name="raw", path="/p/raw", checksum="cr")
    r1 = catalog.begin_run(operation="f", input_version_ids=[raw.version_id])
    inter = catalog.register_intermediate(run_id=r1.run_id, name="inter", path="/p/inter")
    catalog.complete_run(r1.run_id)
    r2 = catalog.begin_run(operation="e", input_version_ids=[inter.version_id])
    out = catalog.register_output(run_id=r2.run_id, name="out", path="/p/out")
    catalog.complete_run(r2.run_id)

    ancestors = catalog.query_lineage(out.version_id, direction="ancestors")
    anc_ids = {a.version_id for a in ancestors}
    assert raw.version_id in anc_ids
    assert inter.version_id in anc_ids

    descendants = catalog.query_lineage(raw.version_id, direction="descendants")
    desc_ids = {d.version_id for d in descendants}
    assert inter.version_id in desc_ids
    assert out.version_id in desc_ids


def test_lineage_unknown_direction_raises(catalog: InMemoryCatalog):
    with pytest.raises(ValueError):
        catalog.query_lineage("ver_x", direction="sideways")


def test_attach_explicit_lineage_edge(catalog: InMemoryCatalog):
    edge = catalog.attach_lineage(
        source_version_id="ver_a", target_version_id="ver_b", run_id="run_1"
    )
    assert isinstance(edge, LineageEdge)
    assert edge.source_version_id == "ver_a"


# ----------------------------------------------------------- rerun / no-overwrite


def test_rerun_produces_new_version_old_retained(catalog: InMemoryCatalog):
    a = catalog.register_input(name="a", path="/p/a", checksum="ca")
    run1 = catalog.begin_run(operation="f", input_version_ids=[a.version_id])
    out1 = catalog.register_intermediate(run_id=run1.run_id, name="g", path="/p/g1")
    catalog.complete_run(run1.run_id)

    run2 = catalog.begin_run(operation="f", input_version_ids=[a.version_id])
    out2 = catalog.register_intermediate(run_id=run2.run_id, name="g", path="/p/g2")
    catalog.complete_run(run2.run_id)

    assert out1.version_id != out2.version_id
    assert catalog.resolve_version(out1.version_id) is not None
    assert catalog.resolve_version(out2.version_id) is not None


# ----------------------------------------------------------------- integrity


def test_integrity_verified(tmp_path: Path, catalog: InMemoryCatalog):
    f = tmp_path / "raw.dat"
    f.write_bytes(b"hello")
    cs = sha256_of_file(f)
    v = catalog.register_input(name="raw", path=str(f), checksum=cs)
    assert catalog.verify_integrity(v.version_id) is IntegrityStatus.VERIFIED


def test_integrity_modified_not_overwritten(tmp_path: Path, catalog: InMemoryCatalog):
    f = tmp_path / "raw.dat"
    f.write_bytes(b"hello")
    cs = sha256_of_file(f)
    v = catalog.register_input(name="raw", path=str(f), checksum=cs)
    # Tamper after registration.
    f.write_bytes(b"HACKED")
    assert catalog.verify_integrity(v.version_id) is IntegrityStatus.MODIFIED
    # Recorded checksum is preserved (not auto-overwritten).
    assert catalog.resolve_version(v.version_id).checksum == cs


def test_integrity_missing_file(catalog: InMemoryCatalog):
    v = catalog.register_input(name="gone", path="/no/such/file", checksum="c")
    assert catalog.verify_integrity(v.version_id) is IntegrityStatus.MISSING


def test_integrity_unknown_when_no_checksum(tmp_path: Path, catalog: InMemoryCatalog):
    # A file that exists but was never given a recorded checksum cannot be
    # verified — and we never fabricate one. (A missing file is MISSING,
    # taking priority over the no-checksum case.)
    f = tmp_path / "exists.dat"
    f.write_bytes(b"data")
    v = catalog.register_input(name="x", path=str(f), checksum=None)
    assert catalog.verify_integrity(v.version_id) is IntegrityStatus.UNKNOWN
    assert catalog.resolve_version(v.version_id).checksum is None


# ------------------------------------------------------------------- listing


def test_list_versions_filter_by_stage(catalog: InMemoryCatalog):
    a = catalog.register_input(name="a", path="/p/a", checksum="ca")
    run = catalog.begin_run(operation="o", input_version_ids=[a.version_id])
    catalog.register_output(run_id=run.run_id, name="o", path="/p/o")
    catalog.complete_run(run.run_id)
    raws = catalog.list_versions(stage=DataStage.RAW)
    outs = catalog.list_versions(stage=DataStage.OUTPUT)
    assert len(raws) == 1
    assert len(outs) == 1


def test_list_runs_ordered(catalog: InMemoryCatalog):
    r1 = catalog.begin_run(operation="a", input_version_ids=[])
    r2 = catalog.begin_run(operation="b", input_version_ids=[])
    runs = catalog.list_runs()
    assert [r.run_id for r in runs] == [r1.run_id, r2.run_id]


# --------------------------------------------------------- serialization round-trip


def test_serialize_roundtrip_preserves_state(catalog: InMemoryCatalog):
    a = catalog.register_input(name="a", path="/p/a", checksum="ca", legacy_resource_id="res_1")
    run = catalog.begin_run(operation="f", input_version_ids=[a.version_id])
    out = catalog.register_output(run_id=run.run_id, name="o", path="/p/o")
    catalog.complete_run(run.run_id)

    data = catalog.to_dict()
    rebuilt = InMemoryCatalog.from_dict(data)
    # All versions/runs/lineage/legacy bridge preserved.
    assert len(rebuilt.list_versions()) == len(catalog.list_versions())
    assert rebuilt.resolve_legacy_resource("res_1").version_id == a.version_id
    assert rebuilt.resolve_run(run.run_id).output_version_ids == [out.version_id]
    # Managed-input index rebuilt so re-registering is idempotent.
    again = rebuilt.register_input(name="a", path="/p/a", checksum="ca", legacy_resource_id="res_1")
    assert again.version_id == a.version_id


# ------------------------------------------------------------------ runtime accessor


def test_runtime_get_catalog_returns_singleton_until_reset():
    reset_catalog()
    c1 = get_catalog()
    c2 = get_catalog()
    assert c1 is c2
    reset_catalog()


def test_runtime_set_catalog_overrides():
    reset_catalog()
    custom = InMemoryCatalog()
    set_catalog(custom)
    assert get_catalog() is custom
    reset_catalog()
