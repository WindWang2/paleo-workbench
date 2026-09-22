"""Review round 1/2 修复的回归钉子。

* P0：shell → panel_float_controller 模块级导入闭合了导入环
  （standalone 收集 test_attribute_table_differential 曾 ERROR）——
  现为函数内导入；钉 standalone 导入顺序不回归。
* P2：``import_layer_features`` 是可信导入通道（绕过用户编辑门禁是
  设计语义）——生产调用方必须只有领域建稿（stage_actions）。
* P2：阶段限定命令在 mapping_stage 未知时 fail-closed。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from paleo_workbench.ui.command_registry import (
    CommandRegistry,
    CommandSpec,
)
from paleo_workbench.ui.workstation.ui_context import UIContextSnapshot

REPO = Path(__file__).resolve().parents[1]


def test_panel_float_controller_imports_standalone():
    """P0 回归：叶子模块必须可独立导入（不经 workstation 包先导入）。"""
    code = (
        "from paleo_workbench.ui.panel_float_controller import "
        "clamp_geometry_to_screens; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO),
        env={"QT_QPA_PLATFORM": "offscreen", "PATH": ""},
    )
    # PATH 清空可能影响 DLL 查找；失败时按原环境重试一次再判定。
    if result.returncode != 0:
        import os

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO),
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_import_layer_features_production_callers_are_domain_only():
    """可信导入通道只允许领域建稿调用（源码扫描钉子）。"""
    allowed = {"paleo_workbench/ui/workstation/stage_actions.py"}
    offenders: list[str] = []
    for path in (REPO / "paleo_workbench").rglob("*.py"):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "import_layer_features" in source and rel not in allowed:
            # 定义处与测试不在 paleo_workbench/ 内，命中即违规。
            if "def import_layer_features" not in source:
                offenders.append(rel)
    assert offenders == [], f"import_layer_features 出现在非领域文件: {offenders}"


def test_stage_scoped_command_fails_closed_on_unknown_stage():
    registry = CommandRegistry()
    registry.register(
        CommandSpec(id="map:x", label="X", stages=("phase2",))
    )
    ctx = UIContextSnapshot(mapping_stage=None)  # provider 故障/无工程
    avail = registry.evaluate("map:x", ctx)
    assert avail.enabled is False
    assert "未知" in avail.reason
