import pytest
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_view_models import (
    STAGE_COLORS,
    STAGE_ICONS,
    STAGE_LABELS,
    AssetView,
    DataStage,
    IntegrityState,
    LineageView,
    VersionView,
    asset_view_from_artifact,
    asset_view_from_object,
    asset_view_from_resource,
)


def test_data_stage_and_integrity_enums():
    # DataStage is now the single Core enum (paleo_workbench.catalog.models,
    # ADR 0056) with lowercase values; presentation data lives in the
    # STAGE_* mappings instead of enum properties.
    assert DataStage.RAW.value == "raw"
    assert DataStage.DERIVED.value == "derived"
    assert DataStage.INTERMEDIATE.value == "intermediate"
    assert DataStage.OUTPUT.value == "output"

    assert STAGE_LABELS[DataStage.RAW] == "原始输入"
    assert STAGE_LABELS[DataStage.DERIVED] == "派生数据"
    assert STAGE_LABELS[DataStage.INTERMEDIATE] == "中间结果"
    assert STAGE_LABELS[DataStage.OUTPUT] == "输出成果"

    assert STAGE_ICONS[DataStage.RAW] == "🔒"
    assert STAGE_ICONS[DataStage.DERIVED] == "🌿"
    assert set(STAGE_COLORS) == set(DataStage)

    assert IntegrityState.VERIFIED.label == "已校验"
    assert IntegrityState.MODIFIED.label == "已修改"
    assert IntegrityState.MISSING.label == "缺失"
    assert IntegrityState.UNMANAGED.label == "外部链接"
    assert IntegrityState.UNKNOWN.label == "未校验"


def test_version_and_lineage_views():
    ver = VersionView(
        version_id="v1",
        checksum="1234567890abcdef12345678",
        checksum_state=IntegrityState.VERIFIED,
    )
    assert ver.checksum_display == "12345678...5678"

    empty_ver = VersionView(version_id="v1")
    assert empty_ver.checksum_display == "—"

    lineage = LineageView(parent_ids=["res_1"], run_id="run_123")
    assert lineage.has_lineage is True

    empty_lineage = LineageView()
    assert empty_lineage.has_lineage is False


def test_asset_view_from_resource(tmp_path: Path):
    dummy_file = tmp_path / "test_well.las"
    dummy_file.write_text("dummy content")

    res = ResourceItem(
        id="res_001",
        name="Well-01",
        path=str(dummy_file),
        type="well_log",
        format="las",
        checksum="sha256_mock_hash",
        tags=["重点", "探井"],
        external=False,
        artifact_role="input",
    )

    view = asset_view_from_resource(res, project_root=tmp_path)
    assert view.id == "res_001"
    assert view.name == "Well-01"
    assert view.stage == DataStage.RAW
    assert view.is_raw is True
    assert view.type_label == "测井"
    assert view.integrity_state == IntegrityState.VERIFIED
    assert view.managed is True
    assert view.tags == ["重点", "探井"]
    assert len(view.versions) == 1
    assert view.versions[0].version_id == "v1"


def test_asset_view_from_resource_missing():
    res = ResourceItem(
        id="res_002",
        name="Missing.segy",
        path="/nonexistent/path/missing.segy",
        type="seismic",
        format="segy",
        status="missing",
        artifact_role="derived",
    )

    view = asset_view_from_resource(res)
    assert view.stage == DataStage.DERIVED
    assert view.is_derived is True
    assert view.integrity_state == IntegrityState.MISSING
    assert view.is_missing is True


def test_asset_view_from_artifact(tmp_path: Path):
    out_file = tmp_path / "result.json"
    out_file.write_text("{}")

    artifact = ExportArtifact(
        id="art_100",
        format="json",
        output_path=str(out_file),
        linked_id="res_001",
        generated_at="2026-08-08T12:00:00Z",
    )

    view = asset_view_from_artifact(artifact, project_root=tmp_path)
    assert view.id == "art_100"
    assert view.stage == DataStage.OUTPUT
    assert view.is_output is True
    assert view.type_label == "成果"
    assert view.integrity_state == IntegrityState.VERIFIED
    assert view.lineage.parent_ids == ["res_001"]


def test_asset_view_from_object_duck_typing():
    res = ResourceItem(
        id="res_003",
        name="Horizons.txt",
        path="/tmp/horizons.txt",
        type="horizon",
        format="txt",
    )
    view1 = asset_view_from_object(res)
    assert view1.id == "res_003"

    view2 = asset_view_from_object(view1)
    assert view2 is view1


def test_enrich_integrity_does_not_rehash_on_ui_thread(monkeypatch, tmp_path):
    """enrich_view_from_catalog must NOT call verify_integrity (full payload
    hash) on the UI thread — only the cheap presence check (review finding
    I6)."""
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.ui.pages.data_view_models import (
        IntegrityState,
        asset_view_from_resource,
        enrich_view_from_catalog,
    )
    from paleo_workbench.project.models import ResourceItem

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    try:
        src = tmp_path / "incoming" / "a.las"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"data")
        version = svc.import_raw(src)
        asset = svc.get_asset(version.asset_id)

        calls = {"verify": 0}
        real_verify = svc.verify_integrity

        def spy(*args, **kwargs):
            calls["verify"] += 1
            return real_verify(*args, **kwargs)

        monkeypatch.setattr(svc, "verify_integrity", spy)

        res = ResourceItem(
            id="res_x",
            name="a.las",
            path=src.as_posix(),
            type="well_log",
            format="las",
            checksum=version.sha256,
        )
        view = asset_view_from_resource(res)
        enrich_view_from_catalog(view, svc, asset.id)

        # Recorded-checksum presence is reported; the expensive re-hash was
        # NOT invoked on the UI thread.
        assert calls["verify"] == 0
        assert view.integrity_state == IntegrityState.VERIFIED
    finally:
        svc.close()
