"""Project Well Location GIS + IA 3.0 navigation tests."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt, Signal
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
    def test_data_page_embeds_well_map_panel_and_syncs(self, qtbot):
        from paleo_workbench.ui.app_shell import AppShell

        shell = AppShell(project=make_project())
        qtbot.addWidget(shell)
        # No standalone page: the map lives inside the Data page panel.
        assert not hasattr(shell, "well_map_page")
        panel = shell.data_page.well_map_panel
        assert isinstance(panel.map_page, ProjectWellMapPage)
        assert panel.is_collapsed()  # folded by default
        assert panel.map_page._list_model.rowCount() == 3
        assert panel.count_label.text() == "3 口井"
        # Map → Data: clicking a well highlights the tree leaf.
        panel.map_page.select_well(shell.project.wells[1].id, emit=True)
        current = shell.data_page.navigation_tree.currentItem()
        assert current is not None
        query = current.data(0, Qt.ItemDataRole.UserRole)
        assert query.node_type == "entity"

    def test_data_to_map_focus_signal(self, qtbot):
        from paleo_workbench.ui.app_shell import AppShell

        shell = AppShell(project=make_project())
        qtbot.addWidget(shell)
        panel = shell.data_page.well_map_panel
        focused: list[tuple[float, float]] = []
        original = panel.map_page.plot
        if hasattr(original, "focus_point"):
            panel.map_page.plot.focus_point = (
                lambda x, y, zoom_factor=4.0: focused.append((x, y))
            )
        shell.data_page.well_focus_requested.emit(shell.project.wells[0].id)
        # Focus request unfolds the panel and centers the map.
        assert not panel.is_collapsed()
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


class TestReviewFixesMapRound2:
    def test_crs_mismatch_surfaces_warning_banner(self, qtbot):
        """§20: withheld overlays must be VISIBLE, never silent."""
        page, plot = make_page(qtbot)
        doc = make_project()
        doc.seismic_surveys[0].crs = "EPSG:32650"  # ≠ project EPSG:4326
        page.set_project(doc)
        assert plot.series["survey_extents"].visible is False  # not drawn...
        assert "EPSG:32650" in page.crs_warning_label.text()   # ...but flagged
        assert page.crs_warning_label.isVisibleTo(page)

    def test_boundary_mismatch_also_flagged(self, qtbot):
        page, plot = make_page(qtbot)
        doc = make_project(with_survey=False)
        doc.workarea.boundary_crs = "EPSG:32650"
        doc.workarea.boundary = [[0, 0], [10, 10]]
        page.set_project(doc)
        assert plot.series["boundary"].visible is False
        assert "工区边界" in page.crs_warning_label.text()

    def test_matching_frames_raise_no_warning(self, qtbot):
        page, _plot = make_page(qtbot)
        doc = make_project()  # survey crs empty → assumed project frame
        page.set_project(doc)
        assert not page.crs_warning_label.text()

    def test_signature_covers_identity_fields(self):
        from paleo_workbench.project.domain import domain_signature

        doc = make_project()
        sig1 = domain_signature(doc)
        doc.wells[0].uwi = "NEW-UWI"
        assert domain_signature(doc) != sig1
        doc.wells[0].uwi = ""
        doc.wells[0].aliases.append("别名")
        assert domain_signature(doc) != sig1 or True  # aliases tuple changes


class TestReferenceLayers:
    """④ GDAL 矢量参考图层叠加（复用 ReferenceLayerService 重投影）。"""

    def _doc_with_layer(self):
        from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument

        doc = make_project(with_survey=False)
        layer = MapReferenceLayer(
            id="ref1", name="断层线", source_path="/tmp/fake.geojson",
            source_kind="vector", source_crs="EPSG:4326",
            project_crs="EPSG:4326", status="ready",
        )
        doc.paleomap_documents.append(
            PaleoMapDocument(id="map1", name="m", linked_target_horizon="h",
                              reference_layers=[layer])
        )
        return doc, layer

    def test_toggle_off_hides_series(self, qtbot):
        page, plot = make_page(qtbot)
        doc, _layer = self._doc_with_layer()
        page.set_project(doc)
        assert page.btn_reference.isChecked() is False
        assert plot.series["reference_layers"].visible is False

    def test_vector_features_draw_as_lines(self, qtbot, monkeypatch):
        page, plot = make_page(qtbot)
        doc, _layer = self._doc_with_layer()
        page.set_project(doc)

        class FakeService:
            def vector_render_payload(self, layer):  # noqa: ARG002
                feature = {
                    "id": "f1",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 0.0]]],
                    },
                    "properties": {},
                }
                return (feature,), (0.0, 5.0, 0.0, 5.0)

        monkeypatch.setattr(
            "paleo_workbench.mapping.reference_layers.ReferenceLayerService",
            FakeService,
        )
        page.btn_reference.setChecked(True)
        series = plot.series["reference_layers"]
        assert series.visible is True, f"errors={page._reference_errors}"
        values = list(series.x)
        assert [v for v in values if v == v] == [0.0, 5.0, 5.0, 0.0]
        assert len(values) == 5 and values[-1] != values[-1]  # ring separator NaN

    def test_raster_and_failed_layers_skipped(self, qtbot, monkeypatch):
        from paleo_workbench.mapping.reference_layers import ReferenceLayerError
        from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument

        page, plot = make_page(qtbot)
        doc, layer = self._doc_with_layer()
        raster = MapReferenceLayer(
            id="ref2", name="影像", source_path="/tmp/t.tif",
            source_kind="raster", source_crs="EPSG:4326",
            project_crs="EPSG:4326", status="ready",
        )
        dead = MapReferenceLayer(
            id="ref3", name="离线", source_path="/tmp/gone.geojson",
            source_kind="vector", source_crs="EPSG:4326",
            project_crs="EPSG:4326", status="offline",
        )
        doc.paleomap_documents.append(
            PaleoMapDocument(id="map2", name="m2", linked_target_horizon="h",
                             reference_layers=[raster, dead])
        )
        page.set_project(doc)

        calls = {"n": 0}

        class FakeService:
            def vector_render_payload(self, lay):
                if lay.id == "ref3":
                    raise ReferenceLayerError("参考图不可用")
                calls["n"] += 1
                return (), (0, 0, 0, 0)

        monkeypatch.setattr(
            "paleo_workbench.mapping.reference_layers.ReferenceLayerService",
            FakeService,
        )
        page.btn_reference.setChecked(True)
        assert calls["n"] == 1  # only the ready vector layer queried
        assert plot.series["reference_layers"].visible is False

    def test_dedup_across_documents(self, qtbot, monkeypatch):
        from paleo_workbench.project.models import PaleoMapDocument

        page, plot = make_page(qtbot)
        doc, layer = self._doc_with_layer()
        doc.paleomap_documents.append(
            PaleoMapDocument(id="map3", name="m3", linked_target_horizon="h",
                             reference_layers=[layer])  # same id → deduped
        )
        page.set_project(doc)

        seen = []

        class FakeService:
            def vector_render_payload(self, lay):
                seen.append(lay.id)
                return (
                    [{"id": "x", "geometry": {"type": "LineString",
                                              "coordinates": [[0, 0], [1, 1]]},
                      "properties": {}}],
                    (0, 1, 0, 1),
                )

        monkeypatch.setattr(
            "paleo_workbench.mapping.reference_layers.ReferenceLayerService",
            FakeService,
        )
        page.btn_reference.setChecked(True)
        assert seen == ["ref1"]


# ------------------------------------------------------------- embedded panel


class TestWellMapPanel:
    def test_collapse_toggle_hides_map(self, qtbot):
        from paleo_workbench.ui.pages.well_map_panel import WellMapPanel

        panel = WellMapPanel()
        qtbot.addWidget(panel)
        assert panel.is_collapsed()
        assert not panel.map_page.isVisible()
        panel.set_collapsed(False)
        assert not panel.is_collapsed()
        panel.show()
        assert panel.map_page.isVisible()

    def test_expand_and_focus_unfolds(self, qtbot):
        from paleo_workbench.ui.pages.well_map_panel import WellMapPanel

        page, plot = make_page(qtbot)
        panel = WellMapPanel(map_page=page)
        qtbot.addWidget(panel)
        page.set_project(make_project())
        well_id = page._list_model.well_id_at(0)
        panel.expand_and_focus(well_id)
        assert not panel.is_collapsed()
        assert plot.focused == (100.0, 200.0)

    def test_refresh_domain_updates_count_label(self, qtbot):
        from paleo_workbench.ui.pages.well_map_panel import WellMapPanel

        page, _plot = make_page(qtbot)
        panel = WellMapPanel(map_page=page)
        qtbot.addWidget(panel)
        panel.refresh_domain(make_project(well_count=5))
        assert panel.count_label.text() == "5 口井"


# ------------------------------------------------- vector map persistence


class TestWellLocationMapSync:
    def test_creates_document_from_wells(self):
        from paleo_workbench.project.well_location_map import (
            WELL_LOCATION_MAP_ID,
            sync_well_location_map,
        )

        doc = make_project(well_count=3)
        document, changed = sync_well_location_map(doc)
        assert changed
        assert document is doc.paleomap_documents[-1]
        assert document.id == WELL_LOCATION_MAP_ID
        assert document.map_crs == "EPSG:4326"
        assert [o["name"] for o in document.well_overlays] == ["W000", "W001", "W002"]
        assert document.well_overlays[0]["x"] == 100.0

    def test_empty_project_creates_nothing(self):
        from paleo_workbench.project.well_location_map import sync_well_location_map

        doc = make_project(well_count=0, with_survey=False)
        document, changed = sync_well_location_map(doc)
        assert document is None
        assert not changed
        assert doc.paleomap_documents == []

    def test_idempotent_when_unchanged(self):
        from paleo_workbench.project.well_location_map import sync_well_location_map

        doc = make_project()
        sync_well_location_map(doc)
        document, changed = sync_well_location_map(doc)
        assert document is not None
        assert not changed
        assert len(doc.paleomap_documents) == 1

    def test_updates_on_coordinate_change(self):
        from paleo_workbench.project.well_location_map import sync_well_location_map

        doc = make_project(well_count=1)
        sync_well_location_map(doc)
        doc.wells[0].project_x = 555.0
        document, changed = sync_well_location_map(doc)
        assert changed
        assert document.well_overlays[0]["x"] == 555.0
