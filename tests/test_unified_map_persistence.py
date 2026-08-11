"""Semantic save/reopen coverage for the primary map-authoring canvas."""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.reference_layers import ReferenceLayerService
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_unified_canvas_persists_style_chrome_extent_and_layer_exclusions(tmp_path, qtbot) -> None:
    project = ProjectDocument.new(name="Unified map")
    document = PaleoMapDocument(
        id="persist-map",
        name="Initial",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [10, 0], [0, 10]]},
        ],
        line_features=[{"id": "l1", "name": "fault", "coordinates": [[0, 0], [10, 10]]}],
    )
    project.paleomap_documents.append(document)
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state(project.paleomap_documents, project_crs="EPSG:3857")
    page.unified_canvas.set_extent((1.0, 2.0, 11.0, 12.0))
    page._apply_layer_properties(
        "persist-map:facies",
        {
            "name": "Styled facies", "crs": "EPSG:3857", "opacity": 0.45,
            "style": {"fill": "#e03131", "stroke": "#ffffff", "stroke_width": 2.0,
                      "labels": {"field": "name", "size": 10.0}},
        },
    )
    page._on_chrome_changed({"title": "Final compilation", "elements": ["图例", "比例尺"]})
    tree = page._native_layer_tree
    assert tree is not None
    tree.tree.setCurrentIndex(tree.model._index_for_id("persist-map:line"))
    tree.remove_action.trigger()
    assert page.save_draft()

    manager = ProjectManager(tmp_path / "unified-map.paleo.json")
    manager.save(project)
    reopened = manager.load().paleomap_documents[0]
    restored = MappingPage()
    qtbot.addWidget(restored)
    restored.update_state([reopened], project_crs="EPSG:3857")

    facies = restored.unified_scene.registry.get("persist-map:facies")
    assert facies is not None
    assert facies.name == "Styled facies"
    assert facies.opacity == pytest.approx(0.45)
    assert restored.unified_scene.vector_style("persist-map:facies")["labels"]["field"] == "name"
    assert restored.unified_canvas.view_extent == (1.0, 2.0, 11.0, 12.0)
    assert reopened.map_chrome["title"] == "Final compilation"
    assert restored.unified_scene.registry.get("persist-map:line") is None


def test_unified_canvas_reopens_reference_source_through_the_same_composition(tmp_path, qtbot) -> None:
    source = tmp_path / "faults.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Fault A"},
                        "geometry": {"type": "LineString", "coordinates": [[120.0, 30.0], [120.1, 30.1]]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    project = ProjectDocument.new(name="Reference map")
    document = PaleoMapDocument(id="reference-map", name="Map", linked_target_horizon="H1")
    document.reference_layers.append(ReferenceLayerService().import_layer(source, "EPSG:3857"))
    project.paleomap_documents.append(document)
    manager = ProjectManager(tmp_path / "reference-map.paleo.json")
    manager.save(project)

    reopened = manager.load().paleomap_documents[0]
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([reopened], project_crs="EPSG:3857")

    layer_id = f"reference-map:reference:{reopened.reference_layers[0].id}"
    assert page.unified_scene.registry.get(layer_id) is not None
    assert page.unified_scene.vector_features(layer_id)[0]["properties"]["name"] == "Fault A"
