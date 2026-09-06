"""V6 §4：Command Palette 消费 UIContext——禁用命令可见原因、不可执行。"""
from __future__ import annotations

import pytest

from paleo_workbench.ui.app_shell import CommandPalette
from paleo_workbench.ui.command_registry import CommandSpec, command_registry
from paleo_workbench.ui.workstation.ui_context import UIContextSnapshot

pytestmark = pytest.mark.usefixtures("qapp")


def _register_fixture_commands() -> None:
    command_registry.clear(keep_core=False)
    command_registry.register(
        CommandSpec(
            id="v6test:phase2_only",
            label="物源线数字化",
            stages=("phase2",),
            callback=lambda: None,
        )
    )
    command_registry.register(
        CommandSpec(id="v6test:always", label="全图", callback=lambda: None)
    )


def test_palette_shows_disabled_command_with_reason(qtbot):
    _register_fixture_commands()
    palette = CommandPalette(
        None, navigate=lambda *_: None, context_provider=lambda: UIContextSnapshot(mapping_stage="phase1")
    )
    qtbot.addWidget(palette)
    palette.popup()
    labels = [
        palette.result_list.item(i).text()
        for i in range(palette.result_list.count())
    ]
    joined = "\n".join(labels)
    assert "物源线数字化" in joined  # 可发现：不隐藏
    assert "阶段" in joined  # 带禁用原因


def test_palette_blocks_activation_of_disabled_command(qtbot):
    _register_fixture_commands()
    fired: list[str] = []
    command_registry.register(
        CommandSpec(
            id="v6test:phase2_only",
            label="物源线数字化",
            stages=("phase2",),
            callback=lambda: fired.append("boom"),
        )
    )
    palette = CommandPalette(
        None,
        navigate=lambda *_: None,
        context_provider=lambda: UIContextSnapshot(mapping_stage="phase1"),
    )
    qtbot.addWidget(palette)
    palette.popup()
    for i in range(palette.result_list.count()):
        item = palette.result_list.item(i)
        if item.text().startswith("物源线"):
            palette._activate_item(item)
    assert fired == []  # 禁用命令不可执行


def test_palette_without_context_provider_keeps_legacy(qtbot):
    _register_fixture_commands()
    palette = CommandPalette(None, navigate=lambda *_: None)
    qtbot.addWidget(palette)
    palette.popup()
    labels = [
        palette.result_list.item(i).text()
        for i in range(palette.result_list.count())
    ]
    assert any(t.startswith("物源线数字化") for t in labels)
    assert not any("不可用" in t for t in labels)
    command_registry.clear(keep_core=False)
