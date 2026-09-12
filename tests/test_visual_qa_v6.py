"""V6 Phase 8：视觉 QA harness 扩展——新状态注册 / 语义检查 / 基线在位。

被测对象：

* ``paleo_workbench.ui.visual_qa_v6``：6 个新捕获状态的驱动 + 语义检查
  （harness 内非门禁；**本文件是门禁**——像素 diff 与语义检查的「报告
  供人工判读」策略不适用于这里的结构断言，decisions.md D8）。
* ``scripts/capture_workstation_screens.py`` / ``scripts/capture_ui_matrix.py``
  的注册与 --v6 矩阵模式。
* ``visual_qa/baseline-v6-matrix/``：新状态基线在位（不重生成既有 30 张）。

全部状态离屏可构造（offscreen 平台、合成工程、无 QGIS 桥——composite
回退画布是本套件环境的诚实现实，不是缺陷）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import visual_qa_v6
from paleo_workbench.ui.visual_qa_v6 import V6_STATES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
BASELINE_DIR = REPO_ROOT / "visual_qa" / "baseline-v6-matrix"

#: 基线矩阵组合（与 capture_ui_matrix --v6 一致：light 基准 × 2 密度 × 3 尺寸）。
_BASELINE_COMBOS = [
    (theme, density, size)
    for theme in ("light",)
    for density in ("compact", "comfortable")
    for size in ("1180x720", "1440x900", "1920x1080")
]

pytestmark = pytest.mark.usefixtures("qapp")


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _driven_window(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    window.show()
    return window


def _assert_all_checks_pass(state: str, window) -> None:
    results = visual_qa_v6.run_state_checks(state, window)
    assert results, f"{state}: 没有注册任何语义检查"
    failed = [r.name for r in results if not r.ok]
    assert not failed, f"{state}: 语义检查失败 → {failed}"


# --- 1. 新状态注册 -------------------------------------------------------------


def test_v6_states_have_shot_table_entries():
    """每个新状态都有 (工程工厂, 驱动) 注册项——与 V5 shots 注册形态一致。"""
    table = visual_qa_v6.v6_shot_table(lambda: None)
    assert tuple(sorted(table)) == tuple(sorted(V6_STATES))
    for state in V6_STATES:
        make_project, drive = table[state]
        assert callable(make_project), state
        assert callable(drive), state


def test_matrix_harness_lists_v6_states():
    """capture_ui_matrix --v6 的状态表与模块注册一致（不触碰既有 12 状态）。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import capture_ui_matrix
    finally:
        sys.path.remove(str(SCRIPTS_DIR))
    assert capture_ui_matrix.V6_STATES == list(V6_STATES)
    for state in capture_ui_matrix.CORE_STATES + capture_ui_matrix.FULL_STATES:
        assert state not in V6_STATES  # 扩展而非替代


def test_capture_shot_constructs_offscreen(tmp_path):
    """端到端证据：--shot 子进程真实构造 mapping_stage_phase2 并截图。

    覆盖注册合并（shots.update）、离屏构造、无 QGIS 桥回退、截图落盘与
    语义检查旁车 JSON（bridge-less 环境的诚实运行）。"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "capture_workstation_screens.py"),
            str(tmp_path),
            "--shot",
            "mapping_stage_phase2",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    png = tmp_path / "mapping_stage_phase2.png"
    assert png.exists() and png.stat().st_size > 0
    payload = json.loads(
        (tmp_path / "_checks" / "mapping_stage_phase2.json").read_text("utf-8"))
    assert payload["state_ok"] is True, payload


# --- 2. 语义检查（门禁断言；harness 内同项检查为非门禁记录） --------------------


@pytest.mark.parametrize("state", V6_STATES[:3])
def test_semantic_checks_mapping_stages(qtbot, tmp_path, state):
    window = _driven_window(qtbot, tmp_path)
    drive = visual_qa_v6.v6_shot_table(lambda: None)[state][1]
    drive(window)
    _assert_all_checks_pass(state, window)


def test_semantic_checks_command_palette_context(qtbot, tmp_path):
    from PySide6.QtCore import Qt

    from paleo_workbench.ui.command_registry import command_registry

    window = _driven_window(qtbot, tmp_path)
    visual_qa_v6.drive_command_palette_context(window)
    _assert_all_checks_pass("command_palette_context", window)

    # 生产缝：阶段动作已注册为阶段限定命令（palette 上下文态的数据源）。
    spec = command_registry.get("stage:constraint_factor:overlay_factor_results")
    assert spec is not None and spec.stages == ("constraint_factor",)
    # 禁用条目：文本含原因，且 item flag 真的不可激活。
    palette = window.app_shell.command_palette
    disabled = [
        (palette.result_list.item(row).text(),
         palette.result_list.item(row).flags())
        for row in range(palette.result_list.count())
        if not palette.result_list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled
    ]
    # V11：措辞断言对齐 V10 M10 的单一真源 stage_whitelist_reason
    # （「当前阶段不允许该操作（限 …）」——base 上该测试期望已过时）。
    assert disabled and any("当前阶段不允许该操作" in text for text, _ in disabled)


def test_semantic_checks_write_grant_dialog(qtbot, tmp_path):
    window = _driven_window(qtbot, tmp_path)
    visual_qa_v6.drive_write_grant_dialog(window)
    _assert_all_checks_pass("write_grant_dialog", window)


def test_semantic_checks_status_workbench_segment(qtbot, tmp_path):
    window = _driven_window(qtbot, tmp_path)
    visual_qa_v6.drive_status_workbench_segment(window)
    _assert_all_checks_pass("status_workbench_segment", window)
    text = window.app_shell.status_bar.workbench_label.text()
    # 后端态必须诚实出现且与画布权威一致（有桥报原生 / 无桥报回退）。
    native = window.app_shell.workstation.composite.uses_native_stack
    assert ("QGIS 原生" in text) if native else ("画布回退" in text)


# --- 3. 新状态基线在位（不重生成既有 30 张 v5 基线） ----------------------------


def test_baselines_exist_for_v6_states():
    files = list(BASELINE_DIR.glob("*.png")) if BASELINE_DIR.exists() else []
    assert files, f"缺少 V6 基线目录或为空：{BASELINE_DIR}"
    for state in V6_STATES:
        for theme, density, size in _BASELINE_COMBOS:
            name = f"{state}__{theme}__{density}__{size}.png"
            assert (BASELINE_DIR / name).exists(), name


def test_v5_baselines_untouched_by_v6_generation():
    """V6 基线生成不得触碰既有 v5 基线（30 张矩阵基线保持原样）。"""
    v5_dir = REPO_ROOT / "visual_qa" / "baseline-v5-matrix"
    pngs = sorted(p.name for p in v5_dir.glob("*.png"))
    assert len(pngs) == 30, f"v5 矩阵基线应为 30 张，实际 {len(pngs)}"
    assert all("__" in name for name in pngs)
