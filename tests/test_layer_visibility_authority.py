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
    opacity: float = 1.0
    crs: str = ""
    source_ref: str = ""
    type: str = "vector"


class _FakeRegistry:
    def __init__(self) -> None:
        self._layers: dict[str, _FakeLayer] = {}

    def get(self, layer_id: str):
        return self._layers.get(layer_id)

    def layers(self):
        return list(self._layers.values())

    def remove(self, layer_id: str) -> None:
        self._layers.pop(layer_id, None)

    # hierarchy/ordering surface used by _restore_unified_composition_state
    def set_parent(self, layer_id: str, parent_id: str) -> None:
        return None

    def parent_id(self, layer_id: str) -> str:
        return ""

    def index_of(self, layer_id: str) -> int:
        for index, layer in enumerate(self.layers()):
            if layer.id == layer_id:
                return index
        return -1

    def move_layer(self, layer_id: str, to_index: int) -> None:
        return None


class _FakeScene:
    def __init__(self) -> None:
        self.registry = _FakeRegistry()
        self.visible_calls: list[tuple[str, bool]] = []

    # rendering surface used by _refresh_unified_composition (stubbed
    # collaborators of the unavailable C++ backend)
    def render_snapshot(self, project_crs: str = ""):
        class _Snap:
            def __init__(self) -> None:
                self.layers = ()
                self.project_crs = project_crs

        return _Snap()

    def vector_style(self, layer_id: str) -> dict:
        return {}

    def set_vector_style(self, layer_id: str, style) -> None:
        return None

    def scalar_layer(self, layer_id: str):
        return None

    def scalar_style(self, layer_id: str) -> dict:
        return {}

    def vector_features(self, layer_id: str):
        return ()

    # production load-path surface used by _on_document_selected
    def is_dirty(self) -> bool:
        return False

    def load_document(self, document) -> None:
        return None

    def set_layer_visible(self, key: str, visible: bool) -> None:
        self.visible_calls.append((key, bool(visible)))

    def command_stack(self):
        return None


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


def test_production_document_selected_uses_kind_visibility(qtbot, monkeypatch):
    """The _on_document_selected load path consumes _kind_visibility.

    #1179: previously an unconditional skip with a false coverage claim.
    The REAL load sequence runs; only the C++-dependent refresh pipeline
    is stubbed (same seam as the neighboring write-through test).
    """
    from paleo_workbench.ui.pages.mapping_page import MappingPage as _MP

    monkeypatch.setattr(_MP, "_refresh_unified_composition", lambda self: None)
    page, document, scene = _page_with_document(qtbot)
    # _edit_scene() returns the graphics edit view's scene; point it at the
    # fake so the production load path is observed (same seam style as the
    # neighboring tests, which stub collaborators of the C++ backend).
    monkeypatch.setattr(_MP, "_edit_scene", lambda self: scene)
    scene.registry.get("map-vis:facies").visible = False
    page._on_document_selected(document)
    by_key = dict(scene.visible_calls)
    assert by_key["facies"] is False
    assert by_key["well"] is True
    assert set(by_key) == {"facies", "well", "line", "label"}



def test_legacy_tree_toggle_writes_through_to_registry(qtbot, monkeypatch):
    """A legacy checkbox toggle must not be dropped once the registry owns
    the kind (#1033 write-through): the REAL handler runs, only the
    C++-dependent refresh pipeline is stubbed."""
    from paleo_workbench.ui.pages.mapping_page import MappingPage as _MP

    monkeypatch.setattr(_MP, "_refresh_unified_composition", lambda self: None)
    page, document, scene = _page_with_document(qtbot)
    layer = scene.registry.get("map-vis:line")
    assert layer.visible is True

    # simulate the legacy tree flipping its checkbox and emitting
    page._on_layer_visibility_changed("line", False)

    assert layer.visible is False
    assert page._kind_visibility("line") is False
    assert page._edit_scene().layer_is_visible("line") is False
