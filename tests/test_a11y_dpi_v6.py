"""V6 Phase 7 — 有界无障碍 / DPI / 键盘修复（audit-g-visual-a11y.md）。

覆盖：
- G-P1-6 ``components/states.py`` 空态图标 DPR：按目标部件
  ``devicePixelRatioF`` 出图（此前强制 ``setDevicePixelRatio(1.0)``，
  HiDPI 下图标被放大一倍）；
- G-P0-2 主窗口几何持久化：dock 宿主（顶层 QMainWindow）随既有布局
  机制一起 ``saveGeometry``/``restoreGeometry``，恢复后 clamp 到可见
  桌面（离屏可测）；
- G-P1-5 Ctrl+S/N/O/F 单一绑定：经 ``shortcuts.register_shortcut`` 创建
  （此前直接 QShortcut + ``register_meta`` 双重登记，冲突检测盲区）；
- G-P1-3 工作站 chrome 图标按钮 ``accessibleName``/``accessibleDescription``。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QByteArray, QRect, QSize, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QShortcut
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolButton

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.layout_persistence import (
    LAYOUT_STATE_VERSION,
    SETTINGS_APP,
    SETTINGS_ORG,
)

_GEOMETRY_KEYS = (
    "layout/window_state",
    "layout/window_geometry",
    "layout/state_version",
)


@pytest.fixture()
def geometry_settings():
    """Hermetic window-geometry keys on the shared layout store.

    conftest 把默认 QSettings 重定向到会话级临时目录，但键在会话内共享：
    快照本测试触碰的键并在结束后还原，避免污染（或依赖）其他用例写入
    的布局状态。
    """
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    prior = {key: settings.value(key) for key in _GEOMETRY_KEYS}
    settings.remove("layout/window_geometry")
    settings.sync()
    yield settings
    for key, value in prior.items():
        if value is None:
            settings.remove(key)
        else:
            settings.setValue(key, value)
    settings.sync()


def _seed_geometry(settings: QSettings, blob: QByteArray) -> None:
    """Write a realistic layout store entry: version + state + geometry.

    ``window_state`` 里的占位字节对 restoreState 是不可解析垃圾（返回
    False、无副作用）——真实保存路径两者总是一起写，这里保持同一形状。
    """
    settings.setValue("layout/state_version", LAYOUT_STATE_VERSION)
    settings.setValue("layout/window_state", QByteArray(b"v6-test"))
    settings.setValue("layout/window_geometry", blob)
    settings.sync()


def _build_host_with_frame(qtbot) -> tuple[QMainWindow, object]:
    """A shown dock host (the role PaleoWorkbenchWindow plays in production)."""
    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    host = QMainWindow()
    qtbot.addWidget(host)
    host.resize(1440, 900)  # app.py 的默认起步几何
    frame = WorkstationFrame(
        ProjectDocument.new("布局测试"), QStackedWidget(), dock_host=host
    )
    return host, frame


# --- G-P1-6: PwbEmptyState icon DPR ----------------------------------------


def test_tinted_pixmap_scales_physical_pixels_to_requested_dpr(qtbot):
    from paleo_workbench.ui.components.states import _tinted_pixmap

    hidpi = _tinted_pixmap("inbox.svg", "TEXT_SECONDARY", 24, 2.0)
    assert hidpi.devicePixelRatio() == 2.0
    assert (hidpi.width(), hidpi.height()) == (48, 48)

    lodpi = _tinted_pixmap("inbox.svg", "TEXT_SECONDARY", 24, 1.0)
    assert lodpi.devicePixelRatio() == 1.0
    assert (lodpi.width(), lodpi.height()) == (24, 24)


def test_empty_state_icon_matches_host_widget_dpr(qtbot):
    from paleo_workbench.ui.components import PwbEmptyState

    state = PwbEmptyState("暂无数据")
    qtbot.addWidget(state)
    pm = state._icon.pixmap()
    # 逻辑尺寸恒为 24，物理 DPR 跟随宿主部件（离屏平台下两者均为 1）。
    assert pm.devicePixelRatio() == state._icon.devicePixelRatioF()
    assert round(pm.width() / pm.devicePixelRatio()) == 24


# --- G-P0-2: main-window geometry persistence ------------------------------


def test_window_geometry_roundtrip(qtbot, geometry_settings):
    source = QMainWindow()
    qtbot.addWidget(source)
    source.setGeometry(30, 40, 700, 500)
    source.show()
    blob = source.saveGeometry()
    _seed_geometry(geometry_settings, blob)

    # 持久化 blob 本身完整可还原：隐藏的裸窗口没有 dock 最小约束，
    # 也没有 offscreen 平台对已显示窗口的贴屏夹紧。
    control = QMainWindow()
    qtbot.addWidget(control)
    assert control.restoreGeometry(blob)
    assert control.geometry().size() == QSize(700, 500)
    assert abs(control.x() - 30) <= 2 and abs(control.y() - 40) <= 2

    # 宿主（dock 宿主 QMainWindow，生产中即 PaleoWorkbenchWindow）恢复。
    # 离屏宿主的 dock 最小宽（~1450px）宽于屏幕时，Qt/平台会把恢复结果
    # 贴屏（x→1、尺寸夹到最小约束）——位置断言容忍该 clamp，精确契约
    # 由上面的隐藏控制窗钉住。
    host, frame = _build_host_with_frame(qtbot)
    host.show()
    before = host.geometry()
    frame._restore_layout()

    geo = host.geometry()
    assert geo != before
    assert 0 <= geo.x() <= 32 and 25 <= geo.y() <= 42
    assert geo.width() >= 700 and geo.height() >= 500


def test_window_geometry_saved_alongside_layout(qtbot, geometry_settings):
    host, frame = _build_host_with_frame(qtbot)
    host.show()
    host.setGeometry(120, 90, 1000, 700)
    frame.flush_layout()  # 生产保存 seam（_refresh_shell / 关闭路径共用）

    blob = geometry_settings.value("layout/window_geometry")
    assert isinstance(blob, QByteArray) and not blob.isNull()
    # 落盘内容就是保存时刻的几何序列化（saveGeometry 对未变窗口是确定性的）。
    assert blob == host.saveGeometry()
    assert (
        geometry_settings.value("layout/state_version", 0, type=int)
        == LAYOUT_STATE_VERSION
    )


def test_restored_geometry_clamped_to_visible_desktop(
    qtbot, geometry_settings, monkeypatch
):
    from paleo_workbench.ui.workstation import shell as shell_module

    source = QMainWindow()
    qtbot.addWidget(source)
    source.setGeometry(5000, 5000, 300, 200)  # 保存时的显示器已不存在
    source.show()
    _seed_geometry(geometry_settings, source.saveGeometry())

    calls: list[QRect] = []
    # shell 经函数内导入取该函数（review 修复 P0 环），patch 其源模块。
    from paleo_workbench.ui import panel_float_controller as pfc_module

    real = pfc_module.clamp_geometry_to_screens

    def _spy(geometry: QRect) -> QRect:
        calls.append(geometry)
        return real(geometry)

    monkeypatch.setattr(pfc_module, "clamp_geometry_to_screens", _spy)

    host, frame = _build_host_with_frame(qtbot)
    host.show()
    frame._restore_layout()

    assert calls, "restore 必须对恢复的窗口几何执行 clamp"
    visible = QGuiApplication.primaryScreen().availableGeometry()
    for screen in QGuiApplication.screens()[1:]:
        visible = visible.united(screen.availableGeometry())
    geo = host.geometry()
    # clamp 契约：窗口与可见桌面相交，且左上角（抓握区）在可见桌面内
    # （离屏宿主的最小约束可宽于屏幕，此时 clamp 保证的是可达性而非全包含）。
    assert visible.intersects(geo)
    assert visible.contains(geo.topLeft())


def test_window_geometry_fenced_by_state_version(qtbot, geometry_settings):
    source = QMainWindow()
    qtbot.addWidget(source)
    source.setGeometry(30, 40, 700, 500)
    source.show()
    geometry_settings.setValue("layout/state_version", LAYOUT_STATE_VERSION - 1)
    geometry_settings.setValue("layout/window_state", QByteArray(b"v6-test"))
    geometry_settings.setValue("layout/window_geometry", source.saveGeometry())
    geometry_settings.sync()

    host, frame = _build_host_with_frame(qtbot)
    host.show()
    before = host.geometry()
    frame._restore_layout()

    # 未知版本的布局数据整体丢弃（版本栅栏），窗口保持默认起步几何。
    assert host.geometry() == before


# --- G-P1-5: window Ctrl shortcuts single binding --------------------------


def test_window_project_shortcuts_bound_via_registry(qtbot):
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui import shortcuts as registry

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)

    by_key: dict[str, list[QShortcut]] = {}
    for sc in window.findChildren(QShortcut):
        by_key.setdefault(sc.key().toString(), []).append(sc)

    for key in ("Ctrl+S", "Ctrl+N", "Ctrl+O", "Ctrl+F"):
        live = by_key.get(key, [])
        assert len(live) == 1, f"{key} 必须只有一个 QShortcut（audit G-P1-5）"
        # register_shortcut 的指纹：ApplicationShortcut 上下文（直接
        # QShortcut 默认 WindowShortcut，即旧的双重定义路径）。
        assert live[0].context() == Qt.ShortcutContext.ApplicationShortcut

    for spec_id in (
        "core:project.save",
        "core:project.new",
        "core:project.open",
        "core:search.focus",
    ):
        assert registry.get(spec_id) is not None

    dupes = registry.conflicts()
    for key in ("Ctrl+S", "Ctrl+N", "Ctrl+O", "Ctrl+F"):
        assert key not in dupes


# --- G-P1-3: accessible names on icon-only chrome buttons -------------------


def test_workstation_chrome_icon_only_buttons_have_accessible_names(qtbot):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    ws = shell.workstation

    # 编图工具条「面板」按钮：IconOnly 样式隐藏了 text，屏幕阅读器需要
    # 显式 accessibleName。
    panels = ws.composite.panels_button
    assert panels.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert panels.accessibleName() == "面板"
    assert panels.accessibleDescription() == panels.toolTip() != ""

    # 活动栏折叠钮（无文字），名称随图标/tooltip 状态翻转。
    collapse = ws.activity_rail.collapse_button
    assert collapse.accessibleName() == "折叠资源管理器"
    assert collapse.accessibleDescription()
    ws.activity_rail.set_explorer_expanded(False)
    assert collapse.accessibleName() == "展开资源管理器"
    ws.activity_rail.set_explorer_expanded(True)
    assert collapse.accessibleName() == "折叠资源管理器"

    # 资源管理器刷新钮（无文字；QLineEdit 清除钮也是无文字 QToolButton，
    # 用 objectName 精确定位）。
    refresh_buttons = [
        button
        for button in ws.explorer.findChildren(QToolButton)
        if button.objectName() == "WorkstationChromeButton"
    ]
    assert len(refresh_buttons) == 1
    assert refresh_buttons[0].accessibleName() == "刷新"
    assert refresh_buttons[0].accessibleDescription()

    # 反向约束：文字可见的 chrome 按钮不做机械 accessibleName。
    assert ws.app_bar.task_button.accessibleName() == ""
    assert ws.app_bar.project_button.accessibleName() == ""
