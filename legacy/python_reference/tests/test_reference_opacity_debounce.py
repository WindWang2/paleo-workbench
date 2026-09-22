"""#654: reference-layer opacity drags must not recompose on every slider tick."""

from __future__ import annotations

from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_reference_opacity_drag_debounces_unified_refresh(qtbot) -> None:
    page = MappingPage()
    qtbot.addWidget(page)
    layer = MapReferenceLayer(
        id="ref_1",
        name="构造参考",
        source_path="/tmp/ref.geojson",
        source_kind="vector",
        source_crs="EPSG:4326",
        project_crs="EPSG:3857",
        opacity=1.0,
    )
    document = PaleoMapDocument(
        id="map-1",
        name="Map",
        linked_target_horizon="H1",
        reference_layers=[layer],
    )
    page.update_state([document], project_crs="EPSG:3857")

    calls = {"n": 0}
    real = page._refresh_unified_composition

    def counting() -> None:
        calls["n"] += 1
        real()

    page._refresh_unified_composition = counting  # type: ignore[method-assign]
    calls["n"] = 0

    for tick in range(100):
        page._on_reference_opacity_changed("ref_1", tick / 100.0)

    assert layer.opacity == 0.99
    assert calls["n"] == 0
    qtbot.waitUntil(lambda: calls["n"] >= 1, timeout=1000)
    assert calls["n"] == 1
    assert layer.opacity == 0.99
