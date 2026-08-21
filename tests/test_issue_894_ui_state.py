"""Regression tests for the UI-state refresh batch (#894).

Five independent state-loss bugs, one test each:

* #894-1 a routine ``update_assets`` refresh reset user-dragged column widths.
* #894-2 ``FactorTaskPanel.update_state`` overwrote the user's method choice.
* #894-3 undoing every edit back to the baseline still showed "unsaved".
* #894-4 a failed seismic reload resurrected the previous asset's pixmap on
  the next resize.
* #894-5 ``SequenceTargetPanel`` dropped a re-commit of a previously emitted
  target because the dedupe cache was not resynced by ``update_state``.
"""

from __future__ import annotations

import numpy as np

from paleo_workbench.project.models import (
    FactorMapTask,
    ResourceItem,
    StratigraphicFramework,
)
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.pages.map_edit_commands import EditCommandStack
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.seismic_slice_preview_widget import (
    SeismicSlicePreviewWidget,
)
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel
from paleo_workbench.ui.tokens import INTERPOLATION_METHODS


def _resources(n: int = 5) -> list[ResourceItem]:
    return [
        ResourceItem(
            name=f"r{i}.las", path=f"/tmp/r{i}.las", type="well_log", format="las"
        )
        for i in range(n)
    ]


def _factor_tasks(method: str, count: int = 3) -> list[FactorMapTask]:
    return [
        FactorMapTask(
            name=f"factor{i}",
            target_horizon="H1",
            factor_type=f"因素{i}",
            method=method,
            status="complete",
        )
        for i in range(count)
    ]


# --------------------------------------------------------------------------- #
# #894-1 — column widths


def test_refresh_preserves_user_column_width(qtbot) -> None:
    """A routine refresh must not reset a width the user dragged."""
    table = DataAssetTable()
    qtbot.addWidget(table)
    res = _resources()
    table.update_assets(res, [])
    table.show()
    qtbot.wait(0)

    header = table.table.horizontalHeader()
    name_col = 0
    header.resizeSection(name_col, 400)
    assert header.sectionSize(name_col) == 400

    # Routine refresh (tag change / verify finish / import all end here).
    table.update_assets(res, [])
    assert header.sectionSize(name_col) == 400, (
        "user column width was reset by a routine data refresh"
    )


def test_column_set_change_refits_new_columns_but_keeps_user_width(qtbot) -> None:
    """Auto-fit still runs when the column set changes, yet a user-dragged
    column keeps its width even through that refit."""
    table = DataAssetTable()
    qtbot.addWidget(table)
    res = _resources()
    table.update_assets(res, [])

    header = table.table.horizontalHeader()
    name_col = 0
    header.resizeSection(name_col, 400)

    # Column set change: reveal a column that was hidden before.
    keys = table.visible_column_keys()
    assert "format" not in keys
    table.set_visible_columns([*keys, "format"])
    table.update_assets(res, [])

    keys_after = table.visible_column_keys()
    name_col_after = keys_after.index("name")
    format_col = keys_after.index("format")
    assert header.sectionSize(name_col_after) == 400
    # The brand-new column was auto-fitted, not left at a default stub.
    assert 0 < header.sectionSize(format_col) <= 300


# --------------------------------------------------------------------------- #
# #894-2 — factor task panel method combo


def test_update_state_does_not_override_user_method_choice(qtbot) -> None:
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)

    seeded = INTERPOLATION_METHODS[0]  # "克里金"
    tasks = _factor_tasks(seeded)
    panel.update_state(tasks)
    assert panel.method_combo.currentText() == seeded

    # The user picks a different method (activated = real user selection).
    user_choice = "方向趋势"
    idx = panel.method_combo.findText(user_choice)
    assert idx >= 0
    panel.method_combo.setCurrentIndex(idx)
    panel.method_combo.activated.emit(idx)

    # Progress-polling refreshes push the same tasks again.
    panel.update_state(tasks)
    assert panel.method_combo.currentText() == user_choice, (
        "refresh overwrote the user's interpolation method"
    )
    panel.update_state(tasks)
    assert panel.method_combo.currentText() == user_choice


def test_update_state_seeds_common_method_until_user_chooses(qtbot) -> None:
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)

    common = "样条"
    panel.update_state(_factor_tasks(common))
    assert panel.method_combo.currentText() == common

    # A refresh with a different common method still re-seeds while the user
    # has never touched the combo.
    panel.update_state(_factor_tasks("IDW"))
    assert panel.method_combo.currentText() == "IDW"


# --------------------------------------------------------------------------- #
# #894-3 — undo/redo dirty flag


def test_undo_to_baseline_clears_dirty_and_redo_redirties(qtbot) -> None:
    scene = MapEditScene()
    scene.load_document(None)
    assert scene.is_dirty() is False

    fid = scene.create_feature(
        {"kind": "line", "name": "", "coordinates": [[0, 0], [1, 1]]}
    )
    assert fid is not None
    assert scene.is_dirty() is True
    scene.translate_features([fid], 5.0, 5.0)
    assert scene.is_dirty() is True

    while scene.command_stack().can_undo():
        assert scene.undo() is True
    assert scene.command_stack().can_undo() is False
    assert scene.is_dirty() is False, (
        "undoing every edit back to the baseline must clear the dirty flag"
    )

    assert scene.redo() is True
    assert scene.is_dirty() is True, "a redone edit must re-mark the document dirty"


def test_undo_all_stays_dirty_when_depth_cap_dropped_commands(qtbot) -> None:
    """If the 50-deep cap trimmed commands, undoing can no longer reach the
    baseline — the document must stay dirty instead of faking clean."""
    scene = MapEditScene()
    scene._command_stack = EditCommandStack(max_depth=1)
    scene.load_document(None)

    for i in range(2):
        fid = scene.create_feature(
            {"kind": "label", "name": "", "text": "x", "coordinates": [i, i]}
        )
        assert fid is not None
    assert scene.command_stack().overflowed is True

    while scene.command_stack().can_undo():
        scene.undo()
    assert scene.is_dirty() is True, (
        "trimmed undo history means the baseline is unreachable: stay dirty"
    )


# --------------------------------------------------------------------------- #
# #894-4 — stale slice pixmap


def test_failed_reload_and_resize_do_not_resurrect_stale_pixmap(qtbot) -> None:
    w = SeismicSlicePreviewWidget()
    qtbot.addWidget(w)
    w.resize(600, 400)
    w.show()

    vol = np.arange(6 * 7 * 8, dtype=np.float32).reshape(6, 7, 8)
    w.load_seismic("/fake/a.sgy", revision=(1,), volume=vol)
    pm = w.image_label.pixmap()
    assert pm is not None and not pm.isNull()

    # Switch to an asset that fails to parse -> volume None, message shown.
    message = "无地震数据或无法解析"
    w.load_seismic("/fake/broken.sgy", revision=(2,), volume=None, message=message)
    assert w._volume is None
    assert w._last_pixmap is None
    assert w.image_label.text() == message

    # A user resize must re-install nothing.
    w.resize(700, 500)
    qtbot.wait(0)
    pm = w.image_label.pixmap()
    assert pm is None or pm.isNull(), "resize resurrected the previous asset's image"
    assert w.image_label.text() == message


# --------------------------------------------------------------------------- #
# #894-5 — sequence target re-commit


def _strat(target: str) -> StratigraphicFramework:
    return StratigraphicFramework(
        target_horizon=target,
        sequence_boundaries=["T1", "T2", "T3"],
    )


def test_recommit_after_programmatic_target_change_emits(qtbot) -> None:
    panel = SequenceTargetPanel()
    qtbot.addWidget(panel)
    emitted: list[str] = []
    panel.target_changed.connect(emitted.append)

    # Step 1: the project target is T1; the user commits T2 via the dropdown.
    panel.update_state(_strat("T1"))
    panel.target_combo.setCurrentText("T2")
    panel._on_target_committed()
    assert emitted == ["T2"]

    # Step 2: the project programmatically moves the target back to T1
    # (project switch / restore rebuilds the combo but the project keeps T1).
    panel.update_state(_strat("T1"))
    assert panel.current_target() == "T1"
    # Re-activating the current project target is still deduped.
    panel.target_combo.setCurrentText("T1")
    panel._on_target_committed()
    assert emitted == ["T2"]

    # Step 3: the user activates T2 again — this must emit, not be swallowed.
    count_before = len(emitted)
    panel.target_combo.setCurrentText("T2")
    panel._on_target_committed()
    assert emitted[count_before:] == ["T2"], (
        "re-selecting a previously committed target after a programmatic "
        "change was dropped by the stale dedupe cache"
    )
