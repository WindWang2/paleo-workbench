"""Tests for unified export / richer importers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.resources.export_service import (
    export_asset_to_path,
    export_project_inventory,
    list_asset_export_labels,
)
from paleo_workbench.resources.exporters import get_available_formats, las_to_json_summary
from paleo_workbench.resources.import_service import import_files
from paleo_workbench.resources.classifier import classify_path


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 2.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. T1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def test_las_export_formats_include_csv_xlsx_json():
    res = ResourceItem(name="w.las", path="/w.las", type="well_log", format="las")
    labels = {lbl for lbl, _ in get_available_formats(res)}
    assert "CSV" in labels
    assert "XLSX" in labels
    assert "JSON" in labels


def test_las_to_json_summary(tmp_path: Path):
    src = tmp_path / "w.las"
    _minimal_las(src)
    out = tmp_path / "w.summary.json"
    las_to_json_summary(src, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["curve_count"] >= 1
    assert any(c["mnemonic"] == "GR" for c in data["curves"])


def test_export_asset_registers_artifact(tmp_path: Path):
    src = tmp_path / "w.las"
    _minimal_las(src)
    project = ProjectDocument.new("Exp")
    res = ResourceItem(
        name="w.las", path=str(src), type="well_log", format="las"
    )
    project.resources.append(res)
    out = tmp_path / "w.csv"
    result = export_asset_to_path(res, "CSV", out, project=project, register=True)
    assert result.success
    assert out.exists()
    assert len(project.export_artifacts) == 1
    assert project.export_artifacts[0].format == "csv"


def test_export_project_inventory(tmp_path: Path):
    project = ProjectDocument.new("Inv")
    project.resources.append(
        ResourceItem(name="a.las", path="/a.las", type="well_log", format="las")
    )
    out = tmp_path / "inv.json"
    result = export_project_inventory(project, out, register=True)
    assert result.success
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["resource_count"] == 1
    assert data["resources"][0]["name"] == "a.las"
    assert len(project.export_artifacts) == 1


def test_import_enriches_summary_and_role(tmp_path: Path):
    src = tmp_path / "w.las"
    _minimal_las(src)
    report = import_files([src], [])
    assert report.added_count == 1
    item = report.added[0]
    assert item.type == "well_log"
    assert item.artifact_role == "input"
    assert item.parsed_summary.get("size_bytes", 0) > 0
    assert "type_label" in item.parsed_summary
    assert "测井" in report.summary_text()


def test_classify_geojson():
    assert classify_path(Path("facies.geojson"))[0] == "geojson"
    assert classify_path(Path("points.shp"))[0] == "vector"


def test_list_asset_export_labels():
    res = ResourceItem(name="t.csv", path="/t.csv", type="tabular", format="csv")
    labels = list_asset_export_labels(res)
    assert "JSON" in labels
    assert "XLSX" in labels
