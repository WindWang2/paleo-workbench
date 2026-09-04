"""B10: SeismicViewPanel 公开 profile-mode API（2-D 剖面解释形态）。

覆盖点（QT_QPA_PLATFORM=offscreen 可运行）：
- enter/exit 正确隐藏/恢复 3-D 专用控件、动作与 3-D 渲染器；
- 与默认模式互斥、幂等（重复 enter/exit 不崩、状态不漂移）；
- 不依赖引擎私有属性也能完成配置（stub view 时 API 降级为纯状态翻转）；
- profile mode 下既有公开加载路径不受影响（加载不复活 3-D 渲染）。

约定：被测配置一律通过公开 API（enter_profile_mode / exit_profile_mode /
set_profile_mode / set_interpretation_bar_visible）驱动；测试里对
``panel.view`` 私有属性的访问仅用于**观察**断言，不用于配置。
"""

import pytest
from PySide6.QtWidgets import QSplitter

import paleo_workbench.ui.pages.seismic_view_panel as panel_module
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel

# 引擎工具条上属于 3-D 工作流的入口（caption 去空白后）
_3D_ONLY_CAPTIONS = {"3D模式:", "加载 SEGY", "Demo"}
# 2-D 剖面解释仍需要的工具（VD/Wiggle、色标、属性）
_PROFILE_TOOL_CAPTIONS = {"显示:", "色标:", "属性:"}
_3D_ONLY_WIDGETS = (
    "_3d_mode_combo",
    "_horizon_menu_btn",
    "_render_menu_btn",
    "_overlay_menu_btn",
    "_slice_label",
    "_readout_label",
)
_SECONDARY_PROFILES = ("_profile_xl", "_profile_t", "_profile_arb")


def _make_panel(qtbot) -> SeismicViewPanel:
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    return panel


def _inline_header(panel: SeismicViewPanel):
    """引擎 inline 剖面板的行头（标题 + 导出按钮）。"""
    layout = panel.view._profile_il.parentWidget().layout()
    return layout.itemAt(0).widget()


def _visible_toolbar_captions(panel: SeismicViewPanel) -> set[str]:
    toolbar = panel.view._toolbar_row1
    captions = set()
    for action in toolbar.actions():
        if not action.isVisible():
            continue
        widget = toolbar.widgetForAction(action)
        if widget is not None and hasattr(widget, "text"):
            captions.add(widget.text().strip())
    return captions


def _toolbar_action_of(panel: SeismicViewPanel, widget):
    """工具条里挂在 *widget* 上的 QAction（引擎经 addWidget 挂载）。"""
    toolbar = panel.view._toolbar_row1
    for action in toolbar.actions():
        if toolbar.widgetForAction(action) is widget:
            return action
    return None


# ----------------------------------------------------------------------
# 默认形态基线
# ----------------------------------------------------------------------


def test_default_mode_is_3d_layout(qtbot):
    panel = _make_panel(qtbot)
    view = panel.view

    assert panel.profile_mode is False
    assert not view._renderer_3d.isHidden()
    assert getattr(view, "_inline_badge", None) is None
    for name in _SECONDARY_PROFILES:
        assert not getattr(view, name).parentWidget().isHidden()
    # 从未 show 的窗口里引擎工具条部件自身处于 hidden 态，默认形态用
    # action 可见性观察（profile mode 操纵的正是 action 可见性）。
    for name in _3D_ONLY_WIDGETS:
        action = _toolbar_action_of(panel, getattr(view, name))
        assert action is not None
        assert action.isVisible()
    assert _3D_ONLY_CAPTIONS <= _visible_toolbar_captions(panel)


# ----------------------------------------------------------------------
# 进入 / 退出：3-D 专用控件隐藏与恢复
# ----------------------------------------------------------------------


def test_enter_profile_mode_hides_3d_chrome_keeps_inline_surface(qtbot):
    panel = _make_panel(qtbot)
    view = panel.view
    renderer = view._renderer_3d
    splitter = renderer.parentWidget()
    assert isinstance(splitter, QSplitter)

    panel.enter_profile_mode()

    assert panel.profile_mode is True
    # 3-D 渲染器整行收起
    assert renderer.isHidden()
    assert renderer.minimumHeight() == 0
    assert splitter.handleWidth() == 0
    assert splitter.sizes()[0] == 0
    # 其余剖面板隐藏，inline 剖面保持为解释面
    for name in _SECONDARY_PROFILES:
        assert getattr(view, name).parentWidget().isHidden()
    assert not view._profile_il.parentWidget().isHidden()
    assert not view._profile_il.isHidden()
    # inline 行头收起，标识收进工具条徽标
    assert _inline_header(panel).isHidden()
    badge = getattr(view, "_inline_badge", None)
    assert badge is not None
    assert not badge.isHidden()
    # 3-D 专用控件/动作全部不可见
    for name in _3D_ONLY_WIDGETS:
        widget = getattr(view, name)
        assert widget.isHidden()
        assert not _toolbar_action_of(panel, widget).isVisible()
    captions = _visible_toolbar_captions(panel)
    assert not _3D_ONLY_CAPTIONS & captions
    # inline/crossline 解释工具仍然可用
    assert _PROFILE_TOOL_CAPTIONS <= captions


def test_exit_profile_mode_restores_default_layout(qtbot):
    panel = _make_panel(qtbot)
    view = panel.view
    renderer = view._renderer_3d
    splitter = renderer.parentWidget()
    min_height_before = renderer.minimumHeight()
    handle_before = splitter.handleWidth()
    header = _inline_header(panel)
    header_max_before = header.maximumHeight()

    panel.enter_profile_mode()
    panel.exit_profile_mode()

    assert panel.profile_mode is False
    assert not renderer.isHidden()
    assert renderer.minimumHeight() == min_height_before
    assert splitter.handleWidth() == handle_before
    assert not splitter.isCollapsible(0)
    assert sum(splitter.sizes()) > 0
    for name in _SECONDARY_PROFILES:
        assert not getattr(view, name).parentWidget().isHidden()
    assert not header.isHidden()
    assert header.maximumHeight() == header_max_before
    for name in _3D_ONLY_WIDGETS:
        widget = getattr(view, name)
        assert not widget.isHidden()
        assert _toolbar_action_of(panel, widget).isVisible()
    assert _3D_ONLY_CAPTIONS <= _visible_toolbar_captions(panel)
    badge = getattr(view, "_inline_badge", None)
    assert badge is not None  # 徽标保留复用，但随默认形态隐藏
    assert badge.isHidden()


def test_profile_mode_round_trip_repeated_cycles(qtbot):
    """enter→exit 多次循环后状态不漂移（restore 基线只采集一次）。"""
    panel = _make_panel(qtbot)
    view = panel.view
    renderer = view._renderer_3d

    for _ in range(3):
        panel.enter_profile_mode()
        assert renderer.isHidden()
        assert not view._profile_il.parentWidget().isHidden()
        for name in _SECONDARY_PROFILES:
            assert getattr(view, name).parentWidget().isHidden()
        panel.exit_profile_mode()
        assert not renderer.isHidden()
        for name in _SECONDARY_PROFILES:
            assert not getattr(view, name).parentWidget().isHidden()
    assert renderer.minimumHeight() == 200  # 引擎构造默认值未被循环破坏
    assert sum(renderer.parentWidget().sizes()) > 0


# ----------------------------------------------------------------------
# 互斥与幂等
# ----------------------------------------------------------------------


def test_profile_mode_is_idempotent_and_mutually_exclusive(qtbot):
    panel = _make_panel(qtbot)

    # 重复 enter：不崩、状态不漂移、徽标不重建
    panel.enter_profile_mode()
    badge = panel.view._inline_badge
    panel.enter_profile_mode()
    panel.enter_profile_mode()
    assert panel.profile_mode is True
    assert panel.view._inline_badge is badge
    assert panel.view._renderer_3d.isHidden()

    # 重复 exit：不崩、回落默认形态
    panel.exit_profile_mode()
    panel.exit_profile_mode()
    assert panel.profile_mode is False
    assert not panel.view._renderer_3d.isHidden()

    # 布尔别名语义一致
    panel.set_profile_mode(True)
    assert panel.profile_mode is True
    panel.set_profile_mode(True)  # 幂等
    assert panel.profile_mode is True
    panel.set_profile_mode(False)
    panel.set_profile_mode(False)  # 幂等
    assert panel.profile_mode is False

    # 只读属性：状态只能经 API 翻转
    with pytest.raises(AttributeError):
        panel.profile_mode = True


# ----------------------------------------------------------------------
# 不依赖引擎私有属性（stub view 降级路径）
# ----------------------------------------------------------------------


def test_profile_mode_without_engine_internals(qtbot, monkeypatch):
    """空面板 + stub view：私有属性缺失时 API 仍完成状态翻转，不崩。"""
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    class StubView(QWidget):
        segy_loaded = Signal(object)

        def __init__(self, *, auto_load=False):
            super().__init__()
            self._slice_worker = None

        def cancel_pending_segy_load(self):
            pass

        def is_ready(self):
            return False

    monkeypatch.setattr(panel_module, "SeismicView", StubView)
    panel = panel_module.SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.enter_profile_mode()
    panel.enter_profile_mode()
    assert panel.profile_mode is True

    panel.set_profile_mode(False)
    panel.exit_profile_mode()
    panel.exit_profile_mode()
    assert panel.profile_mode is False


# ----------------------------------------------------------------------
# profile mode 与既有加载路径共存
# ----------------------------------------------------------------------


def test_profile_mode_survives_public_load_path(qtbot):
    """profile mode 下走公开 update_state 加载路径：数据就绪、3-D 不复活。"""
    panel = _make_panel(qtbot)
    panel.enter_profile_mode()

    project = ProjectDocument.new("ProfileMode")
    task = MockPredictionAdapter().run(project, [], seed=3)
    ready = []
    panel.view_ready.connect(ready.append)
    panel.update_state(task)

    assert ready == [True]
    assert panel.volume_shape == (8, 10, 12)
    assert panel.stack.currentWidget() is panel.view
    assert panel.profile_mode is True
    assert panel.view._renderer_3d.isHidden()
    assert not panel.view._profile_il.parentWidget().isHidden()

    # 退出后仍能回到默认 3-D 形态
    panel.exit_profile_mode()
    assert not panel.view._renderer_3d.isHidden()
    assert panel.profile_mode is False


# ----------------------------------------------------------------------
# 解释动作条（panel 自有部件）显隐
# ----------------------------------------------------------------------


def test_set_interpretation_bar_visible(qtbot):
    panel = _make_panel(qtbot)
    buttons = (
        panel.interp_draft_btn,
        panel.interp_sync_btn,
        panel.interp_undo_btn,
        panel.interp_redo_btn,
        panel.interp_save_btn,
        panel.interp_reload_btn,
    )

    panel.set_interpretation_bar_visible(False)
    assert all(button.isHidden() for button in buttons)

    panel.set_interpretation_bar_visible(True)
    assert all(not button.isHidden() for button in buttons)
