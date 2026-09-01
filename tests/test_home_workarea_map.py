"""Home work-area map (工区地图): snapshot producer + page embedding tests.

The producer is pure (ProjectDocument in → MapRenderSnapshot out), so layer
construction, CRS gating and extent logic run offscreen without any canvas.
Page tests cover the read-only embedding, the empty state and the ⚠ CRS
banner; the frame test exercises the default backend selection (QGIS bridge
or fallback — never a direct qgis_render_bridge import).
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.workarea_map_snapshot import (
    BOUNDARY_LAYER_ID,
    SURVEY_LABEL_LAYER_ID,
    SURVEY_LAYER_ID,
    WELLS_FLAGGED_LAYER_ID,
    WELLS_LAYER_ID,
    build_workarea_map_snapshot,
    snapshot_has_map_content,
    workarea_crs_warnings,
    workarea_view_extent,
)
from paleo_workbench.project.domain import (
    CoordinateStatus,
    SeismicSurveyEntity,
    WellEntity,
    WorkArea,
)
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.service import dashboard_state, home_workflow_steps


def make_project(
    *,
    with_wells: bool = True,
    with_survey: bool = True,
    with_boundary: bool = True,
) -> ProjectDocument:
    doc = ProjectDocument.new("MapProj")
    if with_boundary:
        doc.workarea = WorkArea(
            name="测试工区",
            boundary=[[0, 0], [10, 0], [10, 10], [0, 10]],
        )
    if with_wells:
        doc.wells.append(
            WellEntity(
                name="W1",
                project_x=2.0,
                project_y=3.0,
                coordinate_status=CoordinateStatus.OK,
            )
        )
        doc.wells.append(
            WellEntity(
                name="W2",
                project_x=5.0,
                project_y=5.0,
                coordinate_status=CoordinateStatus.UNTRANSFORMED,
            )
        )
        doc.wells.append(
            WellEntity(name="REF", project_x=99.0, project_y=99.0, spatial_scope="reference")
        )
        doc.wells.append(WellEntity(name="NOCOORD", coordinate_status=CoordinateStatus.MISSING))
    if with_survey:
        doc.seismic_surveys.append(
            SeismicSurveyEntity(name="SVY1", extent=[[1, 1], [8, 1], [8, 8], [1, 8]])
        )
    return doc


def layer_ids(snapshot):
    return [layer.id for layer in snapshot.layers]


# ---------------------------------------------------------------------------
# snapshot layer construction
# ---------------------------------------------------------------------------


def test_snapshot_builds_all_layers_in_order():
    snapshot = build_workarea_map_snapshot(make_project())
    assert layer_ids(snapshot) == [
        BOUNDARY_LAYER_ID,
        SURVEY_LAYER_ID,
        SURVEY_LABEL_LAYER_ID,
        WELLS_LAYER_ID,
        WELLS_FLAGGED_LAYER_ID,
    ]
    assert snapshot_has_map_content(snapshot) is True


def test_boundary_ring_is_closed_and_typed():
    snapshot = build_workarea_map_snapshot(make_project(with_wells=False, with_survey=False))
    (boundary_layer,) = snapshot.layers
    feature = boundary_layer.features[0]
    assert feature["geometry"]["type"] == "Polygon"
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]  # closed ring
    assert len(ring) >= 4


def test_well_layers_scope_and_status_split():
    snapshot = build_workarea_map_snapshot(make_project(with_survey=False, with_boundary=False))
    by_id = {layer.id: layer for layer in snapshot.layers}
    ok = by_id[WELLS_LAYER_ID]
    flagged = by_id[WELLS_FLAGGED_LAYER_ID]
    # REF (reference scope) and NOCOORD (no projected coords) never plot.
    assert [f["properties"]["name"] for f in ok.features] == ["W1"]
    assert [f["properties"]["name"] for f in flagged.features] == ["W2"]
    assert all(
        f["geometry"] == {"type": "Point", "coordinates": [2.0, 3.0]} for f in ok.features
    )
    # coordinate_status flags reflected in the style vocabulary
    assert ok.style["fill"] != flagged.style["fill"]
    assert ok.style["marker"] == "well"
    assert flagged.features[0]["properties"]["coordinate_status"] == CoordinateStatus.UNTRANSFORMED


def test_survey_footprints_close_and_label_at_centroid():
    snapshot = build_workarea_map_snapshot(make_project(with_wells=False, with_boundary=False))
    by_id = {layer.id: layer for layer in snapshot.layers}
    (feature,) = by_id[SURVEY_LAYER_ID].features
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    # Distinct dash style vs the solid boundary.
    assert by_id[SURVEY_LAYER_ID].style["line_pattern"] == "dash"
    (label,) = by_id[SURVEY_LABEL_LAYER_ID].features
    assert label["geometry"]["type"] == "Point"
    assert label["geometry"]["coordinates"] == [4.5, 4.5]
    assert label["properties"]["name"] == "SVY1"
    # Labels ride a transparent point layer (fallback paints point labels only).
    assert by_id[SURVEY_LABEL_LAYER_ID].style["labels"]["field"] == "name"
    assert by_id[SURVEY_LABEL_LAYER_ID].style["fill"] == "transparent"


def test_three_corner_legacy_survey_heals_to_rectangle():
    """Projects saved before extraction shipped 4 corners keep 3 — the
    snapshot must complete the parallelogram instead of drawing a triangle."""
    doc = make_project(with_wells=False, with_boundary=False)
    doc.seismic_surveys[0].extent = [[0, 0], [0, 8], [8, 8]]
    snapshot = build_workarea_map_snapshot(doc)
    by_id = {layer.id: layer for layer in snapshot.layers}
    (feature,) = by_id[SURVEY_LAYER_ID].features
    ring = feature["geometry"]["coordinates"][0]
    assert ring == [[0.0, 0.0], [0.0, 8.0], [8.0, 8.0], [8.0, 0.0], [0.0, 0.0]]


def test_well_layers_carry_name_labels():
    """Well points must render their 井编号 — both backends read style.labels."""
    snapshot = build_workarea_map_snapshot(make_project(with_survey=False, with_boundary=False))
    by_id = {layer.id: layer for layer in snapshot.layers}
    for layer_id in (WELLS_LAYER_ID, WELLS_FLAGGED_LAYER_ID):
        labels = by_id[layer_id].style["labels"]
        assert labels["field"] == "name"
        assert labels.get("visible", True)


def test_complete_survey_corners_helper():
    from paleo_workbench.project.domain import complete_survey_corners

    assert complete_survey_corners([[0, 0], [0, 8], [8, 8]]) == [
        [0.0, 0.0],
        [0.0, 8.0],
        [8.0, 8.0],
        [8.0, 0.0],
    ]
    # Non-3-corner inputs pass through untouched.
    four = [[1, 1], [8, 1], [8, 8], [1, 8]]
    assert complete_survey_corners(four) == [[1.0, 1.0], [8.0, 1.0], [8.0, 8.0], [1.0, 8.0]]
    assert complete_survey_corners([]) == []
    assert complete_survey_corners([[1, 2]]) == [[1.0, 2.0]]


def test_snapshot_uses_own_layer_id_prefix():
    snapshot = build_workarea_map_snapshot(make_project())
    assert all(layer.id.startswith("home_workarea:") for layer in snapshot.layers)


# ---------------------------------------------------------------------------
# CRS gating + warnings
# ---------------------------------------------------------------------------


def test_crs_mismatched_survey_withheld_and_warned():
    doc = make_project()
    doc.seismic_surveys[0].crs = "EPSG:32650"
    snapshot = build_workarea_map_snapshot(doc)
    assert SURVEY_LAYER_ID not in layer_ids(snapshot)
    assert SURVEY_LABEL_LAYER_ID not in layer_ids(snapshot)
    warnings = workarea_crs_warnings(doc)
    assert any("EPSG:32650" in warning for warning in warnings)


def test_crs_mismatched_boundary_withheld_and_warned():
    doc = make_project(with_wells=False, with_survey=False)
    doc.workarea.boundary_crs = "EPSG:32650"
    snapshot = build_workarea_map_snapshot(doc)
    assert snapshot.layers == ()
    warnings = workarea_crs_warnings(doc)
    assert any("工区边界" in warning for warning in warnings)


def test_survey_crs_equivalent_by_authority_code_drawn_without_warning():
    doc = make_project()
    doc.seismic_surveys[0].crs = "EPSG:4326"
    doc.coordinate.project_crs = "EPSG:4326"
    assert build_workarea_map_snapshot(doc).layers  # all layers present
    assert workarea_crs_warnings(doc) == []


def test_descriptive_project_crs_name_mismatches_bare_authority_code():
    """Established domain semantics (mirrors the Well Location map):
    ``crs_equivalent`` compares declared frames literally — the default
    descriptive project CRS name does not equal the bare authority code, so
    such a survey is withheld AND warned, never silently mixed."""
    doc = make_project()
    doc.seismic_surveys[0].crs = "EPSG:4326"
    snapshot = build_workarea_map_snapshot(doc)
    assert SURVEY_LAYER_ID not in layer_ids(snapshot)
    assert any("EPSG:4326" in warning for warning in workarea_crs_warnings(doc))


def test_empty_survey_crs_assumes_project_frame():
    doc = make_project()
    assert SURVEY_LAYER_ID in layer_ids(build_workarea_map_snapshot(doc))
    assert workarea_crs_warnings(doc) == []


# ---------------------------------------------------------------------------
# empty / degenerate projects
# ---------------------------------------------------------------------------


def test_empty_project_yields_empty_snapshot():
    doc = ProjectDocument.new("Empty")
    snapshot = build_workarea_map_snapshot(doc)
    assert snapshot.layers == ()
    assert snapshot_has_map_content(snapshot) is False
    assert workarea_view_extent(snapshot) is None
    assert workarea_crs_warnings(doc) == []


def test_none_project_yields_empty_snapshot():
    snapshot = build_workarea_map_snapshot(None)
    assert snapshot.layers == ()
    assert workarea_crs_warnings(None) == []


def test_view_extent_pads_content_bbox():
    snapshot = build_workarea_map_snapshot(make_project())
    extent = workarea_view_extent(snapshot)
    assert extent is not None
    xmin, ymin, xmax, ymax = extent
    # Content spans [0, 10] × [0, 10]; the fit window is strictly larger.
    assert xmin < 0 and ymin < 0 and xmax > 10 and ymax > 10


def test_single_point_extent_is_not_degenerate():
    doc = make_project(with_survey=False, with_boundary=False)
    doc.wells = [WellEntity(name="Solo", project_x=2.0, project_y=3.0)]
    extent = workarea_view_extent(build_workarea_map_snapshot(doc))
    assert extent is not None
    xmin, ymin, xmax, ymax = extent
    assert xmax > xmin and ymax > ymin


# ---------------------------------------------------------------------------
# page embedding
# ---------------------------------------------------------------------------


def test_home_page_embeds_readonly_map_canvas(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage
    from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas

    page = HomePage()
    qtbot.addWidget(page)
    assert isinstance(page.map_canvas, UnifiedMapCanvas)
    # Read-only: no tool controller — pan/zoom only.
    assert page.map_canvas._tool_controller is None


def test_home_page_empty_project_shows_empty_state(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = ProjectDocument.new("Empty")
    page.update_state(dashboard_state(doc), home_workflow_steps(doc), project=doc)
    assert page.map_stack.currentIndex() == 1  # inviting empty state
    assert page.crs_warning_label.isHidden()


def test_home_page_with_data_shows_map(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = make_project()
    page.update_state(dashboard_state(doc), home_workflow_steps(doc), project=doc)
    assert page.map_stack.currentIndex() == 0
    snapshot_layers = list(page.map_canvas.backend._snapshot.layers)
    assert WELLS_LAYER_ID in [layer.id for layer in snapshot_layers]


def test_home_page_crs_mismatch_shows_banner(qtbot):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = make_project()
    doc.seismic_surveys[0].crs = "EPSG:32650"
    page.update_state(dashboard_state(doc), home_workflow_steps(doc), project=doc)
    assert "EPSG:32650" in page.crs_warning_label.text()
    assert page.crs_warning_label.isVisibleTo(page)


def test_home_page_side_column_collapses_when_cards_hide(qtbot):
    """Map-first: with resources imported and no onboarding report both side
    cards hide and the column yields its width to the map."""
    from paleo_workbench.project.models import ResourceItem
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = ProjectDocument.new("Imported")
    doc.resources.append(ResourceItem(name="r1", path="/tmp/a.las", type="well_log", format="las"))
    page.update_state(dashboard_state(doc), home_workflow_steps(doc), project=doc)
    assert page.start_guide_card.isHidden()
    assert page.onboarding_report_card.isHidden()
    assert page._side_column.isHidden()


def test_home_page_map_refresh_signature_gated(qtbot, monkeypatch):
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = make_project()
    state = dashboard_state(doc)
    steps = home_workflow_steps(doc)
    page.update_state(state, steps, project=doc)

    calls: list = []
    original = page.map_canvas.set_layer_snapshot
    monkeypatch.setattr(
        page.map_canvas,
        "set_layer_snapshot",
        lambda snapshot: (calls.append(snapshot), original(snapshot)),
    )
    # Same domain content → no rebuild (pan/zoom state survives).
    page.update_state(state, steps, project=doc)
    assert calls == []
    # A domain edit invalidates and rebuilds exactly once.
    doc.wells[0].project_x = 4.0
    page.update_state(state, steps, project=doc)
    assert len(calls) == 1


def test_home_page_empty_project_renders_frame_via_default_backend(qtbot):
    """Graceful degradation: default backend selection (QGIS or fallback)
    must deliver a frame for the empty composition without a tool controller."""
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    doc = ProjectDocument.new("Empty")
    page.update_state(dashboard_state(doc), home_workflow_steps(doc), project=doc)
    page.resize(900, 600)
    page.show()
    qtbot.waitUntil(lambda: page.map_canvas.last_frame is not None, timeout=15_000)


@pytest.mark.parametrize(
    "boundary,with_wells,with_survey,expect_content",
    [
        (True, True, True, True),
        (False, True, False, True),
        (True, False, False, True),  # boundary alone still draws a map
        (False, False, False, False),
    ],
)
def test_content_presence_matrix(boundary, with_wells, with_survey, expect_content):
    snapshot = build_workarea_map_snapshot(
        make_project(with_boundary=boundary, with_wells=with_wells, with_survey=with_survey)
    )
    assert snapshot_has_map_content(snapshot) is expect_content
