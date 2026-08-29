from pathlib import Path

import pytest

from paleo_workbench.resources.import_service import import_files
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.manager import project_backup_path
from paleo_workbench.project.models import (
    ExportArtifact,
    HorizonInterpretationRef,
    ProjectDocument,
    ResourceItem,
)
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
    data_file.write_text("~Version\n", encoding="utf-8", newline="")

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
    source.write_text("~Version\n", encoding="utf-8", newline="")

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
    data_file.write_text("~Version\n", encoding="utf-8", newline="")

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


def test_clean_save_after_load_is_a_true_noop(tmp_path: Path, monkeypatch):
    """A reopened, untouched project avoids artifact/path/JSON save work."""
    project_path = tmp_path / "demo.paleo.json"
    resource = tmp_path / "data" / "well.las"
    resource.parent.mkdir()
    resource.write_text("~Version\n", encoding="utf-8", newline="")
    project = ProjectDocument.new("Demo")
    project.resources.append(
        ResourceItem(name="well", path=str(resource), type="well_log", format="las")
    )
    ProjectManager(project_path).save(project)
    manager = ProjectManager(project_path)
    loaded = manager.load()
    before = project_path.read_bytes()

    import paleo_workbench.project.manager as manager_module

    monkeypatch.setattr(
        manager_module,
        "persist_factor_grid_artifacts",
        lambda *_args: pytest.fail("clean save must not inspect factor artifacts"),
    )
    assert manager.save(loaded) is False
    assert manager.last_save_stats.wrote_project_file is False
    assert project_path.read_bytes() == before


def test_metadata_only_save_reuses_resource_path_section(tmp_path: Path, monkeypatch):
    project_path = tmp_path / "demo.paleo.json"
    resource = tmp_path / "data" / "well.las"
    resource.parent.mkdir()
    resource.write_text("~Version\n", encoding="utf-8", newline="")
    project = ProjectDocument.new("Before")
    project.resources.append(
        ResourceItem(name="well", path=str(resource), type="well_log", format="las")
    )
    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()
    loaded.meta.name = "After"

    import paleo_workbench.project.manager as manager_module

    monkeypatch.setattr(
        manager_module,
        "relativize_path",
        lambda *_args: pytest.fail("metadata save must reuse resource paths"),
    )
    assert manager.save(loaded) is True
    assert manager.last_save_stats.dirty_domains
    assert ProjectManager(project_path).load().meta.name == "After"


def test_project_backup_recovers_corrupt_canonical_json(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    manager = ProjectManager(project_path)
    project = ProjectDocument.new("First")
    manager.save(project)
    project.meta.name = "Second"
    manager.save(project)
    backup = project_backup_path(project_path)
    assert backup.is_file()

    project_path.write_text("{ truncated", encoding="utf-8", newline="")
    recovered = ProjectManager(project_path)
    loaded = recovered.load()

    assert loaded.meta.name == "First"
    assert recovered.last_recovery_message
    assert project_path.is_file()


def test_load_cleans_only_owned_project_temp_files(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    manager = ProjectManager(project_path)
    manager.save(ProjectDocument.new("Demo"))
    owned = tmp_path / ".demo.paleo.json.interrupted.tmp"
    unrelated = tmp_path / ".other.paleo.json.interrupted.tmp"
    owned.write_text("partial", encoding="utf-8", newline="")
    unrelated.write_text("user file", encoding="utf-8", newline="")

    manager.load()

    assert not owned.exists()
    assert unrelated.exists()


def test_metadata_save_does_not_touch_immutable_interpretation_payload(tmp_path: Path):
    """A title edit is metadata-only, never an interpretation artifact rewrite."""
    project_path = tmp_path / "demo.paleo.json"
    payload = tmp_path / "demo.artifacts" / "outputs" / "horizon-v3.npz"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"immutable-horizon-v3")
    project = ProjectDocument.new("Before")
    project.horizon_interpretations.append(
        HorizonInterpretationRef(
            name="Horizon V3",
            horizon_key="H3",
            current_version_id="version_h3",
            artifact_path=payload.as_posix(),
        )
    )
    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()
    before_bytes = payload.read_bytes()
    before_mtime_ns = payload.stat().st_mtime_ns

    loaded.meta.name = "After"
    assert manager.save(loaded) is True

    assert payload.read_bytes() == before_bytes
    assert payload.stat().st_mtime_ns == before_mtime_ns


def test_external_resource_paths_remain_absolute_and_external(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    external_file = tmp_path.parent / "shared" / "regional.las"
    external_file.parent.mkdir(parents=True, exist_ok=True)
    external_file.write_text("~Version\n", encoding="utf-8", newline="")

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
    export_file.write_text("png", encoding="utf-8", newline="")

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
