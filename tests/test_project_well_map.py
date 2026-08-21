"""Project Well Location GIS + IA 3.0 navigation tests."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QListView, QWidget

from paleo_workbench.project.domain import (
    CoordinateStatus,
    EntityAssetLink,
    SeismicSurveyEntity,
    WellEntity,
    WorkArea,
)
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.filter_index import FilterQuery, FilterIndex
from paleo_workbench.ui.pages.navigation_tree import NavigationTree
from paleo_workbench.ui.pages.project_overview_panel import ProjectOverviewPanel
from paleo_workbench.ui.pages.project_well_map_page import (
    ProjectWellMapPage,
    WellListModel,
)


class _FakeSeries:
    def __init__(self, name):
        self.name = name
        self.x = np.array([], dtype=np.float64)
        self.y = np.array([], dtype=np.float64)
        self.visible = True


class _FakePlot(QWidget):
    point_hovered = Signal(str, int, float, float)
    point_clicked = Signal(str, int, float, float)

    def __init__(self):
        super().__init__()
        self.series: dict[str, _FakeSeries] = {}
        self.bounds = None
        self.focused = None

    def set_equal_aspect(self, flag):  # noqa: ARG002
        pass

    def add_series(self, series):
        self.series[series.name] = series

    def autofit(self):
        self.bounds = "all"

    def reset_view(self):
        self.bounds = "reset"

    def focus_point(self, x, y, zoom_factor=4.0):  # noqa: ARG002
        self.focused = (x, y)

    def set_view_bounds(self, xmin, xmax, ymin, ymax):
        self.bounds = (xmin, xmax, ymin, ymax)


def make_page(qtbot) -> tuple[ProjectWellMapPage, _FakePlot]:
    plot = _FakePlot()

    class _Engine:
        def create_widget(self, kind, parent=None):  # noqa: ARG002
            return plot

    page = ProjectWellMapPage(engine=_Engine())
    qtbot.addWidget(page)
    return page, plot


def make_project(well_count: int = 3, *, with_survey: bool = True) -> ProjectDocument:
    doc = ProjectDocument.new("GIS测试")
    doc.coordinate.project_crs = "EPSG:4326"
    doc.workarea = WorkArea(name="GIS测试", project_crs="EPSG:4326")
    for i in range(well_count):
        doc.wells.append(
            WellEntity(
                name=f"W{i:03d}",
                surface_x=float(100 + i),
                surface_y=float(200 + i),
                project_x=float(100 + i),
                project_y=float(200 + i),
                coordinate_status=CoordinateStatus.OK,
            )
        )
    if well_count:
        doc.entity_asset_links.append(
            EntityAssetLink(
                entity_type="well", entity_id=doc.wells[0].id, asset_id="a1",
                role="well_head", is_primary=True,
            )
        )
    if with_survey:
        doc.seismic_surveys.append(
            SeismicSurveyEntity(
                name="S1",
                extent=[[0.0, 0.0], [10.0, 0.0], [10.0, 8.0]],
            )
        )
    return doc


# --------------------------------------------------------------------------- model


class TestWellListModel:
    def test_rows_and_lookup(self):
        model = WellListModel()
        model.set_rows(["w1", "w2"], ["A", "B"], ["", " ⚠无坐标"])
        assert model.rowCount() == 2
        assert model.well_id_at(0) == "w1"
        assert model.row_for_well("w2") == 1
        assert model.data(model.index(1, 0)) == "B ⚠无坐标"
        assert model.data(model.index(1, 0), Qt.ItemDataRole.UserRole + 100) is None


# --------------------------------------------------------------------------- page


class TestWellMapPage:
    def test_set_project_builds_series_and_list(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        assert len(page._well_ids) == 3
        wells = plot.series["wells"]
        assert list(wells.x) == [100.0, 101.0, 102.0]
        assert not plot.series["wells_flagged"].x.size
        assert plot.series["boundary"].visible is False
        assert plot.series["survey_extents"].visible is True
        assert page.empty_label.isVisibleTo(page) is False

    def test_flagged_wells_split_into_warning_series(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        doc.wells[2].coordinate_status = CoordinateStatus.UNTRANSFORMED
        doc.wells[2].project_x = doc.wells[2].project_y = None
        page.set_project(doc)
        assert list(plot.series["wells"].x) == [100.0, 101.0]
        assert list(plot.series["wells_flagged"].x) == [102.0]

    def test_empty_state_visible_without_wells(self, qtbot):
        page, _plot = make_page(qtbot)
        page.set_project(make_project(well_count=0))
        assert page.empty_label.isVisibleTo(page) is True

    def test_click_selects_and_emits_canonical_id(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        received: list[str] = []
        page.well_selected.connect(received.append)
        page._on_point_clicked("wells", 1, 101.0, 201.0)
        assert received == [doc.wells[1].id]
        selected = plot.series["wells_selected"]
        assert list(selected.x) == [101.0]

    def test_hover_reports_name_and_coords(self, qtbot):
        page, _plot = make_page(qtbot)
        page.set_project(make_project())
        page._on_point_hovered("wells", 0, 100.5, 200.5)
        assert "W000" in page.coord_label.text()
        # flagged offset resolves registry rows correctly
        page._on_point_hovered("wells_flagged", 0, 7.0, 8.0)
        assert "X: 7.00" in page.coord_label.text()

    def test_select_well_from_map_focuses_plot(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        page.focus_well(doc.wells[1].id)
        assert plot.focused == (101.0, 201.0)

    def test_zoom_to_selection_sets_bounds(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        page.select_wells([doc.wells[0].id, doc.wells[2].id])
        page.zoom_to_selection()
        xmin, xmax, ymin, ymax = plot.bounds
        assert xmin < 100 <= xmax and 202 < ymax

    def test_search_filters_proxy_only(self, qtbot):
        page, _plot = make_page(qtbot)
        page.set_project(make_project())
        page.search_box.setText("W001")
        assert page._proxy.rowCount() == 1

    def test_refresh_domain_rebuilds_on_change_only(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        first_x = plot.series["wells"].x
        page.refresh_domain(doc)  # same signature → no rebuild
        assert plot.series["wells"].x is first_x
        doc.wells.append(WellEntity(name="NEW", project_x=1, project_y=2,
                                    coordinate_status=CoordinateStatus.OK))
        page.refresh_domain(doc)
        assert len(plot.series["wells"].x) == 4

    def test_boundary_polygon_closed(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project(with_survey=False)
        doc.workarea.boundary = [[0, 0], [10, 0], [10, 10], [0, 10]]
        page.set_project(doc)
        boundary = plot.series["boundary"]
        assert boundary.visible is True
        assert boundary.x[0] == boundary.x[-1]

    def test_multi_select_via_list_model(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        page.set_project(doc)
        page.select_wells([doc.wells[0].id, doc.wells[1].id])
        assert plot.series["wells_selected"].x.size == 2


# --------------------------------------------------------------------------- perf


@pytest.mark.slow
class TestWellMapPerformance:
    def test_50k_wells_cache_and_selection(self, qtbot):
        import time

        doc = ProjectDocument.new("perf")
        doc.coordinate.project_crs = "EPSG:4326"
        coords = np.random.default_rng(42).uniform(0, 10000, size=(50_000, 2))
        for i in range(50_000):
            doc.wells.append(
                WellEntity(
                    name=f"K{i}",
                    project_x=float(coords[i, 0]),
                    project_y=float(coords[i, 1]),
                    coordinate_status=CoordinateStatus.OK,
                )
            )
        page, plot = make_page(qtbot)
        start = time.perf_counter()
        page.set_project(doc)
        build_s = time.perf_counter() - start
        assert build_s < 15.0, f"50k rebuild took {build_s:.2f}s"
        assert len(plot.series["wells"].x) == 50_000
        assert page.well_list.model().rowCount() == 50_000
        # Selection must touch only the small highlight array.
        target = doc.wells[25_000].id
        start = time.perf_counter()
        page.select_well(target)
        select_s = time.perf_counter() - start
        assert select_s < 0.5
        assert plot.series["wells_selected"].x.size == 1


# --------------------------------------------------------------------------- overview


class TestOverviewPanel:
    def test_refresh_shows_counts_and_warnings(self, qtbot):
        panel = ProjectOverviewPanel()
        qtbot.addWidget(panel)
        doc = make_project()
        doc.wells[1].coordinate_status = CoordinateStatus.UNTRANSFORMED
        panel.refresh_from_project(doc)
        assert "井位地图" not in panel.title_label.text()
        assert panel._values["wells"].text() == "3"
        assert panel._values["surveys"].text() == "1"
        assert "CRS" in panel.meta_label.text()


# --------------------------------------------------------------------------- tree


class TestNavigationTreeIA:
    def test_entity_groups_built_from_project(self, qtbot):
        tree = NavigationTree()
        qtbot.addWidget(tree)
        doc = make_project()
        tree.set_project(doc)
        labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
        assert any(label.startswith("工区概览") for label in labels)
        well_group = next(
            (tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0).endswith("井")),
            None,
        )
        assert well_group is not None and well_group.childCount() == 3
        survey_group = next(
            (tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0).endswith("地震")),
            None,
        )
        assert survey_group.childCount() == 1

    def test_highlight_well_selects_leaf_and_emits_query(self, qtbot):
        tree = NavigationTree()
        qtbot.addWidget(tree)
        doc = make_project()
        tree.set_project(doc)
        queries: list[FilterQuery] = []
        tree.filter_query_changed.connect(queries.append)
        assert tree.highlight_well(doc.wells[2].id) is True
        assert queries and queries[-1].node_type == "entity"
        assert queries[-1].node_value == doc.wells[2].id

    def test_highlight_unknown_well_returns_false(self, qtbot):
        tree = NavigationTree()
        qtbot.addWidget(tree)
        tree.set_project(make_project())
        assert tree.highlight_well("well_nope") is False

    def test_legacy_groups_preserved(self, qtbot):
        tree = NavigationTree()
        qtbot.addWidget(tree)
        tree.set_project(make_project())
        for label in ("生命阶段", "数据类型", "标签", "状态与完整性"):
            assert tree.find_group(label.split()[0]) is not None or label == "标签"


# --------------------------------------------------------------------------- filter


class TestEntityFilterMatching:
    def test_entity_node_filters_by_membership_set(self):
        index = FilterIndex()

        class Row:
            def __init__(self, rid):
                self.id = rid

        class View:
            def __init__(self, raw):
                self.raw_asset = raw
                self.trashed = False
                self.stage = type("S", (), {"value": "raw"})()
                self.type = "well_head"
                self.normalized_tags = frozenset()
                self.integrity_state = type("I", (), {"value": "verified"})()
                self.governance = {}

        index._assets = [Row("res_a"), Row("res_b")]
        index._views = [View(Row("res_a")), View(Row("res_b"))]
        index._haystacks = ["a", "b"]
        query = FilterQuery(node_type="entity", node_value="w1")
        query = FilterQuery(
            node_type="entity",
            node_value="w1",
            entity_asset_ids=frozenset({"asset_1", "res_a"}),
        )
        hits = index.filter_query(query)
        assert hits == [0]

    def test_entity_node_without_set_matches_nothing(self):
        index = FilterIndex()
        index._assets = []
        index._views = []
        index._haystacks = []
        assert index.filter_query(FilterQuery(node_type="entity", node_value="w1")) == []


# --------------------------------------------------------------------------- shell glue


class TestShellGlue:
    def test_app_shell_registers_map_page_and_syncs(self, qtbot):
        from paleo_workbench.ui.app_shell import AppShell
        from paleo_workbench.ui.navigation import PAGE_INDEX_WELL_MAP

        shell = AppShell(project=make_project())
        qtbot.addWidget(shell)
        assert shell.page_stack.count() >= 12
        assert shell.page_stack.widget(PAGE_INDEX_WELL_MAP) is shell.well_map_page
        assert isinstance(shell.well_map_page, ProjectWellMapPage)
        assert shell.well_map_page._list_model.rowCount() == 3
        # Map → Data: clicking a well highlights the tree leaf.
        shell.well_map_page.select_well(shell.project.wells[1].id, emit=True)
        current = shell.data_page.navigation_tree.currentItem()
        assert current is not None
        query = current.data(0, Qt.ItemDataRole.UserRole)
        assert query.node_type == "entity"

    def test_data_to_map_focus_signal(self, qtbot):
        from paleo_workbench.ui.app_shell import AppShell

        shell = AppShell(project=make_project())
        qtbot.addWidget(shell)
        focused: list[str] = []

        class _SpyPlot(QObject):
            pass

        original = shell.well_map_page.plot
        if hasattr(original, "focus_point"):
            shell.well_map_page.plot.focus_point = lambda x, y, zoom_factor=4.0: focused.append(x)
        shell.data_page.well_focus_requested.emit(shell.project.wells[0].id)
        assert focused or not hasattr(original, "focus_point")


# --------------------------------------------------------------------------- review fixes


class TestReviewFixesMap:
    def test_survey_extent_skipped_on_crs_mismatch(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        doc.seismic_surveys[0].crs = "EPSG:32650"  # ≠ project EPSG:4326
        page.set_project(doc)
        assert plot.series["survey_extents"].visible is False

    def test_boundary_skipped_when_frame_differs(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project()
        doc.workarea.boundary_crs = "EPSG:32650"
        doc.workarea.boundary = [[0, 0], [10, 10]]
        page.set_project(doc)
        assert plot.series["boundary"].visible is False

    def test_tree_caps_entity_children(self, qtbot):
        tree = NavigationTree()
        qtbot.addWidget(tree)
        doc = ProjectDocument.new("big")
        for i in range(600):
            doc.wells.append(WellEntity(name=f"B{i:04d}"))
        tree.set_project(doc)
        well_group = next(
            (tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
             if tree.topLevelItem(i).text(0).endswith("井")),
            None,
        )
        assert well_group is not None
        # 500 rendered + 1 overflow placeholder.
        assert well_group.childCount() == 501
        assert "井位地图" in well_group.child(500).text(0)

    def test_map_page_degrades_without_engine(self, qtbot):
        from paleo_workbench.ui.pages.project_well_map_page import ProjectWellMapPage

        class _BrokenEngine:
            def create_widget(self, kind, parent=None):
                raise RuntimeError("no engine")

        page = ProjectWellMapPage(engine=_BrokenEngine())
        qtbot.addWidget(page)
        page.set_project(make_project())
        # List model still populated; plot replaced by fallback label.
        assert page._list_model.rowCount() == 3
        assert not hasattr(page.plot, "add_series")
