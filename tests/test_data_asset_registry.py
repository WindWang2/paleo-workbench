"""Tests for DataAssetRegistry deep module interface and single-point format registration."""
from __future__ import annotations

from pathlib import Path
import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.data_asset_registry import (
    DataAssetRegistry,
    FormatSpec,
    data_asset_registry,
)
from paleo_workbench.ui.pages.preview_settings import PreviewSettings


def test_data_asset_registry_singleton():
    assert isinstance(data_asset_registry, DataAssetRegistry)


def test_classify_path_standard_formats(tmp_path: Path):
    las_file = tmp_path / "well.las"
    las_file.touch()
    res_type, res_fmt, status = data_asset_registry.classify_path(las_file)
    assert res_type == "well_log"
    assert res_fmt == "las"
    assert status == "indexed"

    sgy_file = tmp_path / "seismic.sgy"
    sgy_file.touch()
    res_type, res_fmt, status = data_asset_registry.classify_path(sgy_file)
    assert res_type == "seismic"
    assert res_fmt == "sgy"
    assert status == "indexed"


def test_scan_directory(tmp_path: Path):
    (tmp_path / "well.las").write_text("~A DEPT GR\n100 45\n")
    (tmp_path / "notes.md").write_text("# Notes\n")

    items = data_asset_registry.scan_directory(tmp_path)
    assert len(items) == 2
    names = {item.name for item in items}
    assert "well.las" in names
    assert "notes.md" in names


def test_parse_preview_las(tmp_path: Path):
    las_file = tmp_path / "test.las"
    las_file.write_text("~A DEPT GR\n100.0 45.0\n100.1 48.0\n")

    item = ResourceItem(
        name="test.las",
        path=str(las_file),
        type="well_log",
        format="las",
        status="indexed",
        source="scan",
    )

    settings = PreviewSettings()
    result = data_asset_registry.parse_preview(item, settings)
    assert result.status == "indexed"
    assert result.format == "las"


def test_register_format_custom():
    custom_registry = DataAssetRegistry()

    spec = FormatSpec(
        format_id="xyz",
        extensions={"xyz"},
        resource_type="custom_type",
        status="indexed",
        preview_parser=lambda item, settings: None,  # type: ignore
    )
    custom_registry.register_format(spec)

    res_type, res_fmt, status = custom_registry.classify_path(Path("test.xyz"))
    assert res_type == "custom_type"
    assert res_fmt == "xyz"
    assert status == "indexed"


def test_scan_directory_uses_registered_format_spec(tmp_path: Path):
    """#626: scan_directory must classify via FormatSpec, not the static table."""
    from paleo_workbench.resources.classifier import classify_path as static_classify

    custom_registry = DataAssetRegistry()
    custom_registry.register_format(
        FormatSpec(
            format_id="xyz",
            extensions={"xyz"},
            resource_type="custom_type",
            status="registered",
        )
    )
    path = tmp_path / "probe.xyz"
    path.write_text("hello\n", encoding="utf-8")
    # Static classifier treats unknown extensions as generic / unknown.
    static_type, static_fmt, _ = static_classify(path)
    assert static_type != "custom_type"

    items = custom_registry.scan_directory(tmp_path)
    assert len(items) == 1
    assert items[0].name == "probe.xyz"
    assert items[0].type == "custom_type"
    assert items[0].format == "xyz"
    assert items[0].status == "registered"


def test_preview_registry_uses_registered_parser(tmp_path: Path):
    """#626: PreviewRegistry.register_format must win over the hardcoded chain."""
    from paleo_workbench.resources.preview_parsers.models import PreviewResult
    from paleo_workbench.resources.preview_parsers.registry import PreviewRegistry

    path = tmp_path / "probe.xyz"
    path.write_text("hello\n", encoding="utf-8")
    item = ResourceItem(
        name="probe.xyz",
        path=str(path),
        type="unknown",
        format="xyz",
        status="indexed",
    )

    def _xyz_preview(asset, settings):
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            format="xyz",
            status="indexed",
            type_label="custom_type",
            message="registered-xyz-parser",
        )

    registry = PreviewRegistry()
    registry.register_format("xyz", _xyz_preview)
    result = registry.build_preview(item, PreviewSettings())
    assert result.message == "registered-xyz-parser"
    assert result.type_label == "custom_type"
