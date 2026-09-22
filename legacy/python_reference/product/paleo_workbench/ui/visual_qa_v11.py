"""V11 视觉 QA 场景集（goal §20 场景清单 / §21 结构性能）。

沿用 V6–V10 血统（续篇，非替代），但形态适配 V11 的验证重点：

* V6–V10 的状态 = **驱动函数**（在完整工作站窗口上编排业务事实）；
* V11 的场景 = **构建函数**（``build_<scenario>() -> QWidget``，离屏直接
  可渲染、可 ``grab()``），外加结构检查（``run_scenario_checks``，门禁
  断言钉在 ``tests/test_v11_visual_qa.py``）。每个场景尽量用**真实面板
  本体**（DataPage / TaskPanelBase / WorkstationInspector / TaskCenter /
  MappingStageBar+Panel / SeismicContextToolbar / CommandPalette），只注入
  合成事实，不 mock 呈现层。

场景覆盖 goal §20 的关键面：

1. 首次打开（空工程壳态：检查器空态 + 任务中心空态）；
2. 数据管理面（资产表 + 检查器选中资产——无目录绑定时的纯工程口径）；
3. 井工作流任务面板（TaskPanelBase：pending/running/complete 三态经
   state_language 任务词表渲染）；
4. 地震上下文工具条（survey/属性/显示模式/体维度定义态）；
5. 阶段条 ×3（Phase 1/2/3 各一景，条 + 面板同屏）；
6. 检查器版本 / Run payload（WorkstationInspector.show_payload 的 V11
   新 kind）；
7. 任务中心（OperationRegistry 在途 + 终态带结果标签，attach_registry）；
8. 命令面板（禁用命令带原因 + 编图工具 tooltip 全量解释）；
9. 空 / 加载 / 警示徽章行合成面（PwbEmptyState / PwbLoadingState /
   PwbBadge warning 行）；
10. 主题矩阵冒烟（场景 5 在 light/dark × 1280×720 / 1920×1080 渲染
    非空——主题经 theme_manager.set_theme 切换）。

像素 diff 仍非门禁（V5 D8 政策）；本模块只保证场景可离屏渲染 + 结构
检查可断言。无 QGIS 桥依赖：需要工作站壳的场景走 AppShell（构造
fallback 画布；桥在位机器同样可跑——测试侧可用
``scenario_needs_workstation_shell`` 决定是否强制 fallback），其余场景
全部是独立面板。
"""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from paleo_workbench.ui.visual_qa_v6 import CheckResult, _check, _settle

#: 场景清单（名字即检查键；截图 harness 可按名字渲染落盘）。
V11_SCENARIOS: tuple[str, ...] = (
    "first_open_empty_shell",
    "data_manager_surface",
    "well_task_workflow_panel",
    "seismic_context_surface",
    "stage_bar_phase1",
    "stage_bar_phase2",
    "stage_bar_phase3",
    "inspector_version_payload",
    "inspector_run_payload",
    "task_center_operations",
    "command_palette_disabled_reason",
    "error_empty_states_composite",
    "theme_matrix_smoke",
)

#: 主题矩阵冒烟的组合轴（场景 10）。
THEME_MATRIX_THEMES: tuple[str, ...] = ("light", "dark")
THEME_MATRIX_SIZES: tuple[tuple[int, int], ...] = ((1280, 720), (1920, 1080))

#: 命令面板场景的阶段过滤词（命中阶段 ② 专属动作；当前在阶段 ① →
#: 禁用 + 原因可见——与 V6 ``PALETTE_CONTEXT_FILTER`` 同源）。
PALETTE_STAGE_FILTER = "单因素"
#: 命令面板场景的编图工具过滤词（surface 工具组；tooltip 挂 action_help
#: 全量解释，含「前置条件：」行）。
PALETTE_TOOL_FILTER = "开始编辑"


# -- 场景构建 -------------------------------------------------------------------


def build_first_open_empty_shell():
    """场景 1：首次打开——空工程壳（无井/无资源/无任务）。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.app_shell import AppShell

    project = ProjectDocument.new("V11 QA · 首次打开")
    shell = AppShell(project=project)
    shell.resize(1600, 900)
    shell.show()
    _settle(250)
    return shell


def build_data_manager_surface():
    """场景 2：数据管理面——资产表多类型行 + 检查器选中资产。

    无目录绑定（纯 ``project.resources``）的离屏口径：足以断言表面结构
    （行数、选中呈现、概要行）。目录富化路径由 governance 测试覆盖。
    """
    from paleo_workbench.project.models import ProjectDocument, ResourceItem
    from paleo_workbench.ui.pages.data_page import DataPage

    project = ProjectDocument.new("V11 QA · 数据管理")
    project.resources.extend(
        [
            ResourceItem(
                name="A12.las", path="wells/A12.las", type="well_log", format="las"
            ),
            ResourceItem(
                name="HZ26.segy",
                path="seismic/HZ26.segy",
                type="seismic",
                format="segy",
            ),
            ResourceItem(
                name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"
            ),
            ResourceItem(
                name="facies.geojson",
                path="maps/facies.geojson",
                type="vector",
                format="geojson",
            ),
            ResourceItem(
                name="砂地比.csv",
                path="factors/砂地比.csv",
                type="tabular",
                format="csv",
            ),
        ]
    )
    page = DataPage(project=project)
    page.resize(1500, 950)
    page._refresh()
    selected = project.resources[0]
    page._set_selected_asset(selected)
    page._update_inspector(selected)
    _settle(100)
    return page


def build_well_task_workflow_panel():
    """场景 3：井工作流任务面板——pending / running / complete 三态同屏。"""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel

    tasks = [
        SimpleNamespace(
            id="pred-003",
            name="D63 砂地比预测",
            status="pending",
            adapter_kind="demo",
            probability_summary=None,
            review_areas=[],
        ),
        SimpleNamespace(
            id="pred-002",
            name="T1 岩相预测",
            status="running",
            adapter_kind="xgboost",
            probability_summary={"mean_probability": 0.72},
            review_areas=[{"id": "a"}, {"id": "b"}],
        ),
        SimpleNamespace(
            id="pred-001",
            name="ZJ2 孔隙度预测",
            status="complete",
            adapter_kind="xgboost",
            probability_summary={"mean_probability": 0.81},
            review_areas=[],
        ),
    ]
    panel = PredictionTaskPanel()
    # selected_index=1：用户选中运行中任务（active_prediction_task 取末位，
    # 显式选择更贴近真实工作流）。
    panel.update_state(tasks, selected_index=1)
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.addWidget(panel, 1)
    container.resize(420, 560)
    container._v11_task_panel = panel
    return container


def build_seismic_context_surface():
    """场景 4：地震上下文工具条——survey 选中 + 属性/模式/体维度定义态。"""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar

    task = SimpleNamespace(name="振幅属性提取 · HZ26")
    toolbar = SeismicContextToolbar()
    toolbar.seismic_source_combo.addItem("HZ26_3D_full.sgy", "survey-1")
    toolbar.seismic_source_combo.setCurrentIndex(0)
    toolbar.set_context(
        task,
        horizon="D63",
        attribute="RMS振幅",
        display_mode="wiggle",
        volume_shape=(301, 401, 1201),
        mock_nature="演示（非科学预测）",
    )
    toolbar.set_status("运行中 · 第 4/9 属性")

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 8, 8, 8)
    caption = QLabel("地震上下文面（V11 QA 场景）")
    caption.setObjectName("WorkFieldLabel")
    layout.addWidget(caption)
    layout.addWidget(toolbar)
    layout.addStretch(1)
    container.resize(1180, 120)
    return container


def _stage_surface(stage_value: str):
    """阶段条 + 阶段面板同屏（场景 5 的公共构造）。"""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from paleo_workbench.ui.workstation.mapping_stage_bar import MappingStageBar
    from paleo_workbench.ui.workstation.mapping_stage_panel import MappingStagePanel

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    bar = MappingStageBar(container)
    bar.set_horizon_state("D63", ["T1", "D63", "M10"])
    bar.set_current_stage(stage_value)
    panel = MappingStagePanel(container)
    panel.set_stage(stage_value)
    layout.addWidget(bar)
    layout.addWidget(panel, 1)
    container.resize(420, 720)
    container._v11_stage_value = stage_value
    container._v11_stage_bar = bar
    container._v11_stage_panel = panel
    return container


def build_stage_bar_phase1():
    """场景 5a：阶段①（智能预测 / 相图标定）阶段条 + 阶段面板。"""
    from paleo_workbench.mapping_workspace.stages import MappingStage

    return _stage_surface(MappingStage.FACIES_CALIBRATION.value)


def build_stage_bar_phase2():
    """场景 5b：阶段②（约束与单因素）阶段条 + 阶段面板（含约束行）。"""
    from paleo_workbench.mapping_workspace.stages import MappingStage

    return _stage_surface(MappingStage.CONSTRAINT_FACTOR.value)


def build_stage_bar_phase3():
    """场景 5c：阶段③（综合编图）阶段条 + 阶段面板。"""
    from paleo_workbench.mapping_workspace.stages import MappingStage

    return _stage_surface(MappingStage.INTEGRATED_COMPILATION.value)


def build_inspector_version_payload():
    """场景 6a：检查器版本 payload（goal §11 Version 呈现面）。

    show_version 的取值键位在 **payload 顶层**（``object`` 为 dict 时
    ``get()`` 读 payload 本身——engine 侧 dict 投影的既定契约）。
    """
    return _inspector_payload_widget(
        {
            "kind": "version",
            "version_id": "ver_20260912_a12c",
            "asset_name": "A12.las",
            "version_number": 3,
            "stage": "derived",
            "created_at": "2026-09-12 10:24",
            "checksum": "9f2c" * 16,
            "parent_ids": ["ver_20260910_88f1"],
            "run_id": "run_compile_0451",
            "source_kind": "map_compile",
            "downstream_count": 2,
        }
    )


def build_inspector_run_payload():
    """场景 6b：检查器 Run payload（goal §11 Run 呈现面；键位同上在顶层）。"""
    return _inspector_payload_widget(
        {
            "kind": "run",
            "run_id": "run_compile_0451",
            "operation": "map_compile",
            "status": "warning",
            "input_version_ids": ["ver_1", "ver_2", "ver_3"],
            "output_version_ids": ["ver_4"],
            "model": "ConstrainedIDW v2",
            "parameters": {"resolution_m": 250.0, "constraint_mode": "hard"},
            "started_at": 1760000000.0,
            "finished_at": 1760000038.5,
        }
    )


def _inspector_payload_widget(payload: dict):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from paleo_workbench.ui.workstation.inspector import WorkstationInspector

    inspector = WorkstationInspector()
    inspector.show_payload(payload)
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(inspector, 1)
    container.resize(340, 640)
    container._v11_inspector = inspector
    return container


def build_task_center_operations():
    """场景 7：任务中心——OperationRegistry 在途 + 终态带结果标签。"""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from paleo_workbench.ui.operations import OperationRegistry, OperationState
    from paleo_workbench.ui.workstation.task_center import TaskCenter

    registry = OperationRegistry()
    running = registry.begin(
        "v11qa-import", "导入 SEG-Y", object_label="HZ26_3D_full.sgy", cancellable=True
    )
    registry.set_cancel(running, lambda: None)
    registry.update(running, done=42, total=100, stage="读取道头")
    finished = registry.begin("v11qa-verify", "完整性校验", object_label="A12.las")
    registry.finish(
        finished,
        OperationState.WARNING,
        result_label="2 项过期",
        jump=lambda: None,
    )

    center = TaskCenter()
    center.attach_registry(registry)
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.addWidget(center, 1)
    container.resize(760, 320)
    container._v11_task_center = center
    container._v11_registry = registry
    return container


def build_command_palette_disabled_reason():
    """场景 8：命令面板——阶段限定命令禁用带原因 + 编图工具 tooltip 详情。

    走真实 AppShell（palette 的 context provider 由壳接线到 UIContext
    服务；独立构造 palette 无法复现权威判词）。
    """
    from paleo_workbench.mapping_workspace.stages import MappingStage
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell(project=ProjectDocument.new("V11 QA · 命令面板"))
    shell.resize(1600, 900)
    shell.show()
    _settle(200)
    shell.workstation.composite.stage_controller.set_stage(
        MappingStage.FACIES_CALIBRATION.value
    )
    _settle(150)
    palette = shell.command_palette
    palette.popup()
    palette.filter_input.setText(PALETTE_STAGE_FILTER)
    _settle(100)
    return palette


def build_error_empty_states_composite():
    """场景 9：空 / 加载 / 警示徽章行——三种状态面合成一屏。"""
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    from paleo_workbench.ui.components.badges import PwbBadge
    from paleo_workbench.ui.components.states import PwbEmptyState, PwbLoadingState

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)

    empty = PwbEmptyState("暂无数据资产", "导入文件或连接数据目录后在此显示")
    layout.addWidget(empty, 1)

    loading = PwbLoadingState("正在解析 HZ26_3D_full.sgy 道头…")
    layout.addWidget(loading, 1)

    badge_row = QWidget()
    row = QHBoxLayout(badge_row)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    caption = QLabel("目录健康：")
    caption.setObjectName("WorkFieldLabel")
    row.addWidget(caption)
    badges = [
        PwbBadge("2 项过期", tone="warning"),
        PwbBadge("1 项校验失败", tone="error"),
        PwbBadge("98 项已验证", tone="success"),
    ]
    for badge in badges:
        row.addWidget(badge)
    row.addStretch(1)
    layout.addWidget(badge_row)
    layout.addStretch(2)

    container.resize(560, 520)
    container._v11_empty_state = empty
    container._v11_loading_state = loading
    container._v11_badges = badges
    return container


def build_theme_matrix_smoke():
    """场景 10：主题矩阵冒烟——复用阶段②面，检查阶段做 light/dark × 尺寸渲染。"""
    return build_stage_bar_phase2()


# -- 结构检查（门禁断言在 tests/test_v11_visual_qa.py）---------------------------


def _check_first_open(widget) -> list[CheckResult]:
    shell = widget
    ws = shell.workstation
    task_center = ws.task_center
    return [
        _check("shell_workstation_present", ws is not None),
        _check(
            "first_open_inspector_project_context",
            ws.inspector.header.text().startswith("检查器 · 工程"),
            ws.inspector.header.text(),
        ),
        _check(
            "first_open_no_object_selected",
            ws.inspector._current is shell.project,
            repr(ws.inspector._current)[:60],
        ),
        _check(
            "first_open_task_center_empty",
            task_center.model.rowCount() == 0,
            f"rows={task_center.model.rowCount()}",
        ),
        _check(
            "first_open_no_wells_no_resources",
            not shell.project.wells and not shell.project.resources,
        ),
    ]


def _check_data_manager(widget) -> list[CheckResult]:
    page = widget
    model = page.asset_table._active_model()
    row_count = model.rowCount()
    title = page.inspector_panel.title_label.text()
    return [
        _check(
            "asset_table_row_count",
            row_count == len(page.project.resources),
            f"rows={row_count} want={len(page.project.resources)}",
        ),
        _check("inspector_shows_selected_asset", "A12.las" in title, title),
        _check("inspector_empty_label_hidden", page.inspector_panel.empty_label.isHidden()),
        _check("inspector_tabs_visible", not page.inspector_panel.tabs.isHidden()),
    ]


def _check_task_panel(widget) -> list[CheckResult]:
    panel = getattr(widget, "_v11_task_panel", None)
    if panel is None:
        return [_check("task_panel_found", False, "PredictionTaskPanel missing")]
    texts = [
        panel.task_list.item(row).text() for row in range(panel.task_list.count())
    ]
    return [
        _check(
            "task_panel_row_count",
            panel.task_list.count() == 3,
            f"rows={panel.task_list.count()}",
        ),
        _check("task_panel_pending_rendered", any("排队中" in t for t in texts), str(texts)),
        _check("task_panel_running_rendered", any("运行中" in t for t in texts), str(texts)),
        _check("task_panel_complete_rendered", any("完成" in t for t in texts), str(texts)),
        _check(
            "task_panel_active_status_badge",
            panel.status_badge.text() == "运行中",
            panel.status_badge.text(),
        ),
        _check(
            "task_panel_status_badge_tone",
            panel.status_badge.tone in ("primary", "warning"),
            panel.status_badge.tone,
        ),
    ]


def _check_seismic_context(widget) -> list[CheckResult]:
    from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar

    toolbar = widget.findChild(SeismicContextToolbar)
    if toolbar is None:
        return [_check("seismic_toolbar_found", False, "toolbar missing")]
    return [
        _check(
            "seismic_source_selected",
            toolbar.seismic_source_combo.currentText() == "HZ26_3D_full.sgy",
            toolbar.seismic_source_combo.currentText(),
        ),
        _check(
            "seismic_attribute_synced",
            toolbar.attribute_combo.currentText() == "RMS振幅",
            toolbar.attribute_combo.currentText(),
        ),
        _check(
            "seismic_settings_details",
            toolbar.horizon_value.text() == "D63"
            and toolbar.task_value.text() == "振幅属性提取 · HZ26"
            and toolbar.shape_value.text() == "301 × 401 × 1201",
            f"horizon={toolbar.horizon_value.text()} "
            f"task={toolbar.task_value.text()} "
            f"shape={toolbar.shape_value.text()}",
        ),
        _check(
            "seismic_status_readout",
            toolbar.status_value.text() == "运行中 · 第 4/9 属性",
            toolbar.status_value.text(),
        ),
    ]


def _stage_checks(stage_value: str):
    def run(widget) -> list[CheckResult]:
        from paleo_workbench.mapping_workspace.stages import (
            STAGE_ORDER,
            stage_from_value,
        )

        bar = widget._v11_stage_bar
        panel = widget._v11_stage_panel
        target = stage_from_value(stage_value)
        marker_ok = all(
            bar._buttons[stage].isChecked() == (stage == target)
            for stage in STAGE_ORDER
        )
        page = panel._pages.get(target)
        return [
            _check(f"stage_bar_marker[{stage_value}]", marker_ok),
            _check(
                "stage_panel_current_page",
                page is not None and panel.stack.currentWidget() is page,
            ),
            _check(
                "stage_horizon_selected",
                bar.current_horizon() == "D63",
                bar.current_horizon(),
            ),
            _check(
                "stage_constraints_row_visibility",
                (panel._constraints_row is not None
                 and panel._constraints_row.isVisibleTo(panel))
                == (stage_value == "constraint_factor"),
            ),
        ]

    return run


def _form_values(form) -> list[str]:
    values: list[str] = []
    for row in range(form.rowCount()):
        item = form.itemAt(row, form.ItemRole.FieldRole)
        if item is None or item.widget() is None:
            continue
        values.append(item.widget().text())
    return values


def _check_inspector_version(widget) -> list[CheckResult]:
    inspector = widget._v11_inspector
    header = inspector.header.text()
    values = _form_values(inspector.properties_form)
    return [
        _check("inspector_version_header", "版本" in header, header),
        _check(
            "inspector_version_number_row",
            any("v3" in value for value in values),
            str(values),
        ),
        _check(
            "inspector_version_run_row",
            any(value == "run_compile_0451" for value in values),
            str(values),
        ),
        _check(
            "inspector_version_parents_row",
            any("1 项" in value for value in values),
            str(values),
        ),
        _check(
            "inspector_version_checksum_abbreviated",
            any("…" in value for value in values),
            str(values),
        ),
    ]


def _check_inspector_run(widget) -> list[CheckResult]:
    inspector = widget._v11_inspector
    header = inspector.header.text()
    values = _form_values(inspector.properties_form)
    interpretation = _form_values(inspector.interpretation_form)
    return [
        _check("inspector_run_header", "Run" in header, header),
        _check(
            "inspector_run_id_row",
            any("run_compile_0451" in value for value in values),
            str(values),
        ),
        _check(
            "inspector_run_io_rows",
            any("3 项" in value for value in values)
            and any("1 项" in value for value in values),
            str(values),
        ),
        _check(
            "inspector_run_state_token",
            any("失败" in value or "降级" in value for value in values),
            str(values),
        ),
        _check(
            "inspector_run_model_row",
            any("ConstrainedIDW" in value for value in interpretation),
            str(interpretation),
        ),
    ]


def _check_task_center(widget) -> list[CheckResult]:
    center = widget._v11_task_center
    registry = widget._v11_registry
    handles = {
        handle.task_id: handle
        for handle in (
            center.model.handle_at(row) for row in range(center.model.rowCount())
        )
        if handle is not None
    }
    running = handles.get("op:v11qa-import")
    finished = handles.get("op:v11qa-verify")
    from paleo_workbench.ui.workstation.task_center import _TaskRowDelegate

    running_state_text = (
        _TaskRowDelegate._state_text(running) if running is not None else ""
    )
    return [
        _check(
            "task_center_registry_rows_present",
            running is not None and finished is not None,
            f"rows={sorted(handles)}",
        ),
        _check(
            "task_center_running_state_text",
            "运行中" in running_state_text,
            running_state_text,
        ),
        _check(
            "task_center_running_progress",
            running is not None and abs(running.progress - 0.42) < 1e-6,
            f"progress={running.progress if running else None}",
        ),
        _check(
            "task_center_finished_result_label",
            finished is not None and "2 项过期" in (finished.message or ""),
            finished.message if finished else None,
        ),
        _check(
            "task_center_registry_cancellable",
            registry.request_cancel("v11qa-import"),
        ),
    ]


def _check_command_palette(widget) -> list[CheckResult]:
    from PySide6.QtCore import Qt

    palette = widget
    disabled: list[tuple[str, object]] = []
    enabled = 0
    for row in range(palette.result_list.count()):
        item = palette.result_list.item(row)
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            enabled += 1
        else:
            disabled.append((item.text(), item.data(Qt.ItemDataRole.UserRole)))
    reason_visible = any("（" in text and text.endswith("）") for text, _ in disabled)
    stage_scoped = any(getattr(spec, "stages", ()) for _, spec in disabled)
    # 工具景：切到编图工具过滤词，map: 命令挂 action_help 全量解释 tooltip。
    palette.filter_input.setText(PALETTE_TOOL_FILTER)
    _settle(60)
    tool_specs_with_details = [
        item
        for row in range(palette.result_list.count())
        for item in (palette.result_list.item(row),)
        if (item.data(Qt.ItemDataRole.UserRole) or SimpleNamespace(id="")).id.startswith(
            "map:"
        )
        and item.toolTip()
    ]
    tooltip_explains = any("前置条件" in item.toolTip() for item in tool_specs_with_details)
    return [
        _check("palette_open", not palette.isHidden()),
        _check(
            "palette_has_disabled_command",
            bool(disabled),
            f"disabled={len(disabled)} enabled={enabled}",
        ),
        _check(
            "palette_disabled_reason_in_text",
            reason_visible,
            str([text for text, _ in disabled][:3]),
        ),
        _check("palette_disabled_item_is_stage_scoped", stage_scoped, ""),
        _check(
            "palette_map_tool_tooltip_details",
            bool(tool_specs_with_details) and tooltip_explains,
            f"tools_with_tooltip={len(tool_specs_with_details)}",
        ),
    ]


def _check_error_empty_states(widget) -> list[CheckResult]:
    empty = widget._v11_empty_state
    loading = widget._v11_loading_state
    badges = widget._v11_badges
    return [
        _check(
            "empty_state_title",
            empty._title.text() == "暂无数据资产",
            empty._title.text(),
        ),
        _check("empty_state_hint_visible", not empty._hint.isHidden()),
        _check(
            "loading_state_text",
            "HZ26_3D_full.sgy" in loading._text.text(),
            loading._text.text(),
        ),
        _check(
            "loading_state_indeterminate",
            loading._bar.maximum() == 0 and loading._bar.minimum() == 0,
        ),
        _check(
            "warning_badge_tone",
            badges[0].tone == "warning" and badges[0].text() == "2 项过期",
            f"tone={badges[0].tone} text={badges[0].text()}",
        ),
        _check(
            "badge_row_tones_distinct",
            [badge.tone for badge in badges] == ["warning", "error", "success"],
            str([badge.tone for badge in badges]),
        ),
    ]


def _distinct_sampled_colors(pixmap, *, step: int = 48) -> set:
    """抽样像素颜色集合（结构冒烟：渲染内容非单色空白）。"""
    image = pixmap.toImage()
    colors: set = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            colors.add(image.pixel(x, y))
    return colors


def _check_theme_matrix(widget) -> list[CheckResult]:
    """主题矩阵：light/dark × 两尺寸渲染非空（尺寸精确 + 非单色内容）。"""
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.ui.theme import theme_manager

    app = QApplication.instance()
    previous = theme_manager.current_theme.value
    results: list[CheckResult] = []
    try:
        for theme in THEME_MATRIX_THEMES:
            theme_manager.set_theme(theme)
            theme_manager.apply(app)
            for width, height in THEME_MATRIX_SIZES:
                widget.resize(width, height)
                _settle(60)
                pixmap = widget.grab()
                distinct = _distinct_sampled_colors(pixmap)
                results.append(_check(
                    f"theme_matrix[{theme}@{width}x{height}]",
                    (not pixmap.isNull())
                    and pixmap.width() == width
                    and pixmap.height() == height
                    and len(distinct) >= 2,
                    f"size={pixmap.width()}x{pixmap.height()} "
                    f"colors={len(distinct)}",
                ))
    finally:
        theme_manager.set_theme(previous)
        theme_manager.apply(app)
    return results


_SCENARIO_BUILDERS: dict[str, Callable[[], object]] = {
    "first_open_empty_shell": build_first_open_empty_shell,
    "data_manager_surface": build_data_manager_surface,
    "well_task_workflow_panel": build_well_task_workflow_panel,
    "seismic_context_surface": build_seismic_context_surface,
    "stage_bar_phase1": build_stage_bar_phase1,
    "stage_bar_phase2": build_stage_bar_phase2,
    "stage_bar_phase3": build_stage_bar_phase3,
    "inspector_version_payload": build_inspector_version_payload,
    "inspector_run_payload": build_inspector_run_payload,
    "task_center_operations": build_task_center_operations,
    "command_palette_disabled_reason": build_command_palette_disabled_reason,
    "error_empty_states_composite": build_error_empty_states_composite,
    "theme_matrix_smoke": build_theme_matrix_smoke,
}

_CHECKS: dict[str, Callable[[object], list[CheckResult]]] = {
    "first_open_empty_shell": _check_first_open,
    "data_manager_surface": _check_data_manager,
    "well_task_workflow_panel": _check_task_panel,
    "seismic_context_surface": _check_seismic_context,
    "stage_bar_phase1": _stage_checks("facies_calibration"),
    "stage_bar_phase2": _stage_checks("constraint_factor"),
    "stage_bar_phase3": _stage_checks("integrated_compilation"),
    "inspector_version_payload": _check_inspector_version,
    "inspector_run_payload": _check_inspector_run,
    "task_center_operations": _check_task_center,
    "command_palette_disabled_reason": _check_command_palette,
    "error_empty_states_composite": _check_error_empty_states,
    "theme_matrix_smoke": _check_theme_matrix,
}


def build_scenario(name: str):
    """按场景名构建离屏可渲染的 QWidget（未知场景 → KeyError）。"""
    try:
        builder = _SCENARIO_BUILDERS[name]
    except KeyError as exc:
        raise KeyError(f"未知 V11 视觉 QA 场景: {name}") from exc
    return builder()


def run_scenario_checks(name: str, widget) -> list[CheckResult]:
    """对已构建的场景 widget 跑结构检查（未知场景 → 空表）。"""
    runner = _CHECKS.get(name)
    return runner(widget) if runner else []


def v11_shot_table() -> dict[str, Callable[[], object]]:
    """场景 → 构建函数表（截图 harness / 测试共用注册形态）。"""
    return dict(_SCENARIO_BUILDERS)


def scenario_needs_workstation_shell(name: str) -> bool:
    """场景是否构建完整工作站壳（测试据此强制 fallback 画布，保无桥语义）。"""
    return name in ("first_open_empty_shell", "command_palette_disabled_reason")
