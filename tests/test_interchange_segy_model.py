"""I7/I8 — SEG-Y (small/medium only) and 3D model export adapters."""

from __future__ import annotations

import pytest

from paleo_workbench.interchange.adapters.model_adapter import (
    AbaqusAdapter,
    Flac3dAdapter,
    parse_abaqus,
    parse_flac3d,
)
from paleo_workbench.interchange.contracts import (
    FormatNotSupportedError,
    InspectionResult,
    VerificationState,
)
from paleo_workbench.interchange.executor import ExportExecutor, ImportExecutor

from tests import interchange_fixtures as fx


# ---------------------------------------------------------------------------
# SEG-Y
# ---------------------------------------------------------------------------


@pytest.fixture()
def segy_adapter():
    pytest.importorskip("segyio")
    from paleo_workbench.interchange.adapters.segy_adapter import SegyAdapter

    return SegyAdapter()


def test_segy_inspect_reports_traces_and_interval(tmp_path, segy_adapter):
    segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
    inspection = segy_adapter.inspect(segy)
    assert inspection.ok
    meta = inspection.metadata
    assert meta["trace_count"] > 0
    assert meta["sample_count"] > 0
    assert meta["sample_interval_us"] == 2000  # dt = 2 ms generator preset
    assert inspection.units.get("twt") == "ms"
    probe = meta["geometry_probe"]
    assert probe["inline_varies"] and probe["crossline_varies"]


def test_segy_inspect_rejects_truncated_header(tmp_path, segy_adapter):
    stub = tmp_path / "stub.segy"
    stub.write_bytes(b"\x00" * 1000)
    inspection = segy_adapter.inspect(stub)
    assert not inspection.ok
    assert any("截断" in e for e in inspection.errors)


def test_segy_fingerprint(tmp_path, segy_adapter):
    segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
    fingerprint = segy_adapter.fingerprint(segy)
    assert fingerprint["hash"]
    assert fingerprint["size_bytes"] == segy.stat().st_size


def test_segy_export_capability_is_honest(tmp_path, segy_adapter):
    segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
    with pytest.raises(FormatNotSupportedError):
        segy_adapter.plan_export(segy, tmp_path / "out.segy")
    verification = segy_adapter.verify_output(tmp_path / "x", None)
    assert verification.state is VerificationState.UNVERIFIED


def test_segy_import_managed_copy_small(tmp_path, segy_adapter):
    import paleo_workbench.catalog.service as catalog_service

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = catalog_service.DataCatalogService.open(project_path)
    try:
        segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
        plan = segy_adapter.plan_import(segy, segy_adapter.inspect(segy))
        assert plan.action == "managed_copy"
        result = ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)
        version = catalog.get_version(result.version_id)
        assert version.managed is True and version.sha256
    finally:
        catalog.close()


def test_segy_large_source_links_externally(tmp_path, segy_adapter):
    segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
    oversized = InspectionResult(
        format_id="segy", ok=True, size_bytes=5 * 1024 * 1024 * 1024
    )
    plan = segy_adapter.plan_import(segy, oversized)
    assert plan.action == "link_external"


# ---------------------------------------------------------------------------
# 3D model exports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_cls", [Flac3dAdapter, AbaqusAdapter])
def test_model_export_roundtrip_verify(tmp_path, adapter_cls):
    adapter = adapter_cls()
    target = tmp_path / f"mesh.{adapter.extensions[0]}"
    plan = adapter.plan_export(tmp_path / "model.src", target, options={"nx": 3, "ny": 2, "nz": 2})
    written, verification = ExportExecutor().execute(plan)
    assert written == target
    assert verification.state is VerificationState.VERIFIED
    by_name = {c.name: c for c in verification.checks}
    assert by_name["gridpoint_count"].detail == "预期 36，实际 36"
    assert by_name["zone_count"].passed


def test_model_export_rejects_missing_dimensions(tmp_path):
    adapter = Flac3dAdapter()
    with pytest.raises(FormatNotSupportedError):
        adapter.plan_export(tmp_path / "s", tmp_path / "m.f3grid", options={"nx": 2})
    with pytest.raises(FormatNotSupportedError):
        adapter.plan_export(tmp_path / "s", tmp_path / "m.f3grid", options={"nx": 2, "ny": 2, "nz": 0})


def test_model_verify_detects_dangling_node_reference(tmp_path):
    """A zone referencing an undefined node must fail verification."""
    path = tmp_path / "broken.f3grid"
    lines = ["* header", "G 1 0 0 0", "G 2 1 0 0", "Z B8 1 1 2 3 4 5 6 7 8"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    facts = parse_flac3d(path)
    assert facts.gridpoints == 2 and facts.zones == 1
    assert any("未定义的节点" in p for p in facts.problems)


def test_model_verify_detects_non_contiguous_ids(tmp_path):
    path = tmp_path / "gap.f3grid"
    lines = ["G 1 0 0 0", "G 3 1 0 0"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    facts = parse_flac3d(path)
    assert any("编号不连续" in p for p in facts.problems)


def test_model_inspect_rejects_foreign_file(tmp_path):
    foreign = tmp_path / "not_a_mesh.f3grid"
    foreign.write_text("hello world\n", encoding="utf-8")
    inspection = Flac3dAdapter().inspect(foreign)
    assert not inspection.ok
    assert any("未识别到网格记录" in e for e in inspection.errors)


def test_model_import_is_unsupported(tmp_path):
    from paleo_workbench.interchange.contracts import PreflightFailedError

    mesh = fx.write_f3grid(tmp_path / "m.f3grid", nx=2, ny=2, nz=2)
    adapter = Flac3dAdapter()
    plan = adapter.plan_import(mesh, adapter.inspect(mesh))
    assert plan.action == "unsupported"
    with pytest.raises(PreflightFailedError):
        ImportExecutor(catalog=None).execute(plan)


def test_unavailable_adapters_declare_honestly(tmp_path):
    from paleo_workbench.interchange.adapters.unavailable import (
        DlisAdapter,
        MeshExchangeAdapter,
        VtkModelAdapter,
    )

    for adapter in (DlisAdapter(), VtkModelAdapter(), MeshExchangeAdapter()):
        capability = adapter.capability()
        assert not capability.read and not capability.export
        assert capability.notes  # actionable reason
        probe = tmp_path / f"x.{adapter.extensions[0]}"
        probe.write_bytes(b"dummy")
        plan = adapter.plan_import(probe, adapter.inspect(probe))
        assert plan.action == "unsupported"
        inspection = adapter.inspect(probe)
        assert not inspection.ok
