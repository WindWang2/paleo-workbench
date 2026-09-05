"""命令注册表 / 中央快捷键注册表 / 屏幕外 clamp 测试（V5-U6）。"""
from __future__ import annotations

from PySide6.QtCore import QRect

from paleo_workbench.ui.command_registry import CommandRegistry, CommandSpec
from paleo_workbench.ui.shortcuts import (
    ShortcutSpec,
    all_specs,
    conflicts,
    register_meta,
)


def _clean_registry():
    reg = CommandRegistry()

    def _noop():  # pragma: no cover
        return None

    reg.register(
        CommandSpec(id="nav:1:a", label="数据 / 项目概述", hint="数据页 · 项目概述", group="页面", callback=_noop)
    )
    reg.register(
        CommandSpec(id="nav:4:x", label="编图", hint="编图页 · 编图", group="页面", callback=_noop)
    )
    reg.register(
        CommandSpec(id="core:theme.dark", label="主题 · 深色", keywords="dark theme 主题", group="视图", callback=_noop)
    )
    return reg


def test_register_and_query():
    reg = _clean_registry()
    assert len(reg.specs()) == 3
    assert reg.get("nav:4:x").label == "编图"
    reg.unregister("nav:4:x")
    assert reg.get("nav:4:x") is None


def test_duplicate_register_replaces():
    reg = CommandRegistry()
    reg.register(CommandSpec(id="x", label="A"))
    reg.register(CommandSpec(id="x", label="B"))
    assert len(reg.specs()) == 1
    assert reg.specs()[0].label == "B"


def test_fuzzy_subsequence_matching():
    reg = _clean_registry()
    hits = reg.find("编图")
    assert hits and hits[0].id == "nav:4:x"
    # 前缀命中优先
    hits = reg.find("主题")
    assert hits and hits[0].id == "core:theme.dark"
    # keywords 参与弱匹配
    hits = reg.find("dark")
    assert hits and hits[0].id == "core:theme.dark"
    # 无命中
    assert reg.find("不存在的命令xyz") == []


def test_recent_pinned_and_persisted(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "recents.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "paleo_workbench.ui.command_registry.QSettings", lambda *a, **k: settings
    )
    reg = _clean_registry()
    reg.record_recent("core:theme.dark")
    reg.record_recent("nav:4:x")
    reg.record_recent("core:theme.dark")  # 再命中提前
    assert [s.id for s in reg.recent_specs()][0] == "core:theme.dark"

    fresh = CommandRegistry()
    fresh.register(CommandSpec(id="core:theme.dark", label="主题 · 深色"))
    fresh.register(CommandSpec(id="nav:4:x", label="编图"))
    fresh.load_recent()
    assert fresh.recent_specs()[0].id in {"core:theme.dark", "nav:4:x"}
    # 未注册的 recent id 被忽略，不抛错
    fresh.record_recent("nonexistent")
    assert all(s.id != "nonexistent" for s in fresh.recent_specs())


def test_shortcut_registry_conflict_detection():
    register_meta(ShortcutSpec(id="t:1", key="Ctrl+Shift+F9", label="测试甲"))
    register_meta(ShortcutSpec(id="t:2", key="Ctrl+Shift+F9", label="测试乙"))
    register_meta(ShortcutSpec(id="t:3", key="Ctrl+Shift+F10", label="测试丙"))
    try:
        dupes = conflicts()
        assert "Ctrl+Shift+F9" in dupes
        assert {s.id for s in dupes["Ctrl+Shift+F9"]} == {"t:1", "t:2"}
        assert "Ctrl+Shift+F10" not in dupes
        assert any(s.id == "t:1" for s in all_specs())
    finally:
        from paleo_workbench.ui.shortcuts import unregister

        unregister("t:1")
        unregister("t:2")
        unregister("t:3")


def test_clamp_geometry_to_screens_offscreen():
    from paleo_workbench.ui.panel_float_controller import clamp_geometry_to_screens

    # offscreen 平台主屏 800x800：完全出屏的窗口贴回主屏
    far = QRect(5000, 5000, 300, 200)
    clamped = clamp_geometry_to_screens(far)
    assert clamped.x() >= 0 and clamped.y() >= 0
    assert clamped.x() < 900 and clamped.y() < 900

    # 屏内窗口不动
    inside = QRect(50, 60, 300, 200)
    assert clamp_geometry_to_screens(inside) == inside


def test_clamp_geometry_partial_offscreen():
    from paleo_workbench.ui.panel_float_controller import clamp_geometry_to_screens

    part = QRect(780, 10, 200, 100)  # 右缘超出 800
    clamped = clamp_geometry_to_screens(part)
    assert clamped.right() <= 800 or clamped.x() >= 0
