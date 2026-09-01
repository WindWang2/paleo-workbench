"""T-STRAT-01: multi-well stratigraphy correlation page (CrossWell)."""

from __future__ import annotations

from pathlib import Path

from geoviz import CurveData, FormationTop, WellLogData
from PySide6.QtCore import Qt

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage
from paleo_workbench.workflow.stratigraphy_correlation import (
    list_well_log_resources,
    load_correlation_wells,
)


def _wait_section(qtbot, page, *, wells: int | None = None) -> None:
    def _ready() -> bool:
        if page._load_job.is_running:
            return False
        if wells is not None:
            return len(page._loaded_logs) == wells
        return True

    qtbot.waitUntil(_ready, timeout=10_000)


def test_app_shell_well_hub_hosts_stratigraphy_correlation(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.stratigraphy_page
    assert isinstance(page, StratigraphyCorrelationPage)
    assert window.app_shell.hub_well.page("stratigraphy") is page


def test_list_well_log_resources_sorted():
    project = ProjectDocument.new("W")
    project.resources.extend(
        [
            ResourceItem(name="B.las", path="/b.las", type="well_log", format="las"),
            ResourceItem(name="A.las", path="/a.las", type="well_log", format="las"),
            ResourceItem(name="s.sgy", path="/s.sgy", type="seismic", format="sgy"),
        ]
    )
    wells = list_well_log_resources(project)
    assert [w.name for w in wells] == ["A.las", "B.las"]


def test_load_correlation_wells_merges_prediction(qtbot, monkeypatch):
    project = ProjectDocument.new("Corr")
    project.stratigraphy.target_horizon = "C6"
    r1 = ResourceItem(name="W1.las", path="/w1.las", type="well_log", format="las")
    r2 = ResourceItem(name="W2.las", path="/w2.las", type="well_log", format="las")
    project.resources.extend([r1, r2])

    known = WellLogData(
        well_name="from-las",
        top_depth=0.0,
        bottom_depth=100.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0, 50, 100], values=[10, 20, 15])],
    )

    from paleo_workbench.prediction.adapters import MockPredictionAdapter
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    MockPredictionAdapter().run(project, [], seed=1)

    def _fake_resolve(self, ref, project_arg):
        return VizPayload(kind="well_log", label=ref.label, well_log=known.model_copy())

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)
    logs, names, loaded_ids, warnings = load_correlation_wells(
        project, resource_ids=[r1.id, r2.id]
    )
    assert len(logs) == 2
    assert len(names) == 2
    assert loaded_ids == [r1.id, r2.id]
    assert warnings == []
    assert len(logs[0].lithology) >= 1


def test_load_correlation_wells_skipped_middle_well_reports_per_well_ids(
    qtbot, monkeypatch
):
    """#404: a mid-list load failure must not shift later wells onto earlier ids."""
    project = ProjectDocument.new("Corr")
    r1 = ResourceItem(name="A.las", path="/a.las", type="well_log", format="las")
    r2 = ResourceItem(name="B.las", path="/b.las", type="well_log", format="las")
    r3 = ResourceItem(name="C.las", path="/c.las", type="well_log", format="las")
    project.resources.extend([r1, r2, r3])

    known = WellLogData(
        well_name="from-las",
        top_depth=0.0,
        bottom_depth=100.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0, 50, 100], values=[10, 20, 15])],
    )
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    def _fake_resolve(self, ref, project_arg):
        if ref.label.endswith("B.las"):
            return VizPayload(kind="well_log", label=ref.label, well_log=None, message="无法加载 LAS")
        return VizPayload(kind="well_log", label=ref.label, well_log=known.model_copy())

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)
    logs, names, loaded_ids, warnings = load_correlation_wells(
        project, resource_ids=[r1.id, r2.id, r3.id]
    )
    assert len(logs) == 2
    assert names == ["from-las", "from-las"]
    # Middle failure: C's id must survive, B's id must be absent.
    assert loaded_ids == [r1.id, r3.id]
    assert r2.id not in loaded_ids
    assert any("B.las" in w for w in warnings)


def test_load_section_keeps_id_alignment_when_middle_well_fails(qtbot, monkeypatch):
    """#404 page flow: tops saved after a mid-list failure attach to the right wells."""
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    project = ProjectDocument.new("Page")
    project.stratigraphy.target_horizon = "H1"
    r1 = ResourceItem(name="A.las", path="/a.las", type="well_log", format="las")
    r2 = ResourceItem(name="B.las", path="/b.las", type="well_log", format="las")
    r3 = ResourceItem(name="C.las", path="/c.las", type="well_log", format="las")
    project.resources.extend([r1, r2, r3])

    known = WellLogData(
        well_name="well",
        top_depth=0.0,
        bottom_depth=50.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0, 25, 50], values=[5, 10, 8])],
    )
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    def _fake_resolve(self, ref, project_arg):
        if ref.label.endswith("B.las"):
            return VizPayload(kind="well_log", label=ref.label, well_log=None, message="无法加载 LAS")
        # Distinct well names so name→resource-id pairing is observable.
        stem = Path(ref.label).stem
        return VizPayload(
            kind="well_log",
            label=ref.label,
            well_log=known.model_copy(update={"well_name": f"WELL-{stem}"}),
        )

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)

    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_backend("legacy")
    page.set_project(project)
    page.update_state(project)
    for i in range(page.well_list.count()):
        page.well_list.item(i).setCheckState(Qt.CheckState.Checked)
    page.load_btn.click()
    _wait_section(qtbot, page, wells=2)
    assert page._loaded_resource_ids == [r1.id, r3.id]
    assert len(page._loaded_names) == 2

    # Simulate user picks on the loaded wells (A and C).
    canvas = page.cross_host.widget
    for well in page._loaded_names:
        canvas.tops_model.add_top(FormationTop(well, "TopA", 12.5))

    tops = page._tops_from_canvas()
    name_to_id = dict(zip(page._loaded_names, page._loaded_resource_ids))
    assert {t.well_id for t in tops} == set(name_to_id.values())
    assert r2.id not in {t.well_id for t in tops}
    # Each rendered top's well_id matches the resource id of its own well name.
    for t in tops:
        assert t.well_id == name_to_id[t.well_name]


def test_page_lists_wells_and_loads_section(qtbot, monkeypatch):
    # Legacy CrossWell host is the target; the engine backend (default when the
    # welllog binding is present) would not mount legacy canvases.
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    project = ProjectDocument.new("Page")
    project.stratigraphy.target_horizon = "H1"
    project.resources.append(
        ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las")
    )
    project.resources.append(
        ResourceItem(name="A2.las", path="/a2.las", type="well_log", format="las")
    )

    known = WellLogData(
        well_name="well",
        top_depth=0.0,
        bottom_depth=50.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0, 25, 50], values=[5, 10, 8])],
    )
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    monkeypatch.setattr(
        VizAdapter,
        "resolve",
        lambda self, ref, project_arg: VizPayload(
            kind="well_log", label="well", well_log=known.model_copy()
        ),
    )

    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state(project)

    assert page.well_list.count() == 2
    assert "H1" in page.horizon_value.text()
    page.load_btn.click()
    _wait_section(qtbot, page, wells=2)
    assert page.cross_host.inner.canvas_count >= 2
    assert "2 口井" in page.loaded_value.text()


def test_stratigraphy_correlation_page_has_scroll_area(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert hasattr(page, "scroll_area")
    assert isinstance(page.scroll_area, QScrollArea)
    assert page.scroll_area.widget() is page.cross_host.widget
    assert page.scroll_area.widgetResizable() is True
    assert (
        page.scroll_area.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )


def test_dual_path_backend_switch_keeps_legacy_and_builds_engine_plan(
    qtbot, monkeypatch
):
    """#170: Legacy remains; engine plan built with stable multi-well ids."""
    project = ProjectDocument.new("Dual")
    project.stratigraphy.target_horizon = "H1"
    project.resources.append(
        ResourceItem(name="W1.las", path="/w1.las", type="well_log", format="las")
    )
    project.resources.append(
        ResourceItem(name="W2.las", path="/w2.las", type="well_log", format="las")
    )
    known = WellLogData(
        well_name="well",
        top_depth=1000.0,
        bottom_depth=1002.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1001.0, 1002.0],
                values=[5, 10, 8],
            )
        ],
    )
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    monkeypatch.setattr(
        VizAdapter,
        "resolve",
        lambda self, ref, project_arg: VizPayload(
            kind="well_log", label="well", well_log=known.model_copy()
        ),
    )
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_backend("legacy")
    page.set_project(project)
    page.update_state(project)
    page.load_btn.click()
    _wait_section(qtbot, page, wells=2)
    assert page.backend() == "legacy"
    assert page.cross_host.inner.canvas_count >= 2
    # Engine plan always built for parity even on Legacy path.
    plan = page.engine_plan()
    assert plan is not None
    assert len(plan.wells) == 2
    assert plan.wells[0].document_id != plan.wells[1].document_id
    # Switch to engine without deleting Legacy host.
    page.set_backend("engine")
    assert page.backend() == "engine"
    assert page.view_stack.currentWidget() is page.engine_host
    # Legacy widgets still exist (not deleted).
    assert page.cross_host.widget is not None
    page.clear_section()
    assert page.engine_plan() is None
    assert page.loaded_value.text().startswith("已加载: 0")
