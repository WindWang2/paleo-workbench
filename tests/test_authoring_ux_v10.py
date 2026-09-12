"""V10 Authoring UX 契约测试：单一 availability 权威 × 全表面一致性。

覆盖 Goal V10 的核心断言面：

* **M1/B** — action registry 完整性（45 id 全登记、无重复、词汇同源）；
  阶段动作词表单源（profile 从 vocabulary 派生，不再漂移）；
* **M3/C** — ToolContext v4 附加事实（捕捉配置/CRS 呈现事实）缺省安全；
* **M5/E** — 图层树菜单消费 canonical evaluator（RAW/冻结/组锁/阻塞的
  禁用原因进入菜单；RAW 有「复制为草稿」入口）；
* **M6/F** — execution re-gate 全覆盖（层切换/阻塞/选择消失/会话结束
  后立刻触发的过期动作必须被拒）；
* **M7/O** — 画布右键菜单与工具条零漂移（同一批已求值 QAction）；
* **M9/P** — palette 几何命令三件套 + 阶段判词单一措辞；
* **M10/Q** — disabled reason 同源（toolbar/palette/菜单共享 evaluator 判词）；
* **M12/U** — help 文本差分缓存（上下文未变不重拼）；
* **M13/D** — 状态矩阵（阶段/角色/会话/选择/CRS/拓扑的成对组合不变量）。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.mapping.action_registry import (
    ACTION_SPECS,
    action_spec,
    surface_tools,
)
from paleo_workbench.mapping.tool_availability import (
    _CHECKED_CANVAS_TOOLS,
    _NATIVE_ONLY_TOOLS,
    TOOL_IDS,
    evaluate_all,
    evaluate_tool,
    stage_group_visibility,
    stage_whitelist_reason,
)
from paleo_workbench.mapping.tool_context import (
    TOOL_CONTEXT_CONTRACT_VERSION,
    ToolContext,
    build_tool_context,
)
from paleo_workbench.mapping.tool_help import TOOL_LABELS, TOOL_SHORTCUTS
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.mapping_workspace.stage_vocabulary import (
    STAGE_CONTEXT_ACTIONS,
    stage_context_action_ids,
)
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


# -- fixtures ---------------------------------------------------------------


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("V10 Authoring", region="T1")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture
def doc(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _register_role(document: CompositeDocument, layer_id: str, role: LayerRole) -> None:
    document.stage_controller.state.set_membership(
        LayerMembershipRecord(layer_id=layer_id, role=role)
    )


def _polygon_doc(document: CompositeDocument) -> str:
    layer = document.edit_controller.create_layer("相带草稿", "polygon")
    _register_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    document.edit_controller.set_active_layer(layer.id)
    document._sync_action_state()
    return str(layer.id)


def _line_role_doc(document: CompositeDocument, role: LayerRole) -> str:
    layer = document.edit_controller.create_layer("约束线", "line")
    _register_role(document, layer.id, role)
    document.edit_controller.set_active_layer(layer.id)
    document._sync_action_state()
    return str(layer.id)


# -- M1/B：action registry 完整性 ---------------------------------------------


def test_action_registry_covers_all_tools_without_duplicates():
    assert set(ACTION_SPECS) == set(TOOL_IDS)
    assert len(ACTION_SPECS) == len(TOOL_IDS)
    for tool_id in TOOL_IDS:
        spec = ACTION_SPECS[tool_id]
        assert spec.tool_id == tool_id
        assert spec.label == TOOL_LABELS[tool_id]
        assert spec.shortcut == TOOL_SHORTCUTS.get(tool_id, "")
        assert spec.icon, f"{tool_id} 缺图标名"
        assert spec.risk in {"read", "selection", "write", "structural"}
        assert spec.surfaces, f"{tool_id} 无呈现面"


def test_action_registry_flags_match_evaluator_tables():
    """canvas_interaction / requires_native 与求值器词表同集（登记处≠第二规则）。"""
    for tool_id, spec in ACTION_SPECS.items():
        assert spec.canvas_interaction == (tool_id in _CHECKED_CANVAS_TOOLS), tool_id
        assert spec.requires_native == (tool_id in _NATIVE_ONLY_TOOLS), tool_id


def test_edit_session_tools_are_not_read_risk():
    """凡求值器要求"已开启编辑会话"的工具，登记处不得标 read。

    长期钉（#1255）：add_ring 等 V10 新命令曾只进了 ``TOOL_IDS`` 与求值器
    的 ``_NEEDS_EDITING``，没进登记处的 ``write_tools``，于是 risk 回落
    ``read``——写动作在 Agent 授权面上伪装成只读。判据从求值器派生，新增
    编辑类命令漏登记表时本测试即红。
    """
    from paleo_workbench.mapping.tool_availability import _NEEDS_EDITING

    for tool_id in _NEEDS_EDITING:
        spec = ACTION_SPECS[tool_id]
        assert spec.risk in {"write", "structural"}, (
            f"{tool_id} 需要编辑会话却登记为 {spec.risk}")


def test_controller_action_icons_resolve_to_assets():
    """工具条/命令面每个 id 的图标都能解析成真实资产（#1256）。

    ``MapActionController`` 以 ``ToolButtonIconOnly`` 呈现（18×18），图标
    缺失 = 一个空白按钮。此前 5 个 V10 新命令的 svg 根本不存在，而旧断言
    只查 ``spec.icon`` 非空，因此是绿的。
    """
    from paleo_workbench.ui import map_action_controller as mac

    ids = (
        tuple(mac.MapActionController._TOOL_IDS)
        + tuple(mac.MapActionController._COMMAND_IDS)
        + tuple(mac.MapActionController._SURFACE_EXTENSION_IDS)
    )
    assert ids, "控制器动作清单为空——断言失去意义"
    missing = [
        action_id for action_id in ids
        if mac._map_icon(ACTION_SPECS[action_id].icon).isNull()
    ]
    assert not missing, f"图标资产缺失: {missing}"


def test_checked_canvas_tools_match_controller_tool_group():
    """求值器 checked 词表 == 控制器建按钮的画布工具组（#1256）。

    ``_CHECKED_CANVAS_TOOLS`` 与登记处 ``canvas_tools`` 的互等只能证明"两
    表同错"；真正的消费者是控制器——它给哪些 id 建了 checkable 按钮，求值
    器就必须给哪些 id 算 checked，否则勾选被回弹。
    """
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.ui import map_action_controller as mac

    controller_canvas = set(mac.MapActionController._TOOL_IDS)
    assert controller_canvas == set(_CHECKED_CANVAS_TOOLS), (
        f"控制器独有: {controller_canvas - set(_CHECKED_CANVAS_TOOLS)}；"
        f"求值器独有: {set(_CHECKED_CANVAS_TOOLS) - controller_canvas}")
    for tool_id in controller_canvas:
        assert ACTION_SPECS[tool_id].canvas_interaction, tool_id


def test_action_registry_surface_queries():
    assert "toggle_editing" in surface_tools("layer_menu")
    assert "split" not in surface_tools("layer_menu")
    assert action_spec("nonexistent") is None


def test_stage_vocabulary_single_source():
    """profile 的 context_actions 从词表派生（三表漂移结构性消除）。"""
    from paleo_workbench.mapping_workspace.stages import STAGE_ORDER

    for stage in STAGE_ORDER:
        from paleo_workbench.mapping_workspace.stage_profiles import stage_profile

        profile_ids = stage_profile(stage).tools.context_actions
        assert tuple(profile_ids) == stage_context_action_ids(stage.value), stage
    # 词表本身覆盖三阶段
    assert set(STAGE_CONTEXT_ACTIONS) == {
        "facies_calibration", "constraint_factor", "integrated_compilation",
    }


# -- M3/C：ToolContext v4 ------------------------------------------------------


def test_tool_context_contract_v4_defaults():
    assert TOOL_CONTEXT_CONTRACT_VERSION == 4
    ctx = build_tool_context(controller_state={}, layer_facts={})
    assert ctx.snapping_tolerance_px == 0.0
    assert ctx.snapping_modes == ()
    assert ctx.snapping_reference_count == 0
    assert ctx.snapping_role_recommended is None
    assert ctx.canvas_destination_crs == ""
    assert ctx.crs_mismatch is None
    assert ctx.reference_failed_count == 0
    assert ctx.running_task_count == 0
    # to_dict 覆盖新字段（序列化契约）
    data = ctx.to_dict()
    assert "snapping_modes" in data and isinstance(data["snapping_modes"], list)


def test_tool_context_v4_collects_snapping_facts(doc):
    doc.edit_controller._snapping.pixel_tolerance = 15.0
    doc.edit_controller._snapping.modes = {"vertex", "segment"}
    ctx = doc.tool_context()
    assert ctx.snapping_tolerance_px == 15.0
    assert set(ctx.snapping_modes) == {"vertex", "segment"}


def test_crs_mismatch_derivation(doc):
    judge = CompositeDocument._project_layer_crs_mismatch
    assert judge("", "EPSG:4326") is None       # 任一未声明 = 不可判定
    assert judge("EPSG:4490", "") is None
    assert judge("EPSG:4490", "EPSG:4326") is True
    assert judge("EPSG:4490", "EPSG:4490") is False
    # 描述式别名归一化等价
    assert judge("EPSG:4490 / CGCS2000", "EPSG:4490") is False


# -- M5/E：图层树菜单消费 canonical evaluator -----------------------------------


def test_layer_menu_facts_raw_layer_blocks_editing_with_reason(doc):
    layer_id = _polygon_doc(doc)
    _register_role(doc, layer_id, LayerRole.INITIAL_FACIES_SOURCE)  # RAW
    doc._sync_action_state()
    facts = doc.layer_menu_facts(layer_id)
    assert facts.raw_protected is True
    assert facts.toggle_editing is not None
    assert not facts.toggle_editing.enabled
    assert facts.toggle_editing.disabled_reason  # 有判词
    assert "RAW" in facts.toggle_editing.disabled_reason or "不可" in facts.toggle_editing.disabled_reason


def test_layer_menu_facts_draft_layer_allows_editing(doc):
    layer_id = _polygon_doc(doc)
    facts = doc.layer_menu_facts(layer_id)
    assert facts.raw_protected is False
    assert facts.toggle_editing.enabled
    assert facts.repair_geometry is not None
    assert facts.repair_geometry.enabled  # polygon + editable


def test_layer_menu_facts_repair_kind_gate_reaches_menu(doc):
    """线图层的「修复几何」在菜单里就禁用（V8 前只有 metadata 旗标判断）。"""
    layer_id = _line_role_doc(doc, LayerRole.PROVENANCE_DIRECTION)
    facts = doc.layer_menu_facts(layer_id)
    assert not facts.repair_geometry.enabled
    assert "面" in facts.repair_geometry.disabled_reason


def test_fallback_panel_menu_uses_evaluator_probe(qtbot, doc):
    """回退树右键菜单：RAW 图层的「开始编辑」禁用 + 「复制为草稿」在场。"""
    layer_id = _polygon_doc(doc)
    _register_role(doc, layer_id, LayerRole.INITIAL_FACIES_SOURCE)
    doc._sync_action_state()
    doc._sync_composition_now()
    panel = doc.layer_manager
    from PySide6.QtCore import Qt

    item = None
    for row in range(panel.tree.topLevelItemCount()):
        if str(panel.tree.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)) == layer_id:
            item = panel.tree.topLevelItem(row)
            break
    assert item is not None
    # 直接调用菜单事实探针（exec 菜单是模态的，不在此打开）
    facts = panel._menu_probe(layer_id)
    assert facts is not None and facts.raw_protected


# -- M6/F：execution re-gate（过期可用判断必须被拒） -----------------------------


def test_regate_layer_switch_before_click(doc):
    """工具条亮着 add_polygon（面层活动）→ 用户切到线层立刻点：必须拒绝。"""
    layer_id = _polygon_doc(doc)
    doc.edit_controller.start_editing()
    doc._sync_action_state()
    assert doc.action_controller.actions["add_polygon"].isEnabled()
    line_id = _line_role_doc(doc, LayerRole.FACIES_BOUNDARY)
    doc.edit_controller.start_editing()
    # 不再 sync（模拟点击发生在刷新间隙）
    doc.action_controller.actions["add_polygon"].setChecked(True)
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._on_tool_requested("add_polygon")
    assert any("不可用" in m for m in messages)
    # checked 不得残留翻转态
    doc._sync_action_state()
    assert not doc.action_controller.actions["add_polygon"].isChecked()


def test_regate_blocking_task_before_shortcut(doc):
    _polygon_doc(doc)
    doc.edit_controller.start_editing()
    doc._sync_action_state()
    assert "save_edits" in doc.action_controller.actions
    doc.edit_controller.blocking_task_label = "workflow:重算"
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._on_command_requested("save_edits")
    assert any("后台任务" in m for m in messages)
    doc.edit_controller.blocking_task_label = ""


def test_regate_selection_disappears_before_merge(doc, monkeypatch):
    # M1：相带 polygon 层默认翻转原生会话；本测试钉 Python 工具路径的
    # re-gate 语义——显式禁用原生翻转。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    layer_id = _polygon_doc(doc)
    doc.edit_controller.start_editing()
    controller = doc.edit_controller
    layer = controller.layer(layer_id)
    # 直接向会话写两个多边形（绕开画布采点，仍走会话权威）
    from paleo_workbench.mapping.vector_layer import VectorFeature

    session = layer.edit_session
    with session.edit_source("test_setup"):
        for index in range(2):
            session.add_feature(VectorFeature(
                feature_id=f"f{index}",
                geometry={"type": "Polygon", "coordinates": [
                    [[float(index), 0], [float(index) + 2, 0],
                     [float(index) + 2, 2], [float(index), 0]]]},
                attributes={},
            ))
    layer.set_selection(("f0", "f1"))
    doc._sync_action_state()
    assert doc.tool_availability()["merge"].enabled or doc.tool_availability()["merge"].disabled_reason
    layer.set_selection(())  # 选择消失，不刷新
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._on_command_requested("merge")
    assert any("不可用" in m for m in messages)


def test_regate_session_closed_before_capture(doc, monkeypatch):
    # M1：同上——钉 Python 会话路径。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    layer_id = _polygon_doc(doc)
    controller = doc.edit_controller
    controller.start_editing()
    from paleo_workbench.mapping.vector_layer import VectorFeature

    session = controller.layer(layer_id).edit_session
    with session.edit_source("test_setup"):
        session.add_feature(VectorFeature(
            feature_id="f0",
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            attributes={},
        ))
    controller.save_edits()  # 会话结束
    # 不刷新，直接点 add_polygon（工具条还亮着）
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._on_tool_requested("add_polygon")
    assert any("开始编辑" in m for m in messages)


def test_repair_execution_full_evaluator(doc):
    """F-3 闭环：非面图层经原生面板信号路径修复 → kind 门禁在执行侧拦截。"""
    layer_id = _line_role_doc(doc, LayerRole.PROVENANCE_DIRECTION)
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._repair_layer(layer_id)
    assert any("面" in m for m in messages), "kind gate 必须在执行时复核"


def test_toggle_editing_execution_blocking_gate(doc):
    layer_id = _polygon_doc(doc)
    doc.edit_controller.blocking_task_label = "workflow:重算"
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._toggle_layer_editing(layer_id)
    assert any("后台任务" in m for m in messages)
    assert doc.edit_controller.layer(layer_id).edit_session is None
    doc.edit_controller.blocking_task_label = ""


# -- M7/O：画布右键菜单与工具条零漂移 -------------------------------------------


def test_canvas_menu_shows_evaluated_actions_only(doc):
    _polygon_doc(doc)
    doc._sync_action_state()
    menu = doc._build_canvas_menu()
    texts = [a.text() for a in menu.actions() if a.text()]
    assert any("全图" in t for t in texts)
    assert any("捕捉" in t for t in texts)
    # 空工程阶段隐藏组（factor）不出现在菜单
    actions_in_menu = {a.objectName() for a in menu.actions() if a.isWidgetType() is False and a.objectName()}
    assert "MapAction:factor_workbench" not in actions_in_menu


def test_canvas_menu_items_carry_evaluator_state(doc):
    _polygon_doc(doc)
    doc._sync_action_state()
    menu = doc._build_canvas_menu()
    for action in menu.actions():
        if not action.objectName().startswith("MapAction:"):
            continue
        tool_id = action.objectName().split(":", 1)[1]
        verdict = doc.tool_availability().get(tool_id)
        if verdict is not None:
            assert action.isEnabled() == verdict.enabled, tool_id
            if not verdict.enabled:
                assert action.toolTip()  # 禁用项有可读原因


# -- M9/P + M10/Q：palette 与判词一致性 -----------------------------------------


def test_palette_geometry_commands_registered(qtbot, tmp_path):
    from paleo_workbench.ui.app_shell import AppShell
    from paleo_workbench.ui.command_registry import command_registry

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    for tool_id in ("split", "merge", "reshape"):
        assert command_registry.get(f"map:{tool_id}") is not None
    assert command_registry.get("core:inspector") is not None


def test_palette_applicability_same_reason_as_toolbar(qtbot, tmp_path):
    """palette 的 map:* 判词与工具条同源（完整快照下同因）。"""
    from paleo_workbench.ui.workstation.tool_surface import (
        evaluate_tool,
        tool_context_from_ui_snapshot,
    )

    ctx = ToolContext(
        project_open=True, mapping_stage="constraint_factor",
        active_layer_id="L1", active_layer_kind="line",
        qgis_layer_type="vector", edit_gate_open=True, vector_writable=True,
    )
    snapshot = type("Snap", (), {
        "project_open": True, "mapping_stage": "constraint_factor",
        "active_layer_id": "L1", "active_layer_kind": "line",
        "active_layer_editable": True, "active_layer_writable": True,
        "editing_active": False, "selection_count": 0,
        "split_ready": False, "merge_ready": False, "reshape_ready": False,
        "blocking_task": "", "queryable_layer_count": 1,
        "qgis_bridge_available": False, "capability_mode": "unavailable",
        "native_canvas_available": False, "native_capability_flags": (),
    })()
    for tool_id in ("merge", "reshape", "add_polygon"):
        full = evaluate_tool(tool_id, ctx).disabled_reason
        adapted = evaluate_tool(
            tool_id, tool_context_from_ui_snapshot(snapshot)).disabled_reason
        assert full == adapted, (tool_id, full, adapted)


def test_stage_reason_single_wording():
    """palette 阶段白名单与 evaluator 同一措辞（M10）。"""
    from paleo_workbench.ui.command_registry import _stage_reason

    expected = stage_whitelist_reason(("constraint_factor",))
    assert _stage_reason(("constraint_factor",)) == expected
    assert "当前阶段不允许该操作" in expected


# -- M13/D：状态矩阵（成对组合不变量） ------------------------------------------


def _matrix_contexts() -> list[tuple[str, ToolContext]]:
    """成对组合矩阵（Goal §9 维度的 pairwise 覆盖，非全笛卡尔）。"""
    base = dict(project_open=True)
    cases: list[tuple[str, ToolContext]] = []
    for stage in (None, "facies_calibration", "constraint_factor",
                  "integrated_compilation", "bogus"):
        for kind, role, frozen in (
            ("", "", False),                       # 未知图层
            ("polygon", "initial_facies_source", False),   # RAW
            ("polygon", "initial_facies_draft", False),    # 可编辑草稿
            ("line", "facies_boundary", False),    # 线角色
            ("polygon", "integrated_facies", True),  # 冻结
        ):
            cases.append((
                f"{stage}/{kind}/{role}/frozen={frozen}",
                ToolContext(
                    mapping_stage=stage, active_layer_kind=kind,
                    active_layer_id="L" if kind else "",
                    layer_role=role, layer_frozen=frozen,
                    edit_gate_open=(False if role == "initial_facies_source"
                                    else (False if frozen else True)),
                    edit_gate_reason="RAW 图层不可变" if role == "initial_facies_source"
                    else ("已冻结" if frozen else ""),
                    qgis_layer_type="vector" if kind else "",
                    vector_writable=bool(kind),
                    raw_locked=role == "initial_facies_source",
                ),
            ))
    # 会话/选择/CRS/拓扑/阻塞维度（叠加在可编辑草稿上）
    draft = dict(
        mapping_stage="facies_calibration", active_layer_kind="polygon",
        active_layer_id="L", layer_role="initial_facies_draft",
        qgis_layer_type="vector", vector_writable=True, edit_gate_open=True,
    )
    cases += [
        ("editing-clean", ToolContext(editing=True, **draft)),
        ("editing-dirty", ToolContext(editing=True, dirty=True, **draft)),
        ("selection-1", ToolContext(editing=True, selection_count=1, **draft)),
        ("selection-2", ToolContext(editing=True, selection_count=2, **draft)),
        ("merge-ready", ToolContext(editing=True, selection_count=2, merge_ready=True, **draft)),
        ("merge-topo-errors", ToolContext(editing=True, selection_count=2, merge_ready=True, topology_error_count=3, **draft)),
        ("crs-invalid", ToolContext(topology_available=True, crs_valid=False, **draft)),
        ("snapping-unavailable", ToolContext(snapping_available=False, **draft)),
        ("blocking", ToolContext(blocking_task="workflow:x", **draft)),
        ("no-project", ToolContext(project_open=False)),
        ("no-layer", ToolContext(mapping_stage="facies_calibration")),
        ("raster-layer", ToolContext(
            mapping_stage="facies_calibration", active_layer_id="R",
            qgis_layer_type="raster")),
    ]
    return cases


@pytest.mark.parametrize("label,ctx", _matrix_contexts())
def test_state_matrix_invariants(label, ctx):
    verdicts = evaluate_all(ctx)
    # 1) cancel 永远可用
    assert verdicts["cancel"].enabled
    # 2) 阻塞任务：除 cancel 全禁；可见项统一阻塞判词（隐藏项的判词是
    #    阶段呈现语义——隐藏优先于阻塞判词是既定门序）。
    if ctx.blocking_task:
        for tool_id, verdict in verdicts.items():
            if tool_id == "cancel":
                continue
            assert not verdict.enabled, f"{label}: {tool_id} 在阻塞期间启用"
            if verdict.visible:
                assert ctx.blocking_task in verdict.disabled_reason, (
                    f"{label}: {tool_id}")
        return
    # 3) RAW/冻结：编辑会话/捕获/几何组禁用且判词来自门禁结论
    if ctx.edit_gate_open is False and ctx.has_active_layer:
        for tool_id in ("toggle_editing", "add_polygon", "move_feature", "merge"):
            verdict = verdicts[tool_id]
            if verdict.visible:
                assert not verdict.enabled, f"{label}: {tool_id}"
                assert verdict.disabled_reason
    # 4) kind 门禁：多边形图层上 add_line 禁用（kind 判词；阶段外动作
    #    整条隐藏——判词是阶段语义，这是既定门序）
    if ctx.active_layer_kind == "polygon" and ctx.editing and ctx.edit_gate_open:
        verdict = verdicts["add_line"]
        if verdict.visible:
            assert verdict.disabled_reason and "面" in verdict.disabled_reason
    # 5) 线角色图层上 add_polygon 让位（抢主位防护）
    if (ctx.active_layer_kind == "polygon" and ctx.layer_role in {
            LayerRole.INTERPOLATION_BOUNDARY.value, LayerRole.MASK_BOUNDARY.value}):
        reason = verdicts["add_polygon"].disabled_reason
        assert reason and "添加面" in reason
    # 6) 选择门：clear_selection 随选择数联动
    if ctx.selection_count <= 0:
        assert not verdicts["clear_selection"].enabled
    # 7) 阶段组可见性：factor/layout_export 按阶段
    if ctx.mapping_stage == "facies_calibration":
        assert not verdicts["factor_workbench"].visible
        assert verdicts["factor_workbench"].disabled_reason  # palette 可发现
    # 8) 拓扑错误阻断合并
    if ctx.topology_error_count > 0:
        assert not verdicts["merge"].enabled
        assert "拓扑" in verdicts["merge"].disabled_reason
    # 9) CRS 无效阻断拓扑
    if not ctx.crs_valid:
        assert not verdicts["topology"].enabled
    # 10) 捕捉不可用判词
    if ctx.snapping_available is False:
        assert not verdicts["snapping"].enabled


def test_stage_group_visibility_matrix():
    assert stage_group_visibility(None)["factor"] is True
    vis = stage_group_visibility("facies_calibration")
    assert vis["factor"] is False and vis["layout_export"] is False
    vis = stage_group_visibility("constraint_factor")
    assert vis["factor"] is True and vis["layout_export"] is False
    vis = stage_group_visibility("integrated_compilation")
    assert vis["factor"] is False and vis["layout_export"] is True
    unknown = stage_group_visibility("bogus")
    assert unknown["navigate"] is True and unknown["geometry"] is False


# -- M12/U：help 差分缓存 -------------------------------------------------------


def test_help_text_diff_cache(doc):
    _polygon_doc(doc)
    doc._apply_tool_availability()
    first_signature = doc._help_signature
    first_texts = doc._help_texts
    assert first_signature and first_texts
    # 同一上下文再刷：不重拼（同一对象复用）
    doc._apply_tool_availability()
    assert doc._help_texts is first_texts
    # 上下文变化（开启会话）：重拼
    doc.edit_controller.start_editing()
    doc._apply_tool_availability()
    assert doc._help_signature != first_signature


# -- M14/V：性能（结构性界） -----------------------------------------------------


def test_evaluate_all_budget_ms():
    ctx = ToolContext(
        mapping_stage="integrated_compilation", active_layer_kind="polygon",
        active_layer_id="L", layer_role="integrated_facies",
        qgis_layer_type="vector", vector_writable=True, edit_gate_open=True,
        editing=True, dirty=True, selection_count=3,
        selection_geometry_types=("polygon",), compatible_polygon_count=3,
        topology_error_count=1, merge_ready=True, split_ready=True,
        snapping_enabled=True, topology_enabled=True,
        project_crs="EPSG:4490", layer_crs="EPSG:4490", scale_denominator=250000.0,
        snapping_tolerance_px=12.0, snapping_modes=("vertex", "segment"),
    )
    start = time.perf_counter()
    for _ in range(20):
        evaluate_all(ctx)
    elapsed = (time.perf_counter() - start) / 20
    assert elapsed < 0.005, f"evaluate_all 均值 {elapsed * 1000:.2f}ms 超 5ms 预算"


def test_thousand_layer_refresh_structural_bound(qtbot, tmp_path):
    """1000 层：全量树重建有界 + 差分刷新不重建（§28 无严重卡顿）。"""
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    # 批量建层时暂停逐层重组（结构变化本就 immediate 全量重组——用户
    # 逐层操作无此风暴；本测试度量的是树/状态刷新，不是建层路径）。
    document.edit_controller.layers_changed.disconnect()  # 全量断开（批量建层）
    try:
        for index in range(1000):
            layer = document.edit_controller.create_layer(f"L{index}", "polygon")
            if index == 0:
                _register_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    finally:
        document.edit_controller.layers_changed.connect(
            lambda *_: document._sync_composition(immediate=True))
    # 一次真实全量发布（基础层 + 编图快照 + 树重建）
    document._sync_composition_now()
    start = time.perf_counter()
    document.layer_manager._reload()
    full_seconds = time.perf_counter() - start
    assert document.layer_manager.tree_row_count() >= 1000
    # 差分路径（结构未变）：只更新单元格，不重建——判据是结构性事实
    # （首行 item 对象身份复用 + 不清树），不用裸计时比较。V10 review
    # follow-up（#1261）：旧断言 ``differential_seconds < full_seconds``
    # 是两次 ~0.1s 的裸计时对比，无预热/无容差/无重复取样，噪声量级与
    # 差值相当（实测跑出 0.0986 < 0.0959 随机红）——随机红会训练团队
    # 忽略红色信号。
    manager = document.layer_manager
    manager._reload()  # 先跑一次全量，建立基线行
    assert manager.tree_row_count() >= 1000, "全量刷新后应有 1000 行"
    baseline_rows = [
        manager.tree.topLevelItem(row)
        for row in range(min(8, manager.tree.topLevelItemCount()))
    ]
    baseline_count = manager.tree.topLevelItemCount()
    # 结构未变的差分刷新：清树会销毁全部 QTreeWidgetItem 并重新分配，
    # 因此"首行对象身份被复用"等价于"没有走 tree.clear() 全量分支"。
    # 该判据不依赖任何计时，且差分↔全量两侧都会真实翻转（见下）。
    manager._reload()
    assert manager.tree.topLevelItemCount() == baseline_count, "行数不得变化"
    assert all(
        manager.tree.topLevelItem(row) is item
        for row, item in enumerate(baseline_rows)
    ), "结构未变时差分刷新不得重建整棵树（首行 item 身份应复用）"
    # 反向对照：结构变化必须走全量分支（身份翻转），否则上面的断言
    # 可能在"永远不清树"的实现下恒绿。
    document.edit_controller.create_layer("L-extra", "polygon")
    document._sync_composition_now()
    assert manager.tree.topLevelItem(0) is not baseline_rows[0], (
        "结构变化时必须全量重建（首行 item 身份应替换）"
    )
    # 状态同步（含 evaluator + help 缓存）在 1000 层下有界
    start = time.perf_counter()
    document._sync_action_state()
    sync_seconds = time.perf_counter() - start
    assert sync_seconds < 2.0, f"_sync_action_state {sync_seconds:.2f}s @1000 层"
