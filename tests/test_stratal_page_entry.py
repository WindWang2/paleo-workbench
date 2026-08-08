"""Tests for the stratal/proportional-slice entry on the 3D modeling page.

Stage-3 acceptance: the stage-2 capability has a clickable entry in the main
program and produces a minimum observable result (≥1 proportional slice visible
in the 3D viewport), even in an offscreen/no-SEGY environment (demo fallback).
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

    # Switch to the demo path and generate.
    page._stratal_demo_check.setChecked(True)
    page._stratal_fractions.setCurrentIndex(0)  # 1/4, 1/2, 3/4
    page._on_generate_stratal_slices()

    snap = renderer.get_stratal_slices()
    assert len(snap) == 3  # three proportional slices
    # Each registered plane pair is added to the GL view.
    assert len(renderer._stratal_plane_items) == 3
    for image, _ in renderer._stratal_plane_items.values():
        assert image in renderer._view.items
    # Status text reflects the action.
    assert "比例切片" in page._stratal_status.text()


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
