"""V11 Goal §7「单一动作权威」契约测试（A1/A3 + 阶段面板禁用呈现）。

覆盖面：

* ToolAvailability 附加 severity/remediation 的不变量（enabled ⇒ 无元数据；
  severity 词表 fail-closed）与明确词族的标注（RAW/冻结角色门、阶段
  白名单、provider 只读、选择前提）；
* RAW/冻结/组锁措辞单源（evaluator 判词 = ``raw_layer_gate_reason()``
  输出；资产菜单与状态条源码不再含手写判词字面量——grep 式断言，
  同 test_integrity_guard 的源码检查风格）；
* 阶段面板动作行禁用呈现（flags/前景/tooltip + 点击 no-op）与
  ``evaluate_stage_commands`` 的工程/阶段/工具面判定序；
* 原生图层树（QgisLayerTreePanel）探针门禁：RAW 判词禁用编辑/修复
  菜单项 + 「不可用：{reason}」tooltip；无探针保持原行为；执行护栏
  拦截判词禁用的请求信号；两套图层面板在构造现场消费同一探针。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu

from paleo_workbench.mapping import tool_availability
from paleo_workbench.mapping.tool_availability import (
    ToolAvailability,
    evaluate_tool,
    frozen_layer_gate_reason,
    raw_layer_gate_reason,
    stage_lock_reason,
    stage_whitelist_reason,
)
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.ui.workstation.mapping_stage_panel import (
    MappingStagePanel,
    _CommandList,
    evaluate_stage_commands,
)
from paleo_workbench.ui.workstation.ui_context import UIContextSnapshot

_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "paleo_workbench"


# -- ToolAvailability 不变量与 severity/remediation 标注 -----------------------


def test_availability_invariants_hold_with_new_fields():
    # enabled ⇒ 无 reason 且无 severity/remediation（同 reason 不变量风格）。
    with pytest.raises(ValueError):
        ToolAvailability(tool_id="pan", enabled=True, severity="warning")
    with pytest.raises(ValueError):
        ToolAvailability(tool_id="pan", enabled=True, remediation="改用草稿")
    # invisible ⇒ not enabled（既有不变量）。
    with pytest.raises(ValueError):
        ToolAvailability(tool_id="pan", visible=False, enabled=True)
    ok = ToolAvailability(tool_id="pan", enabled=True)
    assert ok.severity is None and ok.remediation is None
    assert ok.to_dict()["severity"] is None


def test_severity_vocabulary_is_closed():
    with pytest.raises(ValueError):
        ToolAvailability(tool_id="pan", severity="fatal")
    for allowed in ("info", "warning", "critical"):
        assert ToolAvailability(tool_id="pan", severity=allowed).severity == allowed


def _raw_locked_ctx() -> ToolContext:
    return ToolContext(
        project_open=True, active_layer_id="doc-raw", active_layer_kind="polygon",
        edit_gate_open=False, raw_locked=True,
    )


def test_raw_role_gate_carries_warning_and_shared_wording():
    verdict = evaluate_tool("toggle_editing", _raw_locked_ctx())
    assert not verdict.enabled
    # 判词与共享措辞函数逐字一致（A3：跨表面可比较的单一判词）。
    assert verdict.disabled_reason == raw_layer_gate_reason()
    assert verdict.severity == "warning"
    assert verdict.remediation == "创建 DERIVED 草稿后编辑"
    # checked 重建路径不丢附加元数据。
    assert verdict.checked in (True, False)
    assert ToolAvailability(
        tool_id="toggle_editing", visible=True, enabled=False,
        checked=verdict.checked, disabled_reason=verdict.disabled_reason,
        severity=verdict.severity, remediation=verdict.remediation,
    ).severity == "warning"


def test_frozen_role_gate_uses_shared_wording():
    ctx = ToolContext(
        project_open=True, active_layer_id="doc-f", edit_gate_open=False,
        layer_frozen=True,
    )
    verdict = evaluate_tool("toggle_editing", ctx)
    assert verdict.disabled_reason == frozen_layer_gate_reason()
    assert verdict.severity == "warning"
    assert verdict.remediation == "另存草稿或解除冻结"


def test_stage_whitelist_gate_carries_warning():
    # map_product_assemble 的 qa 组全阶段可见 → 白名单门是实际 blocker。
    ctx = ToolContext(project_open=True, mapping_stage="facies_calibration")
    verdict = evaluate_tool("map_product_assemble", ctx)
    assert not verdict.enabled
    assert verdict.disabled_reason == stage_whitelist_reason(
        ("integrated_compilation",))
    assert verdict.severity == "warning"
    assert verdict.remediation is None


def test_selection_prereq_is_info_and_project_gate_unclassified():
    selection = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="line",
        editing=True,
    )
    verdict = evaluate_tool("delete_selected", selection)
    assert verdict.disabled_reason == "没有选中的要素"
    assert verdict.severity == "info"
    # 工程门禁不在标注词族内（保守 None——不猜）。
    project = evaluate_tool("toggle_editing", ToolContext(project_open=False))
    assert project.severity is None and project.remediation is None
    provider = evaluate_tool("toggle_editing", ToolContext(
        project_open=True, active_layer_id="L1", edit_gate_open=True,
        vector_writable=True, provider_writable=False, provider_name="ogr"))
    assert provider.severity == "warning"


# -- A3：措辞单源（grep 式源码断言 + 模块属性同源） -----------------------------


def test_raw_gate_wording_single_source_in_surfaces():
    asset_src = (
        _SOURCE_ROOT / "ui" / "pages" / "asset_context_menu.py"
    ).read_text(encoding="utf-8")
    assert "原始数据已锁定，不能直接编辑" not in asset_src
    assert "raw_layer_gate_reason" in asset_src

    bar_src = (_SOURCE_ROOT / "ui" / "map_status_bar.py").read_text(
        encoding="utf-8")
    assert "RAW/模型结果图层——不可直接编辑；复制为草稿后编辑" not in bar_src
    assert "当前结果已冻结/发布——不可编辑；另存草稿或解除冻结" not in bar_src
    assert "raw_layer_gate_reason" in bar_src
    assert "frozen_layer_gate_reason" in bar_src
    assert "stage_lock_reason" in bar_src


def test_asset_menu_and_evaluator_share_wording_module_attribute():
    from paleo_workbench.ui.pages import asset_context_menu

    # 同一函数对象（单一措辞真源），不是各抄一份字符串。
    assert asset_context_menu.raw_layer_gate_reason is raw_layer_gate_reason
    assert tool_availability.raw_layer_gate_reason is raw_layer_gate_reason


def test_status_bar_edit_chip_uses_shared_wording(qtbot):
    from paleo_workbench.ui.map_status_bar import MapStatusBar

    bar = MapStatusBar()
    qtbot.addWidget(bar)
    # chip 前缀/格式结构保持，判词句换共享措辞。
    bar.apply_context({"raw_locked": True, "layer_name": "初始相图"})
    assert bar.edit.text() == "RAW · 只读"
    assert bar.edit.toolTip() == raw_layer_gate_reason()
    bar.apply_context({"layer_frozen": True})
    assert bar.edit.text() == "已冻结"
    assert bar.edit.toolTip() == frozen_layer_gate_reason()
    bar.apply_context({"edit_gate_open": False, "edit_gate_reason": "证据组锁定"})
    assert bar.edit.text() == "锁定"
    assert bar.edit.toolTip() == stage_lock_reason("证据组锁定")


# -- 阶段面板：动作行禁用呈现 ---------------------------------------------------


def test_stage_command_list_availability_presentation(qtbot):
    from paleo_workbench.ui import style

    widget = _CommandList([("run_qa", "运行 QA"), ("select_evidence", "选择证据版本")])
    qtbot.addWidget(widget)
    item = widget.item(0)
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert item.toolTip() == "运行 QA"

    widget.set_action_availability({"run_qa": (False, "未打开工程")})
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert item.toolTip() == "不可用：未打开工程"
    assert item.foreground().color().name() == QColor(
        style.palette()["TEXT_DISABLED"]).name()
    # 未提及的动作保守放行（执行侧 re-gate 兜底）。
    assert widget.item(1).flags() & Qt.ItemFlag.ItemIsEnabled

    emitted: list[str] = []
    widget.action_requested.connect(emitted.append)
    widget._on_clicked(item)
    assert emitted == []  # 禁用行点击 no-op

    widget.set_action_availability({"run_qa": (True, None)})
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert item.toolTip() == "运行 QA"
    widget._on_clicked(item)
    assert emitted == ["run_qa"]


def test_stage_panel_threads_availability_to_current_page(qtbot):
    panel = MappingStagePanel()
    qtbot.addWidget(panel)
    panel.set_stage("integrated_compilation")
    page = panel.stack.currentWidget()
    item = page.actions.item(0)
    action_id = str(item.data(Qt.ItemDataRole.UserRole))
    panel.set_action_availability({action_id: (False, "未打开工程")})
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    panel.set_action_availability({action_id: (True, None)})
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled


# -- evaluate_stage_commands：与命令面板同判定序 --------------------------------


def test_evaluate_stage_commands_no_project_disables_all():
    snapshot = UIContextSnapshot()  # project_open=False, mapping_stage=None
    result = evaluate_stage_commands("constraint_factor", snapshot)
    from paleo_workbench.mapping_workspace.stage_vocabulary import (
        stage_context_actions,
    )

    assert set(result) == {a for a, _t in stage_context_actions("constraint_factor")}
    assert result and all(
        enabled is False and reason
        for enabled, reason in result.values()
    )
    assert result["open_factor_workbench"] == (False, "未打开工程")


def test_evaluate_stage_commands_unknown_stage_is_empty():
    assert evaluate_stage_commands("bogus_stage", UIContextSnapshot()) == {}
    assert evaluate_stage_commands("", UIContextSnapshot()) == {}


def test_evaluate_stage_commands_open_project_right_stage():
    snapshot = UIContextSnapshot(
        project_open=True, mapping_stage="integrated_compilation")
    result = evaluate_stage_commands("integrated_compilation", snapshot)
    assert result  # 阶段三动作全部有结论
    # 有工具面映射的动作（run_qa → qa_run）在工程/阶段就绪时放行。
    assert result["run_qa"] == (True, None)
    assert result["assemble_map_product"] == (True, None)
    # 无映射动作保守放行（执行侧 dispatcher re-gate）。
    assert result["select_evidence"] == (True, None)


def test_evaluate_stage_commands_wrong_stage_uses_whitelist_wording():
    snapshot = UIContextSnapshot(
        project_open=True, mapping_stage="constraint_factor")
    result = evaluate_stage_commands("integrated_compilation", snapshot)
    expected = stage_whitelist_reason(("integrated_compilation",))
    assert result["run_qa"] == (False, expected)
    assert result["select_evidence"] == (False, expected)


def test_evaluate_stage_commands_unknown_mapping_stage_fail_closed():
    snapshot = UIContextSnapshot(project_open=True)  # mapping_stage=None
    result = evaluate_stage_commands("integrated_compilation", snapshot)
    assert result["run_qa"] == (False, "当前编图阶段未知")


# -- 原生图层树（QgisLayerTreePanel）：探针门禁 --------------------------------


class _FakeLayer:
    def __init__(self, layer_id: str, metadata: dict | None = None):
        self.id = layer_id
        self.name = layer_id
        self.opacity = 1.0
        self.metadata = dict(metadata or {})


def _raw_locked_facts():
    from paleo_workbench.ui.workstation.tool_surface import LayerMenuFacts

    return LayerMenuFacts(
        toggle_editing=ToolAvailability(
            tool_id="toggle_editing", enabled=False,
            disabled_reason=raw_layer_gate_reason(), severity="warning",
        ),
        repair_geometry=ToolAvailability(
            tool_id="repair_geometry", enabled=False,
            disabled_reason="几何修复针对面图层",
        ),
        raw_protected=True,
    )


def _menu_with_native_entries() -> QMenu:
    menu = QMenu()
    menu.addAction("打开属性表")
    menu.addAction("开始/停止编辑")
    menu.addAction("修复无效几何…")
    menu.addAction("删除图层")
    return menu


def _find_action(menu: QMenu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


def test_native_tree_menu_gates_edit_actions_by_verdict(qtbot):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel(menu_probe=lambda doc: _raw_locked_facts())
    qtbot.addWidget(panel)
    panel._layers = [_FakeLayer("doc-a", {"editable": "true"})]
    menu = _menu_with_native_entries()
    panel._apply_menu_gating(menu, "doc-a")

    toggle = _find_action(menu, "开始/停止编辑")
    repair = _find_action(menu, "修复无效几何…")
    remove = _find_action(menu, "删除图层")
    table = _find_action(menu, "打开属性表")
    # 判词禁用：保持可见（动作仍在菜单）但 disabled + 判词 tooltip。
    assert not toggle.isEnabled()
    assert toggle.toolTip() == f"不可用：{raw_layer_gate_reason()}"
    assert not repair.isEnabled()
    assert repair.toolTip() == "不可用：几何修复针对面图层"
    # RAW 图层可删（与回退树菜单的出现语义一致——删除不是要素编辑）。
    assert remove.isEnabled()
    # 非门禁动作不受影响（Qt6 QAction 默认 tooltip = 文本，无判词前缀即可）。
    assert table.isEnabled()
    assert not table.toolTip().startswith("不可用：")


def test_native_tree_without_probe_keeps_behavior(qtbot):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel._layers = [_FakeLayer("doc-a", {"editable": "true"})]
    menu = _menu_with_native_entries()
    panel._apply_menu_gating(menu, "doc-a")
    for action in menu.actions():
        assert action.isEnabled()
        assert not action.toolTip().startswith("不可用：")

    # 请求信号照常外发（旧行为）。
    received: list[str] = []
    panel.toggle_editing_requested.connect(received.append)
    panel._on_tree_menu("toggle_editing", "doc-a")
    assert received == ["doc-a"]


def test_native_tree_execution_guard_blocks_disabled_verdict(qtbot):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel(menu_probe=lambda doc: _raw_locked_facts())
    qtbot.addWidget(panel)
    toggles: list[str] = []
    repairs: list[str] = []
    tables: list[str] = []
    panel.toggle_editing_requested.connect(toggles.append)
    panel.repair_layer_requested.connect(repairs.append)
    panel.attribute_table_requested.connect(tables.append)

    panel._on_tree_menu("toggle_editing", "doc-a")
    panel._on_tree_menu("repair", "doc-a")
    assert toggles == [] and repairs == []
    # 非门禁键不受执行护栏影响。
    panel._on_tree_menu("attribute_table", "doc-a")
    assert tables == ["doc-a"]


def test_native_tree_remove_button_follows_probe_facts(qtbot):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel(menu_probe=lambda doc: _raw_locked_facts())
    qtbot.addWidget(panel)
    # RAW 无 metadata 旗标（A1 的旧旗标缺口）：探针 facts 仍允许删除。
    panel._layers = [_FakeLayer("doc-raw")]
    panel._on_tree_selection("doc-raw")
    assert panel.remove_button.isEnabled()
    allowed, reason = panel._remove_gate("doc-raw")
    assert allowed and reason is None
    # 非编修/非 RAW：禁用并给出原因。
    from paleo_workbench.ui.workstation.tool_surface import LayerMenuFacts

    panel.set_layer_probes(menu_probe=lambda doc: LayerMenuFacts(raw_protected=False))
    allowed, reason = panel._remove_gate("doc-raw")
    assert not allowed and reason


def test_native_tree_constructor_probes_and_setter(qtbot):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    probe_calls: list[str] = []

    def probe(doc_id):
        probe_calls.append(str(doc_id))
        return _raw_locked_facts()

    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.set_layer_probes(menu_probe=probe)
    assert panel._menu_probe is probe
    menu = _menu_with_native_entries()
    panel._apply_menu_gating(menu, "doc-a")
    assert probe_calls == ["doc-a"]
    assert not _find_action(menu, "开始/停止编辑").isEnabled()


def test_both_layer_panels_consume_same_probes_at_construction():
    src = (
        _SOURCE_ROOT / "ui" / "workstation" / "composite_document.py"
    ).read_text(encoding="utf-8")
    # 原生树与回退树在构造现场注入同一对探针（A1：同一图层同一菜单态）。
    assert src.count("menu_probe=self.layer_menu_facts") == 2
    assert src.count("repair_probe=self._layer_repair_availability") == 2
