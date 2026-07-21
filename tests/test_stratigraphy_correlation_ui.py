"""UI tests for the stratigraphy correlation toolbar and tops injection."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from geoviz import CurveData, WellLogData

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage

DAT = (
    "#WellTops File From SMI\n"
    "A1 X 850.0 0 0 0 850.0 0\n"
    "A1 C1 1164.0 0 0 0 1164.0 0\n"
    "A2 C1 1200.0 0 0 0 1200.0 0\n"
    "GHOST C1 1300.0 0 0 0 1300.0 0\n"
)


def _log(name: str) -> WellLogData:
    return WellLogData(
        well_name=name,
        top_depth=800.0,
        bottom_depth=1600.0,
        curves=[
            CurveData(
                name="GR", unit="API",
                depth=[float(d) for d in range(800, 1601, 10)],
                values=[float(d % 100) for d in range(800, 1601, 10)],
                display_range=(0.0, 100.0),
            )
        ],
    )


def _project(tmp_path: Path) -> ProjectDocument:
    dat = tmp_path / "DC.dat"
    dat.write_text(DAT, encoding="utf-8")
    project = ProjectDocument.new("UI")
    project.resources.extend(
        [
            ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las"),
            ResourceItem(name="A2.las", path="/a2.las", type="well_log", format="las"),
            ResourceItem(name="DC.dat", path=str(dat), type="well_stratification", format="dat"),
        ]
    )
    return project


def _load_page(qtbot, tmp_path, monkeypatch) -> StratigraphyCorrelationPage:
    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setattr(
        mod,
        "load_correlation_wells",
        lambda project, resource_ids=None, max_wells=8: (
            [_log("A1"), _log("A2")], ["A1", "A2"], [],
        ),
    )
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(_project(tmp_path))
    page.update_state()
    page.load_section()
    return page


def test_toolbar_defaults(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert page.browse_btn.isChecked()
    assert page.cross_host.widget.pick_mode is False
    assert page.snap_combo.currentData() == "none"
    assert page.tops_visible_box.isChecked()
    assert page.spacing_slider.value() == 150


def test_pick_mode_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.pick_btn.setChecked(True)
    assert page.cross_host.widget.pick_mode is True
    page.browse_btn.setChecked(True)
    assert page.cross_host.widget.pick_mode is False


def test_manual_link_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert page.cross_host.inner._manual_link_active is False
    page.link_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is True
    page.browse_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is False


def test_snap_and_spacing_controls(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.snap_combo.setCurrentIndex(1)
    assert page.cross_host.widget.snap_type == "max"
    page.spacing_slider.setValue(80)
    assert page.cross_host.inner._container_layout.spacing() == 80


def test_tops_visibility_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.tops_visible_box.setChecked(False)
    assert page.cross_host.widget._overlay._tops_visible is False


def test_load_injects_tops_and_formation_data(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    model = page.cross_host.widget.tops_model
    assert [t.formation_name for t in model.tops_for_well("A1")] == ["X", "C1"]
    assert [t.formation_name for t in model.tops_for_well("A2")] == ["C1"]
    # GHOST well not loaded -> not injected, no crash
    assert model.tops_for_well("GHOST") == []
    formation_data = page.cross_host.inner._formation_data
    assert "A1" in formation_data
    assert formation_data["A1"][0].name == "X"
    assert formation_data["A1"][0].top == 850.0
    assert formation_data["A1"][0].bottom == 1164.0
    # Formation combo populated from tops
    items = [page.formation_combo.itemText(i) for i in range(page.formation_combo.count())]
    assert set(items) == {"X", "C1"}
    # Track checklist populated from canvas track labels
    assert page.track_list.count() > 0


def test_track_checklist_toggles_all_wells(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    item = page.track_list.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)
    label = item.text()
    for canvas in page.cross_host.inner._canvases:
        for track in canvas.tracks:
            if (track.label or "") == label:
                assert track._visible is False


def test_undo_redo_buttons(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    model = page.cross_host.widget.picks_model
    model.add_pick("C1", "A1", 1164.0)
    assert len(model.all_picks()) == 1
    page.undo_btn.click()
    assert model.all_picks() == []
    page.redo_btn.click()
    assert len(model.all_picks()) == 1


def test_clear_section_resets_models(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    page.cross_host.widget.picks_model.add_pick("C1", "A1", 1164.0)
    page.clear_section()
    assert page.cross_host.widget.tops_model.all_tops() == []
    assert page.cross_host.widget.picks_model.all_picks() == []
    assert page.track_list.count() == 0
    assert page.formation_combo.count() == 0


def test_browse_after_completed_link_does_not_reactivate(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    page.link_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is True
    # Engine auto-exits link mode after a completed link (simulate)
    page.cross_host.inner._manual_link_active = False
    page.browse_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is False
