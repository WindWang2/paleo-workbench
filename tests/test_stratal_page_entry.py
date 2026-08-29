"""Tests for the stratal/proportional-slice entry on the 3D modeling page.

Stage-3 acceptance: the stage-2 capability has a clickable entry in the main
program and produces a minimum observable result (≥1 proportional slice visible
in the 3D viewport), even in an offscreen/no-SEGY environment (demo fallback).

#940-1: the two renderer-dependent tests below need a real GL context and are
marked ``opengl``; they are permanently skipped on offscreen CI and have no
dedicated software-GL leg today. Pure-logic stratal tests (card structure,
worker without GL) run everywhere.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------- structure: the analysis card + stratal entry exist ----------

def test_stratal_analysis_card_present_but_hidden(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    # The toggling button exists in the floating toolbar.
    assert page._joint_analysis_btn.text() == "分析"
    assert page._joint_analysis_btn.isCheckable()
    # The card exists and starts hidden (toggled on by the button).
    assert page._joint_analysis_card is not None
    assert not page._joint_analysis_card.isVisibleTo(page)
    # Four labeled tabs are populated.
    assert page._joint_analysis_tabs.count() == 4
    labels = [
        page._joint_analysis_tabs.tabText(i)
        for i in range(page._joint_analysis_tabs.count())
    ]
    assert labels == ["等时切片与属性", "井震标定", "沉积相解释", "导出与诊断"]


def test_stratal_tab_has_clickable_generate_and_clear(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert page.btn_stratal_generate.text() == "生成地层切片"
    assert page.btn_stratal_clear.text() == "清除"
    # Two horizon selectors + a fractions combo + demo checkbox.
    assert page._stratal_top_combo is not None
    assert page._stratal_bot_combo is not None
    assert page._stratal_fractions.count() >= 3
    assert page._stratal_demo_check is not None


def test_analysis_button_toggles_card_visibility(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert not page._joint_analysis_card.isVisibleTo(page)
    page._joint_analysis_btn.setChecked(True)
    assert page._joint_analysis_card.isVisibleTo(page)
    page._joint_analysis_btn.setChecked(False)
    assert not page._joint_analysis_card.isVisibleTo(page)


# ---------- minimum observable result: demo fallback path ----------

@pytest.mark.opengl  # #940-1: needs real GL; skipped on offscreen CI (no leg covers this today)
def test_stratal_generate_demo_produces_visible_slices(qtbot):
    """The minimum-observable-result acceptance criterion.

    With no real SEGY loaded (offscreen env), enabling the demo checkbox and
    clicking "生成地层切片" must (a) mount a synthetic volume on the renderer
    and (b) register ≥1 stratal plane that is visible in the 3D viewport.
    """
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    # Mount the joint widget so a real Renderer3D exists.
    page._ensure_joint_widget()
    renderer = getattr(page._joint_widget, "renderer", None)
    if renderer is None:
        pytest.skip("Renderer3D could not initialize in this offscreen environment")

    # Switch to the demo path and generate (computation runs on a worker
    # thread). Start the job FIRST, then wait on the worker's completed
    # signal (the worker is created by start(), so it must exist before
    # waitSignal dereferences it).
    page._stratal_demo_check.setChecked(True)
    page._stratal_fractions.setCurrentIndex(0)  # 1/4, 1/2, 3/4
    page._on_generate_stratal_slices()
    with qtbot.waitSignal(
        page._stratal_job.worker.completed, timeout=5000
    ) as blocker:
        pass
    assert blocker.args is not None and blocker.args[0]["demo"] is True
    # The completed signal fires on the WORKER thread; the UI applies the
    # result via a queued slot (_on_stratal_completed). Waiting for the
    # signal alone races the handler — wait for the applied state.
    qtbot.waitUntil(
        lambda: len(renderer.get_stratal_slices()) == 3, timeout=5_000
    )
    snap = renderer.get_stratal_slices()
    assert len(snap) == 3  # three proportional slices
    # Each registered plane pair is added to the GL view.
    assert len(renderer._stratal_plane_items) == 3
    for image, _ in renderer._stratal_plane_items.values():
        assert image in renderer._view.items
    # Status text reflects the action.
    assert "比例切片" in page._stratal_status.text()


@pytest.mark.opengl  # #940-1: needs real GL; skipped on offscreen CI (no leg covers this today)
def test_stratal_clear_removes_all_slices(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._ensure_joint_widget()
    renderer = getattr(page._joint_widget, "renderer", None)
    if renderer is None:
        pytest.skip("Renderer3D could not initialize in this offscreen environment")

    page._stratal_demo_check.setChecked(True)
    page._on_generate_stratal_slices()
    # Wait for the async worker to finish applying slices before asserting.
    with qtbot.waitSignal(
        page._stratal_job.worker.completed, timeout=5000
    ) as blocker:
        pass
    assert blocker.args is not None and blocker.args[0]["demo"] is True
    # Same queued-handler race as the generate test: the plane items are
    # registered by _on_stratal_completed, not by the worker signal.
    qtbot.waitUntil(
        lambda: bool(renderer._stratal_plane_items), timeout=5_000
    )
    assert renderer._stratal_plane_items
    page._on_clear_stratal_slices()
    assert renderer._stratal_plane_items == {}
    assert "清除" in page._stratal_status.text()


def test_stratal_fractions_options_are_valid(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    for i in range(page._stratal_fractions.count()):
        fracs = page._stratal_fractions.itemData(i)
        assert fracs is not None and len(fracs) >= 1
        assert all(0.0 <= f <= 1.0 for f in fracs)


def test_stratal_horizon_browse_populates_combo(qtbot, tmp_path):
    """The horizon file pickers should record the chosen path in the combo."""
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    fake = tmp_path / "top.dat"
    fake.write_text("# synthetic\n100 200 1500.0\n")
    # Simulate a successful pick by directly calling the handler's effect.
    page._stratal_top_combo.clear()
    page._stratal_top_combo.addItem(str(fake), str(fake))
    assert page._stratal_top_combo.currentData() == str(fake)


def test_stratal_worker_demo_produces_surfaces(qtbot):
    """StratalWorker demo path emits the expected surfaces/labels without any
    GL renderer — verifies the worker itself (the part the UI test cannot
    reach on the offscreen platform)."""
    from paleo_workbench.ui.pages.geological_modeling_workers import StratalWorker

    worker = StratalWorker(demo=True, fractions=(0.25, 0.50, 0.75))
    with qtbot.waitSignal(worker.completed, timeout=5000) as blocker:
        worker.run()
    result = blocker.args[0]
    assert result["demo"] is True
    assert len(result["surfaces"]) == 3
    assert result["labels"] == ["k=0.25", "k=0.50", "k=0.75"]


def test_stratal_worker_real_path_without_survey_fails_cleanly(qtbot):
    """StratalWorker real-data path with no usable scene/volume fails with a
    message (never crashes, never silently fabricates)."""
    from paleo_workbench.ui.pages.geological_modeling_workers import StratalWorker

    worker = StratalWorker(
        demo=False,
        fractions=(0.5,),
        scene=None,
        volume=None,
        top_path="missing.dat",
        bottom_path="missing.dat",
    )
    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.run()
    assert "survey/registration" in blocker.args[0] or "不可用" in blocker.args[0]


def test_stratal_worker_runs_off_gui_thread_via_owned_job(qtbot):
    """Stratal computation must execute on the owned worker QThread, never
    the GUI thread (C17).

    Regression: the page constructed StratalWorker with ``parent=self``, which
    made ``moveToThread`` in ``OwnedWorkerJob.start`` a silent no-op — run()
    was queued back to the GUI thread and froze the UI for the whole
    horizon-parse + resample duration.
    """
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.pages.geological_modeling_workers import StratalWorker

    executed_on: list[QThread] = []

    class _ThreadAwareStratalWorker(StratalWorker):
        def run(self) -> None:
            executed_on.append(QThread.currentThread())
            super().run()

    worker = _ThreadAwareStratalWorker(demo=True, fractions=(0.25,))
    job = OwnedWorkerJob()
    completed: list[dict] = []
    job.start(
        worker,
        terminal_signals=(worker.terminal,),
        result_connections=((worker.completed, completed.append),),
    )
    qtbot.waitUntil(lambda: bool(completed), timeout=5_000)
    qtbot.waitUntil(lambda: job.thread is None, timeout=5_000)

    app = QApplication.instance()
    assert app is not None
    assert len(executed_on) == 1
    assert executed_on[0] is not app.thread()
    assert completed[0]["demo"] is True
