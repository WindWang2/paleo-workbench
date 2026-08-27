"""#1033 — the LayerRegistry is the single visibility authority.

``_refresh_unified_composition`` used the hidden legacy ``MapLayerTree``
checkbox state as its hardcoded visibility provider, so a native-tree toggle
could be overwritten by stale legacy state on adapter rebuilds (document
switch, ``clear()``, missing composition state), and the edit scene was
force-fed the same stale values.

The native C++ ``MapScene`` backend (``layer_model_core``/``grid_render_core``)
is optional and often unbuilt in dev checkouts, so these tests inject a
minimal registry-backed scene stand-in — only the unavailable C++ dependency
is substituted; every line of resolution logic under test is production code.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage

KINDS = ("facies", "well", "line", "label")


@dataclass
class _FakeLayer:
    id: str
    visible: bool = True
    name: str = ""


class _FakeRegistry:
    def __init__(self) -> None:
        self._layers: dict[str, _FakeLayer] = {}

    def get(self, layer_id: str):
        return self._layers.get(layer_id)

    def layers(self):
        return list(self._layers.values())

    def remove(self, layer_id: str) -> None:
        self._layers.pop(layer_id, None)


class _FakeScene:
    def __init__(self) -> None:
        self.registry = _FakeRegistry()


def _page_with_document(
    qtbot, document_id: str = "map-vis"
) -> tuple[MappingPage, PaleoMapDocument, _FakeScene]:
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(
        id=document_id,
        name="Visibility Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "delta", "coordinates": [[0, 0], [4, 0], [0, 4]]}
        ],
        line_features=[
            {"id": "l1", "name": "contour", "coordinates": [[0, 0], [4, 4]]}
        ],
    )
    page.update_state([document])
    scene = _FakeScene()
    for kind in KINDS:
        scene.registry._layers[f"{document_id}:{kind}"] = _FakeLayer(f"{document_id}:{kind}")
    page._unified_scene_adapter.scene = scene
    return page, document, scene


def test_visibility_resolution_prefers_registry_over_legacy_tree(qtbot):
    page, document, scene = _page_with_document(qtbot)
    scene.registry.get("map-vis:well").visible = False
    # legacy tree still says visible (stale)
    page.layer_tree._layer_visible["well"] = True

    assert page._kind_visibility("well") is False


def test_composition_visibility_uses_registry_for_every_kind(qtbot):
    page, document, scene = _page_with_document(qtbot)
    scene.registry.get("map-vis:facies").visible = False
    scene.registry.get("map-vis:label").visible = False

    visibility = page._composition_visibility()
    assert visibility == {
        "facies": False,
        "well": True,
        "line": True,
        "label": False,
    }


def test_visibility_falls_back_to_persisted_composition_state(qtbot):
    page, document, scene = _page_with_document(qtbot)
    # simulate staged composition (same shape _layer_registry_state writes)
    document.layer_state = {
        "composition": [
            {"id": "map-vis:line", "visible": False},
            {"id": "map-vis:well", "visible": True},
        ]
    }
    # registry entry disappears (e.g. composition cleared for rebuild)
    scene.registry.remove("map-vis:line")

    assert page._kind_visibility("line") is False
    assert page._kind_visibility("well") is True


def test_visibility_seeds_from_legacy_tree_only_without_any_state(qtbot):
    page, document, scene = _page_with_document(qtbot)
    scene.registry.remove("map-vis:label")
    page.layer_tree._layer_visible["label"] = False
    assert page._kind_visibility("label") is False


def test_persisted_state_of_other_document_does_not_leak(qtbot):
    page, document, scene = _page_with_document(qtbot)
    document.layer_state = {
        "composition": [
            {"id": "other-doc:facies", "visible": False},
            {"id": "map-vis:facies", "visible": True},
        ]
    }
    scene.registry.remove("map-vis:facies")
    assert page._kind_visibility("facies") is True


def test_edit_scene_load_applies_registry_visibility_not_stale_legacy(qtbot, monkeypatch):
    """The ``scene.set_layer_visible`` sites after ``load_document`` must not
    force legacy checkbox state over authored registry state."""
    # Isolate from the native unified-scene refresh machinery (optional C++
    # backend); the resolution logic under test is fully production code.
    monkeypatch.setattr(
        MappingPage, "_refresh_unified_composition", lambda self: None
    )
    page, document, scene = _page_with_document(qtbot)
    scene.registry.get("map-vis:facies").visible = False
    document.layer_state = {"composition": [{"id": "map-vis:facies", "visible": False}]}
    # legacy tree disagrees (stale True)
    page.layer_tree._layer_visible["facies"] = True

    edit_scene = page._edit_scene()
    assert edit_scene is not None
    edit_scene.load_document(document)
    for key in KINDS:
        edit_scene.set_layer_visible(key, page._kind_visibility(key))

    assert edit_scene.layer_is_visible("facies") is False
    assert edit_scene.layer_is_visible("well") is True
