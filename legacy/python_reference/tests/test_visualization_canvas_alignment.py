"""Workbench 可视化 uses the same primary geoviz canvas types as geo-viz pages."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QScrollArea

import numpy as np
from geoviz import (
    CrossWellCanvas,
    PaleoMapCanvas,
    SeismicView,
    WellLogCanvas,
    WellTieCanvas,
)

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.viz.adapter import VizAdapter


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. ALIGN:",
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


def test_composite_hosts_same_primary_canvases_as_geoviz_pages(qtbot):
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)
    assert isinstance(panel.well_canvas, WellLogCanvas)
    assert isinstance(panel.seismic_view, SeismicView)
    assert isinstance(panel.cross_well_canvas, CrossWellCanvas)
    assert isinstance(panel.map_canvas, PaleoMapCanvas)
    assert isinstance(panel.well_tie_canvas, WellTieCanvas)
    tab_widget = panel.tabs.widget(panel._tab_index("连井"))
    inner_canvas = tab_widget.widget() if isinstance(tab_widget, QScrollArea) else tab_widget
    assert inner_canvas is panel.cross_well_canvas
    assert panel.tabs.widget(panel._tab_index("井震标定")) is panel.well_tie_canvas


def test_open_ref_loads_las_into_well_log_canvas(qtbot, tmp_path: Path):
    path = tmp_path / "align.las"
    _minimal_las(path)
    project = ProjectDocument.new("Align")
    res = ResourceItem(name="align.las", path=str(path), type="well_log", format="las")
    project.resources.append(res)

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(project.resources, [], [])
    ref = VizAdapter().ref_from_resource(res)
    assert ref is not None
    page.open_ref(ref)
    # #842: cold-cache LAS opens are asynchronous — wait for the payload.
    qtbot.waitUntil(
        page.composite_panel.has_well_log_loaded, timeout=10_000
    )

    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "测井"
    assert page.composite_panel.has_well_log_loaded()
    assert page.composite_panel.cross_well_widget.canvas_count >= 1


def test_open_ref_loads_seismic_into_seismic_view(qtbot, tmp_path: Path, monkeypatch):
    path = tmp_path / "v.sgy"
    path.write_bytes(b"fake")
    project = ProjectDocument.new("S")
    res = ResourceItem(name="v.sgy", path=str(path), type="seismic", format="sgy")
    project.resources.append(res)
    page = VisualizationPage()
    qtbot.addWidget(page)
    loaded = []
    monkeypatch.setattr(
        page.composite_panel.seismic_host.widget,
        "load_segy_async",
        loaded.append,
    )
    page.update_state(project.resources, [], [])
    page.open_ref(VizAdapter().ref_from_resource(res))
    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "地震"
    assert loaded == [str(path)]


def test_open_ref_loads_map_into_paleomap_canvas(qtbot):
    doc = PaleoMapDocument(
        name="PM",
        linked_target_horizon="C6",
        facies_polygons=[
            {
                "id": "f1",
                "name": "三角洲",
                "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
            }
        ],
        well_overlays=[{"name": "A1", "lng": 0.2, "lat": 0.3}],
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([], [], [doc])
    page.open_ref(VizAdapter().ref_from_map_document(doc))
    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "古地理"
    assert isinstance(page.composite_panel.map_canvas, PaleoMapCanvas)


def test_no_src_pages_import_in_workbench_viz():
    """Workbench must not import geo-viz app pages."""
    root = Path(__file__).resolve().parents[1] / "paleo_workbench"
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "src.pages" in text or "from src.pages" in text:
            offenders.append(str(py.relative_to(root.parent)))
    assert not offenders
