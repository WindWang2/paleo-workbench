"""V6 shell P0 修复：showEvent 合并 / 面板全量可恢复 / 预设不毁几何。

对应 baseline audit：

* A-P0-1 ``WorkstationFrame.showEvent`` 定义两次，第一份（post-show
  布局恢复 + 响应式面板）为死代码 → 合并为单一 showEvent；
* A-P0-2 ``_PANEL_TOGGLE_TABLE`` 只覆盖 7/13 dock，关掉的 dock 无重开
  入口 → 表补全为全部 shell dock；
* A-P0-3 ``apply_layout_preset`` 无条件 ``dock_all_panels()`` 摧毁用户
  浮动几何 → 仅「恢复默认布局」重置几何，具名预设只切可见性。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QStackedWidget

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.shell import WorkstationFrame


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.append(
        ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las")
    )
    return project


def _frame(qtbot, tmp_path) -> WorkstationFrame:
    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    return frame


# --- A-P0-1: 单一 showEvent 同时做响应式面板 + 一次性 post-show 恢复 ----------


def test_show_event_runs_responsive_panels_and_post_show_restore(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    frame._post_show_restored = False
    calls: list[object] = []
    frame._apply_responsive_panels = lambda: calls.append("responsive")  # type: ignore[assignment]
    frame._schedule_restore = lambda ms: calls.append(("restore", ms))  # type: ignore[assignment]

    frame.showEvent(QShowEvent())

    assert "responsive" in calls
    assert ("restore", 50) in calls
    assert frame._post_show_restored is True
    # 只恢复一次（重复 show 不再排队 restore）。
    frame.showEvent(QShowEvent())
    assert calls.count(("restore", 50)) == 1


# --- A-P0-2: 每个 shell dock 都有重开入口 --------------------------------------


def test_every_shell_dock_has_toggle_reopen_path(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    all_docks = {id(d) for d in frame._shell_docks()}
    covered_docks = set()
    for attr, _label in frame._PANEL_TOGGLE_TABLE:
        dock = getattr(frame, attr, None)
        assert dock is not None, f"toggle 表引用了不存在的属性 {attr}"
        covered_docks.add(id(dock))
    missing = all_docks - covered_docks
    assert not missing, (
        "以下 dock 关闭后无菜单/palette 重开入口: "
        + ", ".join(
            d.objectName() or repr(d) for d in frame._shell_docks() if id(d) in missing
        )
    )


# --- A-P0-3: 具名预设保留几何；恢复默认才重置 ----------------------------------


def test_named_preset_preserves_floating_geometry(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    frame.well_dock.setFloating(True)
    # 具名预设（测井解释，会显示 well_dock）不得把浮动 dock 强行停靠。
    frame.apply_layout_preset("well_interpretation")
    assert frame.well_dock.isFloating() is True


def test_reset_default_layout_redocks_everything(qtbot, tmp_path):
    frame = _frame(qtbot, tmp_path)
    frame.well_dock.setFloating(True)
    frame._reset_default_layout()
    assert frame.well_dock.isFloating() is False
