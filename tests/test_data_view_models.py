import pytest
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_view_models import (
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
    assert DataStage.RAW.label == "原始输入"
    assert DataStage.DERIVED.label == "派生数据"
    assert DataStage.INTERMEDIATE.label == "中间结果"
    assert DataStage.OUTPUT.label == "输出成果"

    assert DataStage.RAW.icon_symbol == "🔒"
    assert DataStage.DERIVED.icon_symbol == "🌿"

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
