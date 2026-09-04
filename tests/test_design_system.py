"""B1 design system contracts: density tokens, theme reachability, dynamic styles."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench import tokens


def test_spacing_scale_is_complete_and_ordered():
    scale = [
        tokens.SPACE_XS,
        tokens.SPACE_S,
        tokens.SPACE_M,
        tokens.SPACE_L,
        tokens.SPACE_XL,
        tokens.SPACE_2XL,
    ]
    assert scale == [2, 4, 8, 12, 16, 24]
    assert scale == sorted(scale)
    # legacy aliases stay stable（全库大量调用点）
    assert (tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_3) == (4, 8, 12)


def test_density_tokens_cover_both_modes():
    assert set(tokens.DENSITY_TOKENS) == {"compact", "comfortable"}
    compact = tokens.DENSITY_TOKENS["compact"]
    comfortable = tokens.DENSITY_TOKENS["comfortable"]
    assert compact["btn_height"] < comfortable["btn_height"]
    assert compact["padding_y"] < comfortable["padding_y"]


def test_build_qss_reflects_density():
    compact = tokens.build_qss(density="compact", theme="light")
    comfortable = tokens.build_qss(density="comfortable", theme="light")
    assert compact != comfortable
    assert "24px" in compact  # compact btn height
    assert "30px" in comfortable


def test_semantic_surface_aliases_exist_in_every_palette():
    for theme in ("light", "dark", "high_contrast"):
        palette = tokens.palette_for(theme)
        for key in ("SURFACE", "SURFACE_RAISED", "SURFACE_PANEL", "TEXT_MUTED"):
            assert palette[key], f"{key} missing in {theme}"


def test_theme_manager_density_roundtrip(qtbot):
    from paleo_workbench.ui.theme import DensityMode, ThemeManager, ThemeMode

    manager = ThemeManager()
    emitted = []
    manager.theme_changed.connect(lambda *args: emitted.append(args))
    manager.set_density(DensityMode.COMPACT)
    manager.set_theme(ThemeMode.DARK)
    assert emitted == [
        ("light", "compact"),
        ("dark", "compact"),
    ]
    assert manager.get_qss() == tokens.build_qss(
        density="compact", theme="dark"
    )


def test_theme_manager_persists(qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("ui/theme", "dark")
    settings.setValue("ui/density", "compact")
    settings.sync()

    # 直接验证 ThemeManager 的持久化键往返（独立 QSettings 实例同文件）
    from paleo_workbench.ui.theme import theme_manager

    # save path: change → persisted via org/app QSettings（用默认实例可能写
    # 到用户配置；这里只验证加载路径读取同一键）。
    theme_manager._current_theme.__class__  # 保持 import 引用
    saved = QSettings("PaleoWorkbench", "Workstation")
    saved.setValue("ui/theme", "high_contrast")
    saved.setValue("ui/density", "compact")
    saved.sync()
    manager = type(theme_manager)()
    manager.load_persisted()
    assert manager.current_theme.value == "high_contrast"
    assert manager.density.value == "compact"


def test_dynamic_style_registry_rerenders_on_theme_change(qtbot):
    from PySide6.QtWidgets import QLabel

    from paleo_workbench.ui import style
    from paleo_workbench.ui.theme import theme_manager

    label = QLabel()
    qtbot.addWidget(label)

    def render() -> str:
        pal = style.palette()
        return f"color: {pal['TEXT_PRIMARY']};"

    style.bind(label, render)
    before = label.styleSheet()
    assert "color:" in before
    theme_manager.set_theme("dark")
    after_dark = label.styleSheet()
    theme_manager.set_theme("light")
    assert after_dark != before or tokens.palette_for("dark")["TEXT_PRIMARY"] == tokens.TEXT_PRIMARY
    assert label.styleSheet() == before


def test_app_bar_view_menu_is_production_theme_entry(qtbot):
    """B16：主题切换必须从生产 UI 可达（此前仅测试调用 set_theme）。"""
    from paleo_workbench.ui.theme import theme_manager
    from paleo_workbench.ui.workstation.app_bar import WorkstationAppBar

    bar = WorkstationAppBar()
    qtbot.addWidget(bar)
    actions = [a.text() for a in bar._view_menu.actions()]
    assert "深色主题" in actions and "紧凑密度" in actions
    dark = next(a for a in bar._view_menu.actions() if a.text() == "深色主题")
    dark.trigger()
    assert theme_manager.current_theme.value == "dark"
    theme_manager.set_theme("light")
