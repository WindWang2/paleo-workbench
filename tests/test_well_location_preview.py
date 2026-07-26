import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from geoviz import GeoVizEngine, PreparedPreview, PreviewKind
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.viz.hosts.well_location_preview import WellLocationPreview
from paleo_workbench.viz.models import VizPayload


def _well_preview() -> PreparedPreview:
    return PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="Well locations",
        payload=XYPreviewPayload(
            names=("A1", "A2"),
            x=np.asarray([10.0, 30.0]),
            y=np.asarray([20.0, 40.0]),
            resource_id="well-head-1",
            record_ids=(8, 13),
        ),
    )


def _move_mouse(widget, point: QPoint) -> None:
    event = QMouseEvent(
        QEvent.MouseMove,
        QPointF(point),
        QPointF(widget.mapToGlobal(point)),
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QCoreApplication.sendEvent(widget, event)


def _drag_mouse(widget, start: QPoint, end: QPoint) -> None:
    for event in (
        QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(start),
            QPointF(widget.mapToGlobal(start)),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(end),
            QPointF(widget.mapToGlobal(end)),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(end),
            QPointF(widget.mapToGlobal(end)),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    ):
        QCoreApplication.sendEvent(widget, event)


def test_user_can_hover_select_focus_and_reset_a_well(qtbot):
    preview = WellLocationPreview(GeoVizEngine.default())
    qtbot.addWidget(preview)
    preview.resize(800, 600)
    preview.render(_well_preview())
    preview.show()
    qtbot.wait(10)

    full_view = (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    )
    px, py = preview.plot.data_to_pixel(10.0, 20.0)
    point = QPoint(round(px), round(py))

    _move_mouse(preview.plot, point)

    assert preview.active_well is None
    assert "A1" in preview.plot.toolTip()
    assert "X 10.000" in preview.plot.toolTip()
    assert "Y 20.000" in preview.plot.toolTip()

    _move_mouse(preview.plot, QPoint(70, 30))

    assert preview.plot.toolTip() == ""

    qtbot.mouseClick(preview.plot, Qt.LeftButton, pos=point)

    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert preview.active_well.point_index == 0
    assert preview.active_well.resource_id == "well-head-1"
    assert preview.active_well.record_id == 8
    assert preview.plot.selected_point == ("Well locations", 0)
    assert preview.plot.selected_label == "A1"
    assert preview.plot.view_xmax - preview.plot.view_xmin == pytest.approx(
        (full_view[1] - full_view[0]) / 4.0
    )
    assert preview.plot.view_ymax - preview.plot.view_ymin == pytest.approx(
        (full_view[3] - full_view[2]) / 4.0
    )

    preview.plot.setFocus()
    qtbot.keyClick(preview.plot, Qt.Key_Escape)

    assert preview.active_well is None
    assert preview.plot.selected_point is None
    assert (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    ) == pytest.approx(full_view)


def test_blank_click_preserves_active_well_and_double_click_resets(qtbot):
    preview = WellLocationPreview(GeoVizEngine.default())
    qtbot.addWidget(preview)
    preview.resize(800, 600)
    preview.render(_well_preview())
    preview.show()
    qtbot.wait(10)
    full_view = (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    )
    px, py = preview.plot.data_to_pixel(10.0, 20.0)
    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )
    focused_view = (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    )

    _drag_mouse(preview.plot, QPoint(300, 250), QPoint(340, 275))

    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert preview.plot.selected_point == ("Well locations", 0)
    assert (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    ) != pytest.approx(focused_view)
    left, right, top, bottom = preview.plot.get_plot_rect(
        preview.plot.width(),
        preview.plot.height(),
    )
    assert (preview.plot.view_xmax - preview.plot.view_xmin) / (
        right - left
    ) == pytest.approx(
        (preview.plot.view_ymax - preview.plot.view_ymin) / (bottom - top)
    )
    panned_view = (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    )

    blank = QPoint(70, 30)
    qtbot.mouseClick(preview.plot, Qt.LeftButton, pos=blank)

    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    ) == pytest.approx(panned_view)

    qtbot.mouseDClick(preview.plot, Qt.LeftButton, pos=blank)

    assert preview.active_well is None
    assert preview.plot.selected_point is None
    assert (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    ) == pytest.approx(full_view)


def test_point_double_click_does_not_reset_after_first_click_focuses(qtbot):
    preview = WellLocationPreview(GeoVizEngine.default())
    qtbot.addWidget(preview)
    preview.resize(800, 600)
    preview.render(_well_preview())
    preview.show()
    qtbot.wait(10)
    px, py = preview.plot.data_to_pixel(10.0, 20.0)
    point = QPoint(round(px), round(py))

    qtbot.mouseClick(preview.plot, Qt.LeftButton, pos=point)
    focused_view = (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    )
    qtbot.mouseDClick(preview.plot, Qt.LeftButton, pos=point)

    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert preview.plot.selected_point == ("Well locations", 0)
    assert (
        preview.plot.view_xmin,
        preview.plot.view_xmax,
        preview.plot.view_ymin,
        preview.plot.view_ymax,
    ) == pytest.approx(focused_view)


def test_shared_host_reuses_and_releases_well_location_preview(qtbot):
    from paleo_workbench.viz.hosts.geoviz_preview_host import GeoVizPreviewHost

    host = GeoVizPreviewHost(GeoVizEngine.default())
    qtbot.addWidget(host)

    first = host.render(_well_preview())
    second = host.render(_well_preview())

    assert isinstance(first, WellLocationPreview)
    assert second is first
    assert host.stack.currentWidget() is first

    host.release_all()

    assert host.stack.count() == 0
    assert first.plot.series_list == []


def test_both_data_page_entries_delegate_to_shared_well_preview(qtbot):
    from paleo_workbench.ui.pages.lazy_visualization_tabs import (
        LazyVisualizationTabs,
    )
    from paleo_workbench.viz.hosts.engine_preview_host import EnginePreviewHost

    engine = GeoVizEngine.default()
    reader_entry = LazyVisualizationTabs(engine)
    visualization_entry = EnginePreviewHost(engine)
    qtbot.addWidget(reader_entry)
    qtbot.addWidget(visualization_entry.widget)

    reader_entry.show_preview(_well_preview())
    applied = visualization_entry.apply(
        VizPayload(
            kind="engine_preview",
            label="Well locations",
            prepared=_well_preview(),
        )
    )

    assert applied is True
    assert isinstance(reader_entry.host.stack.currentWidget(), WellLocationPreview)
    assert isinstance(
        visualization_entry.widget.stack.currentWidget(),
        WellLocationPreview,
    )
