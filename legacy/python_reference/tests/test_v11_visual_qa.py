"""V11 视觉 QA 门禁（goal §20 场景清单）。

13 场景 ×（离屏渲染 + 结构检查全绿），沿用 V6–V10 门禁风格：

* 每场景 ``build_scenario`` 构建（真实面板本体 + 合成事实，无 QGIS 桥
  依赖——壳场景强制 fallback 画布，语义等同无桥环境）；
* ``widget.grab()`` 非空 pixmap、非零尺寸（像素 diff 本身非门禁，V5 D8）；
* ``run_scenario_checks`` 的结构检查全部通过（呈现 = 权威结论）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui import visual_qa_v11
from paleo_workbench.ui.visual_qa_v11 import V11_SCENARIOS

pytestmark = pytest.mark.usefixtures("qapp")


def _force_fallback_canvas(monkeypatch):
    """强制 fallback 画布（无桥环境语义；桥在位机器同样可跑）。"""

    def _no_bridge():
        raise RuntimeError("bridge disabled for V11 visual QA")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge
    )


@pytest.mark.parametrize("scenario", V11_SCENARIOS)
def test_v11_scenario_renders_and_passes_checks(qtbot, monkeypatch, scenario):
    if visual_qa_v11.scenario_needs_workstation_shell(scenario):
        _force_fallback_canvas(monkeypatch)
    widget = visual_qa_v11.build_scenario(scenario)
    qtbot.addWidget(widget)
    # 壳场景返回的是壳的子面板（如 command palette）：把顶层窗也交给
    # qtbot 托管，定时器/dock 随测试 teardown 释放。
    top_level = widget.window()
    if top_level is not None and top_level is not widget:
        qtbot.addWidget(top_level)

    # 渲染冒烟：非空 pixmap、非零尺寸。
    pixmap = widget.grab()
    assert not pixmap.isNull(), f"{scenario}: grab() 产出空 pixmap"
    assert pixmap.width() > 0 and pixmap.height() > 0, (
        f"{scenario}: grab() 尺寸 {pixmap.width()}x{pixmap.height()}"
    )

    # 结构检查（门禁）：注册非空且全部通过。
    results = visual_qa_v11.run_scenario_checks(scenario, widget)
    assert results, f"{scenario}: 无结构检查注册"
    failed = [r for r in results if not r.ok]
    assert not failed, (
        f"{scenario}: 结构检查失败 → {[r.name for r in failed]}: "
        f"{[r.detail for r in failed]}"
    )


def test_v11_scenario_registry_shape():
    """场景注册表形态：13 场景，构建/检查表覆盖一致。"""
    assert len(V11_SCENARIOS) == 13
    assert len(set(V11_SCENARIOS)) == len(V11_SCENARIOS)
    table = visual_qa_v11.v11_shot_table()
    assert set(table) == set(V11_SCENARIOS)
    assert all(callable(builder) for builder in table.values())


def test_v11_theme_matrix_axes_covered():
    """主题矩阵轴：light/dark × 1280×720 / 1920×1080 四组合齐全。"""
    assert visual_qa_v11.THEME_MATRIX_THEMES == ("light", "dark")
    assert visual_qa_v11.THEME_MATRIX_SIZES == ((1280, 720), (1920, 1080))
