from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_strategy import (
    preview_for_artifact,
    preview_for_resource,
)


def test_preview_strategy_identifies_image(tmp_path: Path):
    image = tmp_path / "map.png"
    image.write_bytes(b"not-real-png")
    resource = ResourceItem(
        name="map.png",
        path=image.as_posix(),
        type="image_reference",
        format="png",
    )

    state = preview_for_resource(resource)

    assert state.mode == "image"
    assert state.image_path == image.as_posix()


def test_preview_strategy_returns_table_summary():
    resource = ResourceItem(
        name="table.xlsx",
        path="/tmp/table.xlsx",
        type="spreadsheet",
        format="xlsx",
        parsed_summary={"size_bytes": 2048},
    )

    state = preview_for_resource(resource)

    assert state.mode == "table"
    assert "table.xlsx" in state.title
    assert any("2048" in line for line in state.lines)


def test_preview_strategy_metadata_for_unknown():
    resource = ResourceItem(
        name="raw.bin",
        path="/tmp/raw.bin",
        type="unknown",
        format="bin",
    )

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "暂不支持预览" in state.warning


def test_preview_strategy_export_artifact():
    artifact = ExportArtifact(
        linked_id="map_1",
        format="GeoTIFF",
        output_path="/tmp/map.tif",
    )

    state = preview_for_artifact(artifact)

    assert state.mode == "artifact"
    assert "GeoTIFF" in state.title
