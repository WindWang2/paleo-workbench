from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_save_draft_merges_view_state_preserving_provenance(qtbot):
    """Viewport center/scale are written; is_demo_draft / seed stay intact."""
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]],
        }],
        view_state={
            "generator": "deterministic-map-draft-v1",
            "is_demo_draft": True,
            "seed": 7,
        },
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])
    page.edit_view.apply_view_state({"center": (12.5, 34.0), "scale": 2.5})
    # Mark dirty so save is meaningful (view alone may not dirty scene)
    page.edit_view.scene().translate_features(["f1"], 0.1, 0.0)

    assert page.save_draft() is True
    assert doc.view_state["is_demo_draft"] is True
    assert doc.view_state["seed"] == 7
    assert doc.view_state["generator"] == "deterministic-map-draft-v1"
    assert doc.view_state["center"] == [12.5, 34.0]
    assert doc.view_state["scale"] == 2.5


def test_update_state_restores_view_state(qtbot):
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
        view_state={"center": [40.0, 50.0], "scale": 3.0, "is_demo_draft": True},
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])

    state = page.edit_view.view_state()
    assert state["center"] == (40.0, 50.0)
    assert state["scale"] == 3.0


def test_save_draft_writes_document(qtbot):
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]],
        }],
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])
    # move feature via scene API if exposed
    page.edit_view.scene().translate_features(["f1"], 1.0, 0.0)
    assert page.is_dirty()
    assert page.toolbar.save_draft_btn.isEnabled() is True

    saved = []
    page.draft_saved.connect(saved.append)
    page.save_draft()
    assert not page.is_dirty()
    assert page.toolbar.save_draft_btn.isEnabled() is False
    assert saved == [doc]
    assert doc.facies_polygons[0]["coordinates"][0][0] == 1.0


def test_save_draft_includes_new_lines_and_labels(qtbot):
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])
    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)

    scene.create_feature({
        "id": "ln1",
        "kind": "line",
        "name": "F1",
        "coordinates": [[0, 0], [3, 3]],
    })
    scene.create_feature({
        "id": "lb1",
        "kind": "label",
        "name": "注记",
        "text": "注记",
        "coordinates": [1.5, 1.5],
    })
    assert page.is_dirty()
    page.save_draft()
    assert not page.is_dirty()
    assert len(doc.line_features) == 1
    assert doc.line_features[0]["id"] == "ln1"
    assert len(doc.label_features) == 1
    assert doc.label_features[0]["id"] == "lb1"
    assert doc.label_features[0]["text"] == "注记"


def test_save_draft_disabled_without_document(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([])
    assert page.toolbar.save_draft_btn.isEnabled() is False
    assert page.save_draft() is False


def test_export_features_matches_scene_items(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "W", "x": 1, "y": 1}],
        line_features=[{"id": "ln1", "name": "L", "coordinates": [[0, 0], [1, 1]]}],
        label_features=[{"id": "lb1", "text": "T", "anchor": [0.5, 0.5]}],
    )
    scene.load_document(doc)
    exported = scene.export_features()
    ids = {r["id"] for r in exported}
    assert ids == {"f1", "w1", "ln1", "lb1"}
    assert scene.features_to_records() == exported
