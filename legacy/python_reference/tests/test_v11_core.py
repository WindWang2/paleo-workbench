"""V11 data-fabric core: typed lineage ports, compound bundles, pin/retention.

Covers the persistence round-trip (document → SQLite canonical store → reopen)
for the V11 additive tables (``run_ports``, ``version_members``), the
ports⊆flat invariant, bundle placement/verification/working-copy lifecycle,
and pin/retention governance overlays.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import (
    DataStage,
    RunPort,
    VersionMember,
)
from paleo_workbench.catalog.service import DataCatalogService


@pytest.fixture()
def service(tmp_path: Path) -> DataCatalogService:
    project = tmp_path / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    yield svc
    svc.close()


def _make_raw(service: DataCatalogService, tmp_path: Path, name: str) -> str:
    src = tmp_path / name
    src.write_text(f"payload-{name}\n", encoding="utf-8")
    version = service.import_raw(src, name=name, type="well_log")
    return version.id


# ---------------------------------------------------------------------------
# typed lineage ports
# ---------------------------------------------------------------------------


def test_set_run_ports_roundtrip_and_subset_invariant(service, tmp_path):
    v1 = _make_raw(service, tmp_path, "a.las")
    v2 = _make_raw(service, tmp_path, "b.las")
    run = service.register_run(
        "demo_op", input_version_ids=[v1, v2], parameters={"k": 1}
    )
    service.set_run_ports(
        run.id,
        input_ports=[
            RunPort(role="sonic", version_id=v1, ordinal=0),
            RunPort(role="density", version_id=v2, ordinal=1),
        ],
        output_ports=[],
    )
    reloaded = service.get_run(run.id)
    assert [p.role for p in reloaded.input_ports] == ["sonic", "density"]
    assert set(p.version_id for p in reloaded.input_ports) <= set(
        reloaded.input_version_ids
    )


def test_set_run_ports_rejects_unknown_version(service, tmp_path):
    v1 = _make_raw(service, tmp_path, "a.las")
    run = service.register_run("demo_op", input_version_ids=[v1])
    with pytest.raises(Exception):
        service.set_run_ports(
            run.id, input_ports=[RunPort(role="sonic", version_id="ver_missing")]
        )


def test_ports_survive_canonical_reopen(service, tmp_path):
    v1 = _make_raw(service, tmp_path, "a.las")
    run = service.register_run("demo_op", input_version_ids=[v1])
    service.set_run_ports(
        run.id,
        input_ports=[RunPort(role="sonic", version_id=v1, entity_type="well")],
        output_ports=[],
    )
    project_path = service.project_path
    service.close()

    reopened = DataCatalogService.open(project_path)
    try:
        r = reopened.get_run(run.id)
        assert len(r.input_ports) == 1
        assert r.input_ports[0].role == "sonic"
        assert r.input_ports[0].entity_type == "well"
    finally:
        reopened.close()


def test_old_store_gains_new_tables_without_rebuild(tmp_path):
    """A store written by pre-V11 code opens under V11 without data loss."""
    project = tmp_path / "old.paleo.json"
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    v1 = _make_raw(svc, tmp_path, "legacy.las")
    svc.close()

    # Simulate pre-V11 tables: drop the V11 additive tables from the store.
    import sqlite3

    from paleo_workbench.catalog.db import DB_FILENAME, catalog_dir_for

    db_path = catalog_dir_for(project) / DB_FILENAME
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE IF EXISTS run_ports")
    conn.execute("DROP TABLE IF EXISTS version_members")
    conn.commit()
    conn.close()

    reopened = DataCatalogService.open(project)
    try:
        assert reopened.get_version(v1) is not None
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert {"run_ports", "version_members"} <= tables
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# compound bundle versions
# ---------------------------------------------------------------------------


def _make_bundle_dir(tmp_path: Path) -> Path:
    bundle = tmp_path / "survey_family"
    (bundle / "sub").mkdir(parents=True)
    (bundle / "layer.shp").write_bytes(b"shp-bytes")
    (bundle / "layer.shx").write_bytes(b"shx-bytes")
    (bundle / "layer.dbf").write_bytes(b"dbf-bytes")
    (bundle / "sub" / "sidecar.bin").write_bytes(b"bin-bytes")
    return bundle


def test_register_bundle_version_roundtrip(service, tmp_path):
    asset = service._new_asset("survey family", "geojson", "shp", None)
    with service._lock:
        service._add_asset(asset)
        from paleo_workbench.catalog.db import DirtySet

        service._save(DirtySet(assets={asset.id: None}))
    bundle = _make_bundle_dir(tmp_path)
    version = service.register_bundle_version(
        asset.id,
        bundle,
        DataStage.RAW,
        member_specs=[
            VersionMember(name="geometry", rel_path="layer.shp", member_role="data"),
            VersionMember(
                name="projection", rel_path="sub/sidecar.bin",
                member_role="sidecar", required=False,
            ),
        ],
    )
    assert len(version.members) == 4
    by_rel = {m.rel_path: m for m in version.members}
    assert by_rel["layer.shp"].member_role == "data"
    assert by_rel["sub/sidecar.bin"].required is False
    assert by_rel["layer.dbf"].required is True
    assert version.sha256  # aggregate credential
    assert version.size_bytes == sum(m.size_bytes or 0 for m in version.members)

    # payload dir holds all members; member_path stays in-bounds
    base = service.resolve_path(version)
    assert base.is_dir()
    assert (base / "layer.shp").is_file()
    assert service.member_path(version.id, "sub/sidecar.bin").is_file()

    report = service.verify_bundle_integrity(version.id)
    assert report["bundle"] and report["status"] == "verified"

    # tamper one member → modified, and detection is per-member
    (base / "layer.dbf").chmod(0o666) if (base / "layer.dbf").exists() else None
    target = base / "sub" / "sidecar.bin"
    target.chmod(0o666)
    target.write_bytes(b"tampered")
    report2 = service.verify_bundle_integrity(version.id)
    assert report2["status"] == "modified"
    assert any(m["status"] == "modified" for m in report2["members"])


def test_bundle_rejects_escaping_member_spec(service, tmp_path):
    asset = service._new_asset("x", "geojson", None, None)
    with service._lock:
        service._add_asset(asset)
    bundle = _make_bundle_dir(tmp_path)
    with pytest.raises(Exception):
        service.register_bundle_version(
            asset.id,
            bundle,
            DataStage.RAW,
            member_specs=[
                VersionMember(name="escape", rel_path="../outside.shp")
            ],
        )


def test_bundle_rejects_spec_for_missing_file(service, tmp_path):
    asset = service._new_asset("x", "geojson", None, None)
    with service._lock:
        service._add_asset(asset)
    bundle = _make_bundle_dir(tmp_path)
    with pytest.raises(Exception):
        service.register_bundle_version(
            asset.id,
            bundle,
            DataStage.RAW,
            member_specs=[VersionMember(name="ghost", rel_path="ghost.shp")],
        )
    # nothing was placed
    root = service.resolve_path  # noqa: F841 (sanity that service still usable)
    assert not list((tmp_path / "demo.paleo.json").parent.glob("demo.artifacts/raw/*/*/*"))


def test_bundle_working_copy_commit_cycle(service, tmp_path):
    asset = service._new_asset("family", "geojson", "shp", None)
    with service._lock:
        service._add_asset(asset)
    bundle = _make_bundle_dir(tmp_path)
    version = service.register_bundle_version(asset.id, bundle, DataStage.RAW)

    work = service.create_bundle_working_copy(version.id)
    assert work.is_dir()
    # reuse, not clobber
    again = service.create_bundle_working_copy(version.id)
    assert again == work
    (work / "layer.dbf").write_bytes(b"edited-dbf")

    committed = service.commit_bundle_working_copy(
        work, asset_id=asset.id, stage=DataStage.RAW
    )
    assert committed.id != version.id
    assert committed.version_number == 2
    member = {m.rel_path: m for m in committed.members}["layer.dbf"]
    import hashlib

    assert member.sha256 == hashlib.sha256(b"edited-dbf").hexdigest()
    # the working copy moved away
    assert not work.exists()
    # original untouched
    orig = {m.rel_path: m for m in version.members}["layer.dbf"]
    from paleo_workbench.catalog.checksum import sha256_file

    assert sha256_file(service.member_path(version.id, orig)) == orig.sha256


def test_bundle_members_survive_reopen(service, tmp_path):
    asset = service._new_asset("family", "geojson", "shp", None)
    with service._lock:
        service._add_asset(asset)
    bundle = _make_bundle_dir(tmp_path)
    version = service.register_bundle_version(asset.id, bundle, DataStage.RAW)
    project_path = service.project_path
    service.close()

    reopened = DataCatalogService.open(project_path)
    try:
        v = reopened.get_version(version.id)
        assert len(v.members) == 4
        assert v.members  # ordered by (ordinal, name) at aggregate time
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# pin / retention / lifecycle status
# ---------------------------------------------------------------------------


def test_pin_roundtrip_and_cleanup_blocking(service, tmp_path):
    v1 = _make_raw(service, tmp_path, "a.las")
    run = service.register_run("op", input_version_ids=[v1])
    out = tmp_path / "out.json"
    out.write_text("{}", encoding="utf-8")
    result = service.register_result_asset(
        name="result", type="json", format="json", asset_metadata=None,
        source_path=out, stage=DataStage.DERIVED, run_id=run.id,
    )
    assert service.cleanup_eligibility(result.id)["eligible"] is False  # derived=user
    assert service.retention_class(v1) == "retain"  # RAW

    # cache-class with no dependents IS eligible…
    service.set_retention_class(result.id, "cache")
    assert service.cleanup_eligibility(result.id)["eligible"] is True
    # …but a downstream consumer blocks it (double gate).
    run2 = service.register_run("op2", input_version_ids=[result.id])
    out2 = tmp_path / "out2.json"
    out2.write_text("{}", encoding="utf-8")
    child = service.register_result_asset(
        name="child", type="json", format="json", asset_metadata=None,
        source_path=out2, stage=DataStage.DERIVED, run_id=run2.id,
    )
    elig = service.cleanup_eligibility(result.id)
    assert elig["eligible"] is False
    assert any("downstream" in b for b in elig["blockers"])
    # the child itself stays blocked by its user retention class
    assert any("retention" in b for b in service.cleanup_eligibility(child.id)["blockers"])

    service.pin_version(result.id, reason="freeze for review")
    assert service.is_pinned(result.id)
    status = service.version_lifecycle_status(result.id)
    assert status["pinned"] is True
    assert status["producing_operation"] == "op"

    service.unpin_version(result.id)
    assert not service.is_pinned(result.id)


def test_retention_unknown_value_conservative(service, tmp_path):
    v1 = _make_raw(service, tmp_path, "a.las")
    version = service.get_version(v1)
    version.metadata["retention_class"] = "garbage"
    assert service.retention_class(v1) == "retain"
