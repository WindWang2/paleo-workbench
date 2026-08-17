import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QListView, QListWidget, QToolButton

from geoviz import (
    GeoVizEngine,
    PreparedPreview,
    PreviewKind,
    PreviewRowIssue,
    XYPreviewDiagnostics,
)
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.viz.hosts.well_location_preview import (
    WellLocationId,
    WellLocationPreview,
    WellLocationPreviewState,
    WellLocationPreviewStateStore,
)
from paleo_workbench.viz.models import VizPayload


def _well_preview(
    *,
    source_version: str = "version-1",
    resource_id: str = "well-head-1",
) -> PreparedPreview:
    return PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="Well locations",
        payload=XYPreviewPayload(
            names=("A1", "A2"),
            x=np.asarray([10.0, 30.0]),
            y=np.asarray([20.0, 40.0]),
            resource_id=resource_id,
            record_ids=(8, 13),
            source_rows=(12, 18),
            source_version=source_version,
        ),
    )


def _named_well_preview(
    names: tuple[str, ...],
    *,
    record_ids: tuple[int, ...],
) -> PreparedPreview:
    count = len(names)
    return PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="Well locations",
        payload=XYPreviewPayload(
            names=names,
            x=np.arange(count, dtype=float) * 10.0,
            y=np.arange(count, dtype=float) * 20.0,
            resource_id="well-head-1",
            record_ids=record_ids,
            source_rows=tuple(range(1, count + 1)),
            source_version="version-1",
        ),
    )


def _show_well_preview(
    qtbot,
    prepared: PreparedPreview,
    *,
    size: tuple[int, int] = (900, 600),
    state_store: WellLocationPreviewStateStore | None = None,
) -> WellLocationPreview:
    preview = WellLocationPreview(
        GeoVizEngine.default(),
        state_store=state_store,
    )
    qtbot.addWidget(preview)
    preview.resize(*size)
    preview.render(prepared)
    preview.show()
    qtbot.wait(10)
    return preview


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


def _list_texts(preview: WellLocationPreview) -> list[str]:
    model = preview.well_list.model()
    return [
        str(model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole))
        for row in range(model.rowCount())
    ]


def test_sync_list_selection_does_not_reenter_activation(qtbot):
    """#664: block selectionModel, not the view, when syncing the list."""
    preview = _show_well_preview(qtbot, _well_preview())
    calls = {"n": 0}
    original = preview._activate_list_well

    def _wrapped(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    preview._activate_list_well = _wrapped
    preview._sync_list_selection(1)
    assert calls["n"] == 0
    assert preview.well_list.currentIndex().isValid()


def test_well_list_is_persistent_naturally_sorted_and_stable(qtbot):
    preview = _show_well_preview(
        qtbot,
        _named_well_preview(
            ("A10", "A2", "A1", "A2"),
            record_ids=(10, 42, 3, 7),
        ),
    )

    assert preview.well_list.model().rowCount() == 4
    assert _list_texts(preview) == [
        "A1",
        "A2 · X 10, Y 20",
        "A2 · X 30, Y 60",
        "A10",
    ]
    assert preview.well_list.isVisible()
    assert preview.well_list.mapTo(preview, QPoint()).x() > preview.plot.x()
    assert len(preview.plot.series_list[0].x) == 4


def test_well_list_uses_a_virtualized_model_view(qtbot):
    preview = _show_well_preview(qtbot, _well_preview())

    assert isinstance(preview.well_list, QListView)
    assert not isinstance(preview.well_list, QListWidget)
    assert preview.well_list.model().rowCount() == 2


def test_well_list_model_keeps_all_50_000_supported_wells(qtbot):
    count = 50_000
    prepared = _named_well_preview(
        tuple(f"W{index}" for index in range(count)),
        record_ids=tuple(range(count)),
    )
    preview = WellLocationPreview(GeoVizEngine.default())
    qtbot.addWidget(preview)

    preview.render(prepared)

    assert preview.well_list.model().rowCount() == count
    assert len(preview.plot.series_list[0].x) == count


def test_50_000_well_list_search_and_plot_keep_every_identity_reachable(qtbot):
    count = 50_000
    prepared = _named_well_preview(
        tuple(f"W{index}" for index in range(count)),
        record_ids=tuple(range(count)),
    )
    preview = _show_well_preview(qtbot, prepared)

    for point_index in (0, count // 2, count - 1):
        preview.well_search.setText(f"W{point_index}")
        assert preview.well_list.model().rowCount() == 1
        row = preview.well_list.model().index(0, 0)
        qtbot.mouseClick(
            preview.well_list.viewport(),
            Qt.LeftButton,
            pos=preview.well_list.visualRect(row).center(),
        )
        assert preview.active_well is not None
        assert preview.active_well.identity.record_id == point_index

    preview.well_search.clear()
    point_index = count - 1
    preview.plot.focus_point(
        float(prepared.payload.x[point_index]),
        float(prepared.payload.y[point_index]),
        zoom_factor=1_000.0,
    )
    px, py = preview.plot.data_to_pixel(
        float(prepared.payload.x[point_index]),
        float(prepared.payload.y[point_index]),
    )
    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )

    assert preview.active_well is not None
    assert preview.active_well.identity.record_id == point_index


def test_source_coordinate_and_row_diagnostics_are_expandable(qtbot):
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="Well locations",
        payload=XYPreviewPayload(
            names=("A1",),
            x=np.asarray([10.0]),
            y=np.asarray([20.0]),
            resource_id="well-head-1",
            record_ids=(0,),
            source_rows=(3,),
            source_version="v1",
            source_crs="EPSG:32648",
            coordinate_units="m",
            diagnostics=XYPreviewDiagnostics(
                total_records=2,
                valid_records=1,
                issues=(PreviewRowIssue(4, "X 坐标不是有限数值"),),
            ),
        ),
    )
    preview = _show_well_preview(qtbot, prepared)

    assert "EPSG:32648" in preview.source_status.text()
    assert "m" in preview.source_status.text()
    assert "有效 1/2" in preview.source_status.text()
    toggle = preview.findChild(QToolButton, "WellLocationDiagnosticToggle")
    assert toggle is not None
    assert toggle.isVisible()
    assert "查看 1 条" in toggle.text()
    assert "源行 4" not in preview.source_status.text()
    assert not preview.diagnostic_details.isVisible()

    qtbot.mouseClick(toggle, Qt.LeftButton)

    assert preview.diagnostic_details.isVisible()
    assert "源行 4" in preview.diagnostic_details.text()
    assert "X 坐标不是有限数值" in preview.diagnostic_details.text()


def test_data_quality_marks_extremely_low_validity_and_duplicate_groups(qtbot):
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="Well locations",
        payload=XYPreviewPayload(
            names=("A1", "A1", "B1"),
            x=np.asarray([10.0, 20.0, 30.0]),
            y=np.asarray([20.0, 40.0, 60.0]),
            resource_id="well-head-1",
            record_ids=(0, 1, 2),
            source_rows=(3, 4, 5),
            source_version="v1",
            diagnostics=XYPreviewDiagnostics(
                total_records=100,
                valid_records=3,
            ),
        ),
    )
    preview = _show_well_preview(qtbot, prepared)

    assert "严重数据质量问题" in preview.source_status.text()
    assert "3/100" in preview.source_status.text()
    assert "1 个重名井名组" in preview.source_status.text()
    assert "X/Y" in preview.source_status.text()


def test_versioned_state_survives_widget_reconstruction_and_invalidates(
    qtbot,
):
    store = WellLocationPreviewStateStore()
    first = WellLocationPreview(
        GeoVizEngine.default(),
        state_store=store,
    )
    qtbot.addWidget(first)
    first.resize(900, 600)
    first.render(_well_preview())
    first.show()
    qtbot.wait(10)
    px, py = first.plot.data_to_pixel(10.0, 20.0)
    qtbot.mouseClick(
        first.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )
    first.well_search.setText("A1")
    first.plot.pan(35.0, 20.0)
    expected_view = first.plot.view_bounds()
    first.release()

    restored = WellLocationPreview(
        GeoVizEngine.default(),
        state_store=store,
    )
    qtbot.addWidget(restored)
    restored.resize(900, 600)
    restored.render(_well_preview())

    assert restored.active_well is not None
    assert restored.active_well.identity == WellLocationId(
        resource_id="well-head-1",
        source_version="version-1",
        record_id=8,
    )
    assert restored.active_well.source_row == 12
    assert restored.well_search.text() == "A1"
    assert restored.plot.view_bounds() == pytest.approx(expected_view)

    restored.release()
    changed = WellLocationPreview(
        GeoVizEngine.default(),
        state_store=store,
    )
    qtbot.addWidget(changed)
    changed.render(_well_preview(source_version="version-2"))

    assert changed.active_well is None
    assert changed.well_search.text() == ""


def test_stale_version_cannot_evict_newer_version_state():
    store = WellLocationPreviewStateStore()
    current = WellLocationPreviewState(search_text="current")
    stale = WellLocationPreviewState(search_text="stale")

    store.activate_version("well-head-1", "version-2")
    store.save("well-head-1", "version-2", current)
    store.save("well-head-1", "version-1", stale)

    assert store.load("well-head-1", "version-2") == current
    assert store.load("well-head-1", "version-1") is None
    assert store.load("well-head-1", "version-3") is None


def test_preview_state_is_isolated_per_asset_and_clears_with_session(qtbot):
    store = WellLocationPreviewStateStore()
    first = _show_well_preview(
        qtbot,
        _well_preview(resource_id="well-head-1"),
        state_store=store,
    )
    px, py = first.plot.data_to_pixel(10.0, 20.0)
    qtbot.mouseClick(
        first.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )
    first.well_search.setText("A1")

    other = _show_well_preview(
        qtbot,
        _well_preview(resource_id="well-head-2"),
        state_store=store,
    )
    assert other.active_well is None
    assert other.well_search.text() == ""

    restored = _show_well_preview(
        qtbot,
        _well_preview(resource_id="well-head-1"),
        state_store=store,
    )
    assert restored.active_well is not None
    assert restored.well_search.text() == "A1"

    store.clear()
    cleared = _show_well_preview(
        qtbot,
        _well_preview(resource_id="well-head-1"),
        state_store=store,
    )
    assert cleared.active_well is None
    assert cleared.well_search.text() == ""


def test_preview_state_restores_list_scroll_position(qtbot):
    store = WellLocationPreviewStateStore()
    prepared = _named_well_preview(
        tuple(f"W{index}" for index in range(200)),
        record_ids=tuple(range(200)),
    )
    first = _show_well_preview(qtbot, prepared, state_store=store)
    scroll = first.well_list.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    expected_scroll = scroll.value()
    first.release()

    restored = _show_well_preview(qtbot, prepared, state_store=store)

    assert restored.well_list.verticalScrollBar().value() == expected_scroll


def test_well_search_filters_names_only_and_preserves_plot_points(qtbot):
    preview = _show_well_preview(
        qtbot,
        _named_well_preview(
            ("North-A1", "south-a10", "Beta"),
            record_ids=(1, 2, 3),
        ),
    )

    preview.well_search.setText("A1")

    assert _list_texts(preview) == ["North-A1", "south-a10"]
    assert len(preview.plot.series_list[0].x) == 3

    preview.well_search.clear()

    assert _list_texts(preview) == ["Beta", "North-A1", "south-a10"]


def test_plot_and_list_replace_the_same_single_active_well(qtbot):
    prepared = _named_well_preview(
        ("A10", "A2", "A1"),
        record_ids=(10, 2, 1),
    )
    preview = _show_well_preview(qtbot, prepared)

    px, py = preview.plot.data_to_pixel(
        float(prepared.payload.x[0]),
        float(prepared.payload.y[0]),
    )
    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )

    assert preview.active_well is not None
    assert preview.active_well.name == "A10"
    assert preview.well_list.currentIndex().data() == "A10"

    a1_index = preview.well_list.model().index(0, 0)
    qtbot.mouseClick(
        preview.well_list.viewport(),
        Qt.LeftButton,
        pos=preview.well_list.visualRect(a1_index).center(),
    )

    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert preview.active_well.point_index == 2
    assert preview.plot.selected_point == ("Well locations", 2)
    assert preview.plot.selected_label == "A1"
    assert preview.well_list.selectionModel().selectedIndexes() == [a1_index]
    assert (preview.plot.view_xmin + preview.plot.view_xmax) / 2.0 == (
        pytest.approx(float(prepared.payload.x[2]))
    )
    assert (preview.plot.view_ymin + preview.plot.view_ymax) / 2.0 == (
        pytest.approx(float(prepared.payload.y[2]))
    )

    _drag_mouse(preview.plot, QPoint(300, 250), QPoint(340, 275))
    assert (preview.plot.view_xmin + preview.plot.view_xmax) / 2.0 != (
        pytest.approx(float(prepared.payload.x[2]))
    )

    qtbot.mouseClick(
        preview.well_list.viewport(),
        Qt.LeftButton,
        pos=preview.well_list.visualRect(a1_index).center(),
    )

    assert (preview.plot.view_xmin + preview.plot.view_xmax) / 2.0 == (
        pytest.approx(float(prepared.payload.x[2]))
    )
    assert (preview.plot.view_ymin + preview.plot.view_ymax) / 2.0 == (
        pytest.approx(float(prepared.payload.y[2]))
    )


def test_plot_selection_scrolls_to_list_row_without_stealing_focus(qtbot):
    prepared = _named_well_preview(
        tuple(f"A{index}" for index in range(1, 51)),
        record_ids=tuple(range(1, 51)),
    )
    preview = _show_well_preview(qtbot, prepared, size=(900, 340))
    last_index = len(prepared.payload.names) - 1
    px, py = preview.plot.data_to_pixel(
        float(prepared.payload.x[last_index]),
        float(prepared.payload.y[last_index]),
    )

    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )

    selected_index = preview.well_list.currentIndex()
    assert selected_index.isValid()
    assert selected_index.data() == "A50"
    assert preview.well_list.visualRect(selected_index).intersects(
        preview.well_list.viewport().rect()
    )
    assert preview.focusWidget() is preview.plot


def test_filter_reports_when_active_well_is_hidden_from_list(qtbot):
    preview = _show_well_preview(qtbot, _well_preview())
    px, py = preview.plot.data_to_pixel(30.0, 40.0)
    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )

    preview.well_search.setText("A1")

    assert preview.active_well is not None
    assert preview.active_well.name == "A2"
    assert preview.plot.selected_point == ("Well locations", 1)
    assert not preview.well_list.currentIndex().isValid()
    assert preview.filter_status.isVisible()
    assert "A2" in preview.filter_status.text()
    assert "图中高亮" in preview.filter_status.text()

    preview.well_search.clear()

    assert preview.well_list.currentIndex().isValid()
    assert not preview.filter_status.isVisible()


def test_keyboard_row_navigation_keeps_active_well_synchronized(qtbot):
    preview = _show_well_preview(qtbot, _well_preview())
    px, py = preview.plot.data_to_pixel(30.0, 40.0)
    qtbot.mouseClick(
        preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )

    preview.well_list.setFocus()
    qtbot.keyClick(preview.well_list, Qt.Key_Up)

    assert preview.well_list.currentIndex().data() == "A1"
    assert preview.active_well is not None
    assert preview.active_well.name == "A1"
    assert preview.plot.selected_point == ("Well locations", 0)
    assert preview.plot.selected_label == "A1"

    preview.well_search.setText("A2")

    assert preview.filter_status.isVisible()
    assert "A1" in preview.filter_status.text()


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
    assert not preview.well_list.currentIndex().isValid()
    assert preview.well_list.selectionModel().selectedIndexes() == []
    assert not preview.filter_status.isVisible()
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


def test_shared_host_restores_well_state_after_terminal_clear(qtbot):
    from paleo_workbench.viz.hosts.geoviz_preview_host import GeoVizPreviewHost

    host = GeoVizPreviewHost(GeoVizEngine.default())
    qtbot.addWidget(host)
    host.resize(900, 600)
    first = host.render(_well_preview())
    host.show()
    qtbot.wait(10)
    px, py = first.plot.data_to_pixel(10.0, 20.0)
    qtbot.mouseClick(
        first.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )
    first.well_search.setText("A1")
    first.plot.pan(25.0, 15.0)
    expected_view = first.plot.view_bounds()

    host.clear()
    restored = host.render(_well_preview())

    assert restored is not first
    assert restored.active_well is not None
    assert restored.active_well.identity == WellLocationId(
        "well-head-1",
        "version-1",
        8,
    )
    assert restored.well_search.text() == "A1"
    assert restored.plot.view_bounds() == pytest.approx(expected_view)


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

    prepared = _well_preview()
    reader_entry.show_preview(prepared)
    applied = visualization_entry.apply(
        VizPayload(
            kind="engine_preview",
            label="Well locations",
            prepared=prepared,
        )
    )

    assert applied is True
    reader_preview = reader_entry.host.stack.currentWidget()
    visualization_preview = visualization_entry.widget.stack.currentWidget()
    assert isinstance(reader_preview, WellLocationPreview)
    assert isinstance(
        visualization_preview,
        WellLocationPreview,
    )
    assert reader_preview.source_status.text() == visualization_preview.source_status.text()
    assert reader_preview.well_list.model().rowCount() == 2
    assert visualization_preview.well_list.model().rowCount() == 2


def test_data_and_visualization_entries_share_one_session_state(qtbot):
    from paleo_workbench.ui.pages.lazy_visualization_tabs import (
        LazyVisualizationTabs,
    )
    from paleo_workbench.viz.hosts.engine_preview_host import EnginePreviewHost

    engine = GeoVizEngine.default()
    store = WellLocationPreviewStateStore()
    reader_entry = LazyVisualizationTabs(
        engine,
        well_state_store=store,
    )
    visualization_entry = EnginePreviewHost(
        engine,
        well_state_store=store,
    )
    qtbot.addWidget(reader_entry)
    qtbot.addWidget(visualization_entry.widget)
    reader_entry.resize(900, 600)
    reader_entry.show()
    reader_entry.show_preview(_well_preview())
    qtbot.wait(10)
    reader_preview = reader_entry.host.stack.currentWidget()
    assert isinstance(reader_preview, WellLocationPreview)
    px, py = reader_preview.plot.data_to_pixel(10.0, 20.0)
    qtbot.mouseClick(
        reader_preview.plot,
        Qt.LeftButton,
        pos=QPoint(round(px), round(py)),
    )
    reader_preview.well_search.setText("A1")
    reader_preview.plot.pan(20.0, 10.0)
    expected_view = reader_preview.plot.view_bounds()

    assert visualization_entry.apply(
        VizPayload(
            kind="engine_preview",
            label="Well locations",
            prepared=_well_preview(),
        )
    )
    visualization_preview = visualization_entry.widget.stack.currentWidget()

    assert isinstance(visualization_preview, WellLocationPreview)
    assert visualization_preview.active_well is not None
    assert visualization_preview.active_well.identity == WellLocationId(
        "well-head-1",
        "version-1",
        8,
    )
    assert visualization_preview.well_search.text() == "A1"
    assert visualization_preview.plot.view_bounds() == pytest.approx(expected_view)
