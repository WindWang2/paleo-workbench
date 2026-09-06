"""L5 — 2-D interpretation-surface orientation switching (inline/crossline/time).

``set_profile_orientation`` re-shapes the profile-mode surface onto another
engine profile panel; the badge, panel visibility and exit-restore must all
follow, and the workspace combo drives it end to end.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel

_PROFILE_PANELS = ("_profile_il", "_profile_xl", "_profile_t", "_profile_arb")


def _make_panel(qtbot) -> SeismicViewPanel:
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    return panel


def _panel_visible(panel: SeismicViewPanel, name: str) -> bool:
    wrapper = getattr(panel.view, name, None)
    return wrapper is not None and not wrapper.parentWidget().isHidden()


def test_orientation_switch_swaps_visible_profile(qtbot):
    panel = _make_panel(qtbot)
    panel.enter_profile_mode()
    assert _panel_visible(panel, "_profile_il")
    assert not _panel_visible(panel, "_profile_xl")
    assert not _panel_visible(panel, "_profile_t")

    assert panel.set_profile_orientation("crossline") is True
    assert panel.profile_orientation == "crossline"
    assert _panel_visible(panel, "_profile_xl")
    assert not _panel_visible(panel, "_profile_il")
    assert not _panel_visible(panel, "_profile_t")
    badge = panel.view._inline_badge
    assert badge.text() == "Crossline 剖面"

    assert panel.set_profile_orientation("time") is True
    assert _panel_visible(panel, "_profile_t")
    assert not _panel_visible(panel, "_profile_il")
    assert not _panel_visible(panel, "_profile_xl")
    assert badge.text() == "Time 切片"


def test_unknown_orientation_refused(qtbot):
    panel = _make_panel(qtbot)
    panel.enter_profile_mode()
    assert panel.set_profile_orientation("diagonal") is False
    assert panel.profile_orientation == "inline"
    assert _panel_visible(panel, "_profile_il")


def test_orientation_before_enter_applies_on_enter(qtbot):
    panel = _make_panel(qtbot)
    assert panel.set_profile_orientation("time") is True
    panel.enter_profile_mode()
    assert _panel_visible(panel, "_profile_t")
    assert not _panel_visible(panel, "_profile_il")


def test_exit_restores_all_profiles_after_orientation_switches(qtbot):
    panel = _make_panel(qtbot)
    il_header_max = panel.view._profile_t.parentWidget().layout().itemAt(0).widget().maximumHeight()

    panel.enter_profile_mode()
    panel.set_profile_orientation("time")
    panel.set_profile_orientation("crossline")
    panel.exit_profile_mode()

    for name in _PROFILE_PANELS:
        assert _panel_visible(panel, name), name
    t_header = panel.view._profile_t.parentWidget().layout().itemAt(0).widget()
    assert t_header.maximumHeight() == il_header_max
    assert not t_header.isHidden()


def test_orientation_switch_is_repeatable(qtbot):
    panel = _make_panel(qtbot)
    panel.enter_profile_mode()
    for orientation in ("crossline", "time", "inline", "time", "crossline"):
        assert panel.set_profile_orientation(orientation) is True
    assert panel.profile_orientation == "crossline"
    panel.exit_profile_mode()
    for name in _PROFILE_PANELS:
        assert _panel_visible(panel, name), name
