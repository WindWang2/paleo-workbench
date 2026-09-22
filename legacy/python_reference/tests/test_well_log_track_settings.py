from __future__ import annotations

import pytest

from PySide6.QtCore import Qt
from geoviz import CurveData, WellLogData
from geoviz_well_log.renderer import CurveTrack

from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.pages.well_log_track_settings import CurveTrackSettingsDialog
from paleo_workbench.viz.well_log_track_layout import (
    CurveGroupLimitError,
    build_configured_well_log_tracks,
    curve_keys_for,
    default_curve_track_layout,
)


def _well_data() -> WellLogData:
    names = ["AC", "DEN", "CNL", "RT", "SP", "CAL", "GR", "RXO"]
    return WellLogData(
        well_name="A-1",
        top_depth=1_000.0,
        bottom_depth=1_100.0,
        curves=[
            CurveData(
                name=name,
                unit="API",
                depth=[1_000.0, 1_050.0, 1_100.0],
                values=[float(index), float(index + 1), float(index + 2)],
            )
            for index, name in enumerate(names)
        ],
    )


def _curve_tracks(data: WellLogData, layout):
    return [
        track
        for track in build_configured_well_log_tracks(data, layout)
        if isinstance(track, CurveTrack)
    ]


def test_default_layout_shows_six_independent_curves_including_gr(qtbot):
    data = _well_data()
    layout = default_curve_track_layout(data.curves)

    tracks = _curve_tracks(data, layout)

    assert len(tracks) == 6
    assert all(len(track.curves) == 1 for track in tracks)
    assert "GR" in [track.curves[0].name for track in tracks]


def test_curve_grouping_is_bounded_to_three_and_can_be_unmerged(qtbot):
    data = _well_data()
    keys = curve_keys_for(data.curves)
    layout = default_curve_track_layout(data.curves)

    layout = layout.merge(keys[1], onto=keys[0])
    layout = layout.merge(keys[2], onto=keys[0])
    tracks = _curve_tracks(data, layout)

    assert len(tracks) == 4
    assert [curve.name for curve in tracks[0].curves] == ["CNL", "DEN", "AC"]
    with pytest.raises(CurveGroupLimitError):
        layout.merge(keys[3], onto=keys[0])

    restored = layout.unmerge(keys[0])
    restored_tracks = _curve_tracks(data, restored)
    assert len(restored_tracks) == 6
    assert all(len(track.curves) == 1 for track in restored_tracks)


def test_settings_dialog_handles_drag_merge_and_unmerge(qtbot):
    data = _well_data()
    layout = default_curve_track_layout(data.curves)
    dialog = CurveTrackSettingsDialog(data.curves, layout)
    qtbot.addWidget(dialog)
    keys = curve_keys_for(data.curves)

    third_curve = dialog.tree.topLevelItem(2)
    third_curve.setCheckState(1, Qt.CheckState.Unchecked)
    assert keys[2] not in dialog.layout.visible_curve_keys

    # The tree emits this when a source curve is dropped onto a target curve.
    dialog.tree.merge_requested.emit(keys[1], keys[0])
    assert dialog.layout.group_for(keys[0]) == (keys[1], keys[0])
    merged_group = dialog.tree.topLevelItem(0)
    assert merged_group.text(0) == "DEN+AC"
    assert [merged_group.child(index).text(0) for index in range(2)] == ["DEN", "AC"]
    assert dialog.unmerge_curve(keys[0]) is True
    assert dialog.layout.group_for(keys[0]) == (keys[0],)


def test_panel_applies_selected_visibility_and_grouping(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    data = _well_data()
    panel._show_well_log(data)
    keys = curve_keys_for(data.curves)

    assert len([track for track in panel.canvas.tracks if isinstance(track, CurveTrack)]) == 6
    panel.set_curve_track_layout(
        panel.curve_track_layout().merge(keys[1], onto=keys[0]).with_visible(keys[2], False)
    )

    tracks = [track for track in panel.canvas.tracks if isinstance(track, CurveTrack)]
    assert len(tracks) == 4
    assert [curve.name for curve in tracks[0].curves] == ["DEN", "AC"]
