"""Map-document migration to host-owned vector authoring state."""

from paleo_workbench.mapping.map_authoring import MapAuthoringDocument
from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument


def _document() -> PaleoMapDocument:
    return PaleoMapDocument(
        id="map-a",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "facies-1", "name": "delta", "coordinates": [[0, 0], [5, 0], [0, 5]]}
        ],
        well_overlays=[{"id": "well-1", "name": "A", "x": 2, "y": 3}],
        line_features=[{"id": "line-1", "name": "fault", "coordinates": [[0, 0], [5, 5]]}],
        label_features=[{"id": "label-1", "text": "delta", "anchor": [1, 1]}],
    )


def test_authoring_document_migrates_all_legacy_geometry_kinds() -> None:
    authoring = MapAuthoringDocument.from_document(_document(), project_crs="EPSG:3857")

    assert authoring.layer("facies").feature("facies-1").geometry["type"] == "Polygon"
    assert authoring.layer("well").feature("well-1").geometry["type"] == "Point"
    assert authoring.layer("line").feature("line-1").geometry["type"] == "LineString"
    assert authoring.layer("label").feature("label-1").attributes["text"] == "delta"


def test_authoring_document_keeps_edits_buffered_until_explicit_commit() -> None:
    authoring = MapAuthoringDocument.from_document(_document())
    session = authoring.start_editing("facies")
    session.move_feature("facies-1", 10, 0)
    session.add_feature(
        VectorFeature("facies-2", {"type": "Polygon", "coordinates": [[[6, 0], [8, 0], [6, 2], [6, 0]]]})
    )

    assert authoring.layer("facies").feature_ids() == ("facies-1",)
    assert {record["id"] for record in authoring.records()} >= {"facies-1", "facies-2"}

    audit = authoring.commit_changes()

    assert authoring.layer("facies").feature_ids() == ("facies-1", "facies-2")
    assert [entry["command_type"] for entry in audit] == ["move_feature", "add_feature"]


def test_authoring_attribute_edits_share_the_active_edit_undo_stack() -> None:
    authoring = MapAuthoringDocument.from_document(_document())
    session = authoring.start_editing("label")

    assert authoring.change_attribute("label-1", "text", "shoreline")
    assert session.feature("label-1").attributes["text"] == "shoreline"
    assert session.undo()
    assert session.feature("label-1").attributes["text"] == "delta"


def test_authoring_presentation_state_round_trips_with_a_project(tmp_path) -> None:
    project = ProjectDocument.new(name="Authoring")
    document = _document()
    authoring = MapAuthoringDocument.from_document(document, project_crs="EPSG:3857")
    authoring.set_active_kind("line")
    authoring.layer("facies").style = {"fill": "#123456", "stroke": "#ffffff"}
    authoring.layer("label").labels = {"field": "text", "size": 11}
    document.map_crs = "EPSG:3857"
    document.layer_state = authoring.state()
    document.view_state = {"extent": [0.0, 0.0, 10.0, 10.0]}
    project.paleomap_documents.append(document)

    manager = ProjectManager(tmp_path / "authoring.paleo.json")
    manager.save(project)
    reopened = manager.load().paleomap_documents[0]
    restored = MapAuthoringDocument.from_document(reopened)

    assert reopened.map_crs == "EPSG:3857"
    assert reopened.view_state["extent"] == [0.0, 0.0, 10.0, 10.0]
    assert restored.active_kind == "line"
    assert restored.layer("facies").style["fill"] == "#123456"
    assert restored.layer("label").labels["field"] == "text"
    snapshot = document_render_snapshot(reopened, project_crs="EPSG:3857")
    facies = next(layer for layer in snapshot.layers if layer.id.endswith(":facies"))
    labels = next(layer for layer in snapshot.layers if layer.id.endswith(":label"))
    assert facies.style["fill"] == "#123456"
    assert labels.style["labels"]["field"] == "text"
