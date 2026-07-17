from pathlib import Path

import pytest

from paleo_workbench.resources.import_service import import_files
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.project.paths import artifact_dir_for


def test_failed_atomic_replace_does_not_advance_in_memory_updated_at(
    tmp_path: Path, monkeypatch
):
    from paleo_workbench.project import manager as manager_module

    project = ProjectDocument.new(name="Transaction")
    original_updated_at = project.meta.updated_at
    manager = ProjectManager(tmp_path / "demo.paleo.json")
    monkeypatch.setattr(manager_module, "_now_iso", lambda: "2099-01-01T00:00:00+00:00")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(manager_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        manager.save(project)

    assert project.meta.updated_at == original_updated_at
    assert not manager.project_path.exists()


def test_project_round_trip_uses_relative_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_file = tmp_path / "data" / "well.las"
    data_file.parent.mkdir()
    data_file.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(
            name="well.las",
            path=str(data_file),
            type="well_log",
            format="las",
            status="indexed",
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.resources[0].path == data_file.resolve().as_posix()
    assert loaded.resources[0].external is False
    assert artifact_dir_for(project_path) == tmp_path / "demo.artifacts"


def test_lightweight_import_classification_round_trips_as_project_content(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    source = tmp_path / "data" / "well.las"
    source.parent.mkdir()
    source.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.extend(
        import_files([source], existing=[], project_path=project_path).added
    )
    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.resources[0].type == "well_log"
    assert loaded.resources[0].format == "las"
    assert loaded.resources[0].checksum is None
    assert loaded.resources[0].parsed_summary["size_bytes"] == len(b"~Version\n")


def test_resaving_loaded_project_keeps_relative_resource_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_file = tmp_path / "data" / "well.las"
    data_file.parent.mkdir()
    data_file.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(
            name="well.las",
            path=str(data_file),
            type="well_log",
            format="las",
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()
    manager.save(loaded)
    reloaded = manager.load()

    assert reloaded.resources[0].path == data_file.resolve().as_posix()
    assert reloaded.resources[0].external is False


def test_external_resource_paths_remain_absolute_and_external(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    external_file = tmp_path.parent / "shared" / "regional.las"
    external_file.parent.mkdir(parents=True, exist_ok=True)
    external_file.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(
            name="regional.las",
            path=str(external_file),
            type="well_log",
            format="las",
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.resources[0].path == external_file.resolve().as_posix()
    assert loaded.resources[0].external is True


def test_reference_layer_external_and_offline_round_trip(tmp_path: Path):
    from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument

    project_path = tmp_path / "demo.paleo.json"
    # Source outside project dir → external=True after save
    external_ref = tmp_path.parent / "shared_ref" / "faults.geojson"
    external_ref.parent.mkdir(parents=True, exist_ok=True)
    external_ref.write_text(
        '{"type":"FeatureCollection","features":[]}',
        encoding="utf-8",
    )

    project = ProjectDocument.new(name="Demo")
    map_doc = PaleoMapDocument(
        name="Map",
        linked_target_horizon="H1",
        reference_layers=[
            MapReferenceLayer(
                name="断层",
                source_path=str(external_ref),
                source_kind="vector",
                source_crs="EPSG:4326",
                project_crs="EPSG:3857",
            ),
            MapReferenceLayer(
                name="缺失",
                source_path=str(tmp_path / "gone.geojson"),
                source_kind="vector",
                source_crs="EPSG:4326",
                project_crs="EPSG:3857",
            ),
        ],
    )
    project.paleomap_documents.append(map_doc)

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    layers = loaded.paleomap_documents[0].reference_layers
    by_name = {layer.name: layer for layer in layers}
    assert by_name["断层"].external is True
    assert by_name["断层"].status == "ready"
    assert by_name["断层"].source_path == external_ref.resolve().as_posix()
    assert by_name["缺失"].status == "offline"
    assert "不可用" in by_name["缺失"].error_message


def test_export_artifact_output_path_is_relativized_when_inside_project(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    export_file = tmp_path / "exports" / "demo.png"
    export_file.parent.mkdir()
    export_file.write_text("png", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.export_artifacts.append(
        ExportArtifact(
            linked_id="map_1",
            format="png",
            output_path=str(export_file),
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.export_artifacts[0].output_path == export_file.resolve().as_posix()


def test_loaded_relative_pdf_path_is_ready_for_preview(tmp_path: Path):
    from paleo_workbench.ui.pages.preview_provider import PreviewProvider

    project_path = tmp_path / "demo.paleo.json"
    pdf_path = tmp_path / "documents" / "report.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(
            name="report.pdf",
            path=str(pdf_path),
            type="document",
            format="pdf",
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    result = PreviewProvider().preview(loaded.resources[0])

    assert loaded.resources[0].path == pdf_path.resolve().as_posix()
    assert result.mode == "pdf"
