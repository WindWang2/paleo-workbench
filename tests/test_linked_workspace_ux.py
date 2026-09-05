"""L10 — linked workstation UX: domain badge, conversion status, link gating.

The badge row is a READ-ONLY view over the coordination bus; the link
switch has real effect on both consumer paths (seismic locate, native link
cursor) and the producer path (well depth-cursor broadcast).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.selection_context import SelectionContext


@pytest.fixture()
def hub() -> CoordinateTransformHub:
    hub = CoordinateTransformHub()
    hub.register_well("W-1", x=0.0, y=0.0, total_depth_m=3000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-1",
            [(0.0, 0.0), (2000.0, 1500.0)],
            provenance="checkshot:qc",
        )
    )
    return hub


@pytest.fixture()
def controller(hub) -> ViewCoordinationController:
    return ViewCoordinationController(SelectionContext(), hub)


class _FakeSeismicPanel:
    def __init__(self):
        self.locates: list = []
        self._controller = None

    def attach_coordination(self, controller):
        self._controller = controller

    def locate_position(self, il, xl, twt=None):
        self.locates.append((il, xl, twt))


def _workspace(qtbot, controller=None, seismic=None):
    ws = LinkedInterpretationWorkspace()
    qtbot.addWidget(ws)
    ws._views_created = True
    ws._active_well_name = "W-1"
    ws.seismic_panel = seismic or _FakeSeismicPanel()

    class _WellPanel:
        def current_well_name(self):
            return "W-1"

    ws.well_panel = _WellPanel()
    if controller is not None:
        ws.attach_coordination(controller)
    return ws


def test_domain_status_reports_calibration_authority(qtbot, controller):
    ws = _workspace(qtbot, controller)
    controller.publish_well_selection("W-1", source=controller.SOURCE_MAP)

    text = ws.conversion_status_label.text()
    assert "checkshot:qc" in text
    assert ws.sync_status_label.text().startswith("同步：开启")


def test_domain_status_reports_missing_calibration(qtbot, controller):
    controller.coordinate_hub.clear_time_depth_calibration("W-1")
    ws = _workspace(qtbot, controller)
    controller.publish_well_selection("W-1", source=controller.SOURCE_MAP)

    text = ws.conversion_status_label.text()
    assert "不可用" in text
    assert "无时深校准" in text


def test_status_row_updates_without_publishing(qtbot, controller):
    ws = _workspace(qtbot, controller)
    before = controller.selection_context.snapshot()
    controller.publish_well_selection("W-1", source=controller.SOURCE_MAP)
    after = controller.selection_context.snapshot()
    # the status subscription is read-only: the only change is the publish's
    assert after.active_well_id == "W-1"
    assert after.source_widget_id == controller.SOURCE_MAP
    assert ws.conversion_status_label.text() != ""


def test_link_off_blocks_seismic_locate_consumer(qtbot):
    seismic = _FakeSeismicPanel()
    ws = _workspace(qtbot, seismic=seismic)
    ws.set_linked(False)

    ws.locate_seismic(10, 20, 100.0)
    assert seismic.locates == []

    ws.set_linked(True)
    ws.locate_seismic(10, 20, 100.0)
    assert seismic.locates == [(10, 20, 100.0)]


def test_link_off_blocks_native_link_cursor_consumer(qtbot):
    ws = _workspace(qtbot)
    driven: list = []
    ws.well_panel.set_link_cursor = lambda md: driven.append(md) or True
    ws.set_linked(False)

    assert ws.apply_link_cursor("W-1", 1500.0) is False
    assert driven == []

    ws.set_linked(True)
    assert ws.apply_link_cursor("W-1", 1500.0) is True
    assert driven == [1500.0]


def test_link_off_blocks_depth_cursor_broadcast(qtbot, controller):
    publishes: list = []
    original = controller.publish_depth_cursor

    def _spy(well, md, *, source):
        publishes.append((well, md))
        return original(well, md, source=source)

    controller.publish_depth_cursor = _spy
    try:
        ws = _workspace(qtbot, controller)
        ws.set_linked(False)
        ws._on_depth_cursor(1234.5)
        assert publishes == []

        ws.set_linked(True)
        ws._on_depth_cursor(1234.5)
        assert publishes == [("W-1", 1234.5)]
    finally:
        controller.publish_depth_cursor = original
