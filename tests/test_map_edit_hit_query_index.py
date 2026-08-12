"""Regression coverage for bounded legacy edit-scene feature picking."""

from __future__ import annotations

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_items import WellPointItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


def _well_document(count: int) -> PaleoMapDocument:
    return PaleoMapDocument(
        name="many wells",
        linked_target_horizon="H",
        well_overlays=[
            {"id": f"well-{index}", "name": f"Well {index}", "x": float(index * 10), "y": 0.0}
            for index in range(count)
        ],
    )


def test_stable_queries_do_not_reserialize_every_visible_feature(monkeypatch, qtbot) -> None:
    scene = MapEditScene()
    scene.load_document(_well_document(1_000))
    original = WellPointItem.to_record
    calls = 0

    def counted(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(WellPointItem, "to_record", counted)
    for _ in range(20):
        assert scene.hit_test_at(5_000.0, 0.0, tolerance=0.5) == "well-500"

    diagnostics = scene.hit_query_diagnostics()
    assert calls == 0
    assert diagnostics["record_build_count"] == 1_000
    assert diagnostics["rebuild_count"] == 1
    assert diagnostics["candidate_count"] < 100


def test_feature_level_edits_and_history_keep_the_query_index_correct(qtbot) -> None:
    scene = MapEditScene()
    scene.load_document(_well_document(1))

    assert scene.create_feature({"id": "new", "kind": "well", "coordinates": [20.0, 0.0]}) == "new"
    assert scene.hit_test_at(20.0, 0.0, tolerance=0.5) == "new"
    assert scene.undo()
    assert scene.hit_test_at(20.0, 0.0, tolerance=0.5) is None
    assert scene.redo()
    assert scene.hit_test_at(20.0, 0.0, tolerance=0.5) == "new"

    scene.translate_features(["new"], 10.0, 0.0)
    assert scene.hit_test_at(30.0, 0.0, tolerance=0.5) == "new"
    assert scene.undo()
    assert scene.hit_test_at(20.0, 0.0, tolerance=0.5) == "new"
    assert scene.redo()
    assert scene.hit_test_at(30.0, 0.0, tolerance=0.5) == "new"

    scene.set_layer_visible("well", False)
    assert scene.hit_test_at(30.0, 0.0, tolerance=0.5) is None
    scene.set_layer_visible("well", True)
    assert scene.hit_test_at(30.0, 0.0, tolerance=0.5) == "new"
    scene.clear_features()
    assert scene.hit_test_at(30.0, 0.0, tolerance=0.5) is None
    assert scene.hit_query_diagnostics()["entries"] == 0
