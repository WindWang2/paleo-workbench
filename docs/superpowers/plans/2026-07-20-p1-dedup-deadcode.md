# P1 低风险去重 + 死代码清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 合并两处成对复制代码（任务面板、预测工作流），删除死代码（adapters/ 包、ui/widgets/、get_well_table），并将 PAGE_INDEX_* 常量上移、WorkflowController 私有接口公开化。

**Architecture:** 纯结构重构，不改行为。提取 `TaskPanelBase` 基类保留两个子类的 objectName/标题/字段差异；提取 `run_facies_prediction` 共享函数，两个公开函数保留原模块原签名做薄封装；PAGE_INDEX_* 移入 `ui/navigation.py` 并由 app_shell 再导出保持兼容。

**Tech Stack:** Python 3.12, PySide6, pydantic, pytest + pytest-qt。

**Spec:** `docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md`（P1 节）

## Global Constraints

- 只改结构，不改功能行为与 UI 文案。
- 现有测试是安全网：除计划明确列出的测试文件调整外，不得修改测试逻辑。
- 测试运行命令统一为 `.venv/bin/python -m pytest <path> -q`（项目使用 `.venv`）。
- 每个 Task 结束独立 commit，可单独 revert。
- 保持兼容锚点：`PredictionTaskPanel`/`SeismicTaskPanel` 类名与 objectName 不变；`run_seismic_facies_prediction`/`run_well_log_facies_prediction` 函数名与所在模块不变；`PAGE_INDEX_*` 从 `paleo_workbench.ui.app_shell` 仍可导入（tests/test_app_shell.py、test_stratigraphy_correlation.py、test_visualization_jump.py 依赖）；`window._preview_settings_dialog` 属性保留（tests/test_data_integration.py:70,85 依赖）。

---

### Task 1: 建立测试基线

**Files:** 无（只读验证）

**Interfaces:** 无

- [ ] **Step 1: 跑全量测试确认基线全绿**

Run: `.venv/bin/python -m pytest tests -q --tb=short -p no:cacheprovider 2>&1 | tail -5`
Expected: 全部 passed（若有 failed/error，停下来先报告，不要继续后续 Task）

---

### Task 2: 合并任务面板（TaskPanelBase）

**Files:**
- Create: `paleo_workbench/ui/pages/task_panel_base.py`
- Modify: `paleo_workbench/ui/pages/prediction_task_panel.py`（整体重写为薄子类）
- Modify: `paleo_workbench/ui/pages/seismic_task_panel.py`（整体重写为薄子类）
- Test: `tests/test_prediction_task_panel.py`、`tests/test_seismic_task_panel.py`、`tests/test_work_page_presentation.py`、`tests/test_well_log_prediction_page.py`（均不修改，用于验证）

**Interfaces:**
- Consumes: 现有 `paleo_workbench.ui.pages.prediction_helpers.active_prediction_task` / `field_value`；`paleo_workbench.ui.tokens`。
- Produces: `TaskPanelBase(QFrame)`，构造参数 `(*, object_name: str, title: str, show_review_count: bool, parent=None)`；属性 `name_value`/`adapter_value`/`status_value`/`mean_probability_value`/`review_count_value`（show_review_count=False 时为 None）/`task_list`；信号 `task_selected = Signal(int)`；方法 `update_state(prediction_tasks, *, selected_index=None)`。`PredictionTaskPanel` 与 `SeismicTaskPanel` 为其无新增行为的子类。

背景：两文件约 100 行近乎逐字相同，差异仅：objectName（`PredictionTaskPanel`/`SeismicTaskPanel`）、标题（`测井预测任务`/`地震预测任务`）、Prediction 版多一个 `待复核区` 字段（`review_count_value`）。QSS 在 `ui/tokens.py:346,349` 同时引用两个 objectName，必须保留。

- [ ] **Step 1: 先跑现有面板测试确认绿**

Run: `.venv/bin/python -m pytest tests/test_prediction_task_panel.py tests/test_seismic_task_panel.py tests/test_work_page_presentation.py -q`
Expected: PASS

- [ ] **Step 2: 创建 `paleo_workbench/ui/pages/task_panel_base.py`**

```python
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, field_value


class TaskPanelBase(QFrame):
    """Shared left-hand task summary panel with selection list."""

    task_selected = Signal(int)

    def __init__(
        self,
        *,
        object_name: str,
        title: str,
        show_review_count: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedWidth(240)
        self._tasks: list = []
        self._suppress = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title_label = QLabel(title)
        title_label.setObjectName("MapDockTitle")
        layout.addWidget(title_label)

        self.name_value = self._add_value(layout, "当前任务", "未选择预测任务")
        self.adapter_value = self._add_value(layout, "适配器", "—")
        self.status_value = self._add_value(layout, "状态", "待开始")
        self.mean_probability_value = self._add_value(layout, "平均概率", "—")
        self.review_count_value = (
            self._add_value(layout, "待复核区", "0 个") if show_review_count else None
        )

        list_label = QLabel("任务列表")
        list_label.setObjectName("WorkFieldLabel")
        layout.addWidget(list_label)
        self.task_list = QListWidget()
        self.task_list.setObjectName("WorkListWidget")
        self.task_list.currentRowChanged.connect(self._on_row)
        layout.addWidget(self.task_list, 1)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def _on_row(self, row: int) -> None:
        if not self._suppress and row >= 0:
            self.task_selected.emit(row)

    def update_state(
        self,
        prediction_tasks: list | tuple | None,
        *,
        selected_index: int | None = None,
    ) -> None:
        tasks = list(prediction_tasks or [])
        self._tasks = tasks
        if selected_index is not None and 0 <= selected_index < len(tasks):
            task = tasks[selected_index]
        else:
            task = active_prediction_task(tasks)

        self.name_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.adapter_value.setText(field_value(task, "adapter_kind", "") or "—")
        self.status_value.setText(field_value(task, "status", "") or "待开始")
        probability = (field_value(task, "probability_summary", {}) or {}).get(
            "mean_probability"
        )
        self.mean_probability_value.setText(
            str(probability) if probability is not None else "—"
        )
        if self.review_count_value is not None:
            self.review_count_value.setText(
                f"{len(field_value(task, 'review_areas', []) or [])} 个"
            )

        self._suppress = True
        self.task_list.clear()
        active_row = -1
        for index, item in enumerate(tasks):
            name = field_value(item, "name", "") or "未命名预测任务"
            status = field_value(item, "status", "") or "pending"
            self.task_list.addItem(f"{name} · {status}")
            if task is not None and (
                item is task
                or field_value(item, "id", None) == field_value(task, "id", None)
            ):
                active_row = index
        if active_row >= 0:
            self.task_list.setCurrentRow(active_row)
        self._suppress = False
```

- [ ] **Step 3: 重写 `paleo_workbench/ui/pages/prediction_task_panel.py` 为薄子类**

完整文件内容：

```python
from __future__ import annotations

from paleo_workbench.ui.pages.task_panel_base import TaskPanelBase


class PredictionTaskPanel(TaskPanelBase):
    """Left-hand summary of prediction tasks with selection."""

    def __init__(self, parent=None):
        super().__init__(
            object_name="PredictionTaskPanel",
            title="测井预测任务",
            show_review_count=True,
            parent=parent,
        )
```

- [ ] **Step 4: 重写 `paleo_workbench/ui/pages/seismic_task_panel.py` 为薄子类**

完整文件内容：

```python
from __future__ import annotations

from paleo_workbench.ui.pages.task_panel_base import TaskPanelBase


class SeismicTaskPanel(TaskPanelBase):
    """Left-hand summary of seismic prediction tasks with selection."""

    def __init__(self, parent=None):
        super().__init__(
            object_name="SeismicTaskPanel",
            title="地震预测任务",
            show_review_count=False,
            parent=parent,
        )
```

- [ ] **Step 5: 跑面板相关测试**

Run: `.venv/bin/python -m pytest tests/test_prediction_task_panel.py tests/test_seismic_task_panel.py tests/test_work_page_presentation.py tests/test_well_log_prediction_page.py -q`
Expected: PASS（与原行为一致）

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/pages/task_panel_base.py paleo_workbench/ui/pages/prediction_task_panel.py paleo_workbench/ui/pages/seismic_task_panel.py
git commit -m "refactor: 提取 TaskPanelBase 合并预测/地震任务面板重复代码"
```

---

### Task 3: 合并预测工作流（run_facies_prediction）

**Files:**
- Create: `paleo_workbench/workflow/facies_prediction.py`
- Modify: `paleo_workbench/workflow/seismic_prediction.py`（run 函数改薄封装，保留 LABELS 常量）
- Modify: `paleo_workbench/workflow/well_log_prediction.py`（run 函数改薄封装，其余函数不动）
- Test: `tests/test_seismic_workflow.py`、`tests/test_well_log_workflow.py`、`tests/test_local_prediction_adapter.py`、`tests/test_seismic_prediction_integration.py`、`tests/test_well_log_prediction_integration.py`（均不修改，用于验证）

**Interfaces:**
- Consumes: `paleo_workbench.pipeline.assets.bind_prediction_assets` / `suggest_assets_for_demo`；`paleo_workbench.prediction.adapters.LocalAssetPredictionAdapter`；`paleo_workbench.workflow.stratigraphy.active_target_horizon`。
- Produces: `run_facies_prediction(project: ProjectDocument, *, seed: int = 0, workflow: str, name_prefix: str) -> PredictionTask`。公开函数 `run_seismic_facies_prediction(project, *, seed=0)` 与 `run_well_log_facies_prediction(project, *, seed=0)` 签名、模块位置、行为（task.name、model_metadata、result_summary 内容）完全不变。

背景：两函数仅差 `workflow` 标识（`seismic_facies`/`well_log_facies`）与名称前缀（`地震相预测`/`单井相预测`），其余逐字相同。

- [ ] **Step 1: 先跑现有工作流测试确认绿**

Run: `.venv/bin/python -m pytest tests/test_seismic_workflow.py tests/test_well_log_workflow.py tests/test_local_prediction_adapter.py -q`
Expected: PASS

- [ ] **Step 2: 创建 `paleo_workbench/workflow/facies_prediction.py`**

```python
"""Shared facies prediction run (workbench side).

Uses LocalAssetPredictionAdapter (ISS-PRED-01) with asset binding and tags
workflow/target_horizon so prediction pages and mapping compile share context.
"""

from __future__ import annotations

from paleo_workbench.pipeline.assets import bind_prediction_assets, suggest_assets_for_demo
from paleo_workbench.prediction.adapters import LocalAssetPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument
from paleo_workbench.workflow.stratigraphy import active_target_horizon


def run_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
    workflow: str,
    name_prefix: str,
) -> PredictionTask:
    """Create a complete facies PredictionTask bound to project assets.

    Uses factor-map ids when available; binds suggested demo assets and tags
    ``workflow``/``target_horizon`` into model_metadata and result_summary.
    """
    factor_ids = [
        task.id
        for task in project.factor_map_tasks
        if getattr(task, "status", "") == "complete"
    ]
    adapter = LocalAssetPredictionAdapter()
    task = adapter.run(project, factor_ids, seed=seed)
    suggestion = suggest_assets_for_demo(project)
    bind_prediction_assets(
        project,
        task,
        well_log_ids=suggestion["well_log_ids"],
        seismic_ids=suggestion["seismic_ids"],
    )
    horizon = active_target_horizon(project) or project.stratigraphy.target_horizon or ""
    task.name = f"{name_prefix} · {horizon or 'demo'}"
    meta = dict(task.model_metadata or {})
    meta["workflow"] = workflow
    meta["target_horizon"] = horizon
    meta["adapter"] = task.adapter_kind
    task.model_metadata = meta
    summary = dict(task.result_summary or {})
    summary["workflow"] = workflow
    summary["target_horizon"] = horizon
    task.result_summary = summary
    return task
```

- [ ] **Step 3: 重写 `paleo_workbench/workflow/seismic_prediction.py`**

完整文件内容：

```python
"""Seismic facies prediction workflow helpers (workbench side).

Uses LocalAssetPredictionAdapter (ISS-PRED-01) with seismic/LAS asset binding
and tags target_horizon so prediction page / mapping compile share context.
"""

from __future__ import annotations

from paleo_workbench.project.models import PredictionTask, ProjectDocument
from paleo_workbench.workflow.facies_prediction import run_facies_prediction


def run_seismic_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
) -> PredictionTask:
    """Create a complete seismic facies PredictionTask bound to project SEGY.

    Uses factor-map ids when available; always binds the first available seismic
    resource so SeismicView can load a real volume when present.
    """
    return run_facies_prediction(
        project,
        seed=seed,
        workflow="seismic_facies",
        name_prefix="地震相预测",
    )


# Labels aligned with geoviz_seismic.attribute_pipeline (subset for workbench UI)
SEISMIC_ATTRIBUTE_LABELS = (
    "振幅",
    "包络",
    "瞬时相位",
    "瞬时频率",
    "RMS振幅",
    "甜点",
)

SEISMIC_DISPLAY_MODES = ("vd", "wiggle")
```

- [ ] **Step 4: 修改 `paleo_workbench/workflow/well_log_prediction.py` 的 run 函数**

只做两处改动，文件其余部分（`lithology_name_for_facies`、`regions_to_depth_intervals`、`merge_prediction_onto_well_log`、`export_well_canvas`）逐字保留：

1. 文件头部 import 区：删除 `from paleo_workbench.pipeline.assets import (WELL_KEY, bind_prediction_assets, suggest_assets_for_demo,)`、`from paleo_workbench.prediction.adapters import LocalAssetPredictionAdapter`、`from paleo_workbench.workflow.stratigraphy import active_target_horizon` 三行（已验证 `WELL_KEY` 仅出现在 import 行，文件其余部分无使用），新增 `from paleo_workbench.workflow.facies_prediction import run_facies_prediction`。保留 `from pathlib import Path`、`from typing import Any`、`from paleo_workbench.project.models import PredictionTask, ProjectDocument`（均被保留的函数使用）。
2. `run_well_log_facies_prediction` 函数体替换为：

```python
def run_well_log_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
) -> PredictionTask:
    """Create a complete well-facies PredictionTask bound to LAS resources.

    Uses :class:`LocalAssetPredictionAdapter` so readable LAS GR curves drive
    depth zones when present (ISS-PRED-01); otherwise falls back to mock.
    """
    return run_facies_prediction(
        project,
        seed=seed,
        workflow="well_log_facies",
        name_prefix="单井相预测",
    )
```

- [ ] **Step 5: 跑工作流相关测试**

Run: `.venv/bin/python -m pytest tests/test_seismic_workflow.py tests/test_well_log_workflow.py tests/test_local_prediction_adapter.py tests/test_seismic_prediction_integration.py tests/test_well_log_prediction_integration.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/workflow/facies_prediction.py paleo_workbench/workflow/seismic_prediction.py paleo_workbench/workflow/well_log_prediction.py
git commit -m "refactor: 提取 run_facies_prediction 合并地震/测井预测工作流重复代码"
```

---

### Task 4: 删除死代码（adapters/ 包、ui/widgets/、get_well_table）

**Files:**
- Delete: `paleo_workbench/adapters/__init__.py`、`base.py`、`paleo_map.py`、`schemas.py`（整个 `paleo_workbench/adapters/` 目录）
- Delete: `paleo_workbench/ui/widgets/__init__.py`、`empty_state.py`、`page_scaffold.py`、`panel_card.py`、`section_header.py`、`toolbar_strip.py`（整个 `paleo_workbench/ui/widgets/` 目录）
- Delete: `tests/test_adapter_schemas.py`（纯 adapter 契约测试）
- Delete: `tests/test_ui_widgets.py`（纯 widgets 测试）
- Modify: `tests/test_integration_smoke.py`（替换 adapter 导出步骤，保留管道契约测试意图）
- Modify: `tests/test_e2e_dataflow_contract.py`（同上）
- Modify: `paleo_workbench/workflow/well_table.py:174-178`（删除 `get_well_table`）

**Interfaces:**
- Consumes: 无。
- Produces: 无（纯删除）。注意 `paleo_workbench.prediction.adapters`（Mock/LocalAsset 预测适配器）是**不同模块**，严禁误删。

背景核查结论（已 grep 验证）：`paleo_workbench.adapters` 仅被上述 3 个测试文件引用，生产代码零引用；`paleo_workbench.ui.widgets` 仅被 `tests/test_ui_widgets.py` 引用；`get_well_table` 全库（含 tests）无调用点。两个 e2e/smoke 测试用 `PaleoMapAdapter` 只是为了产出 geojson 文件给 `record_export`，用直接写文件替代即可，测试意图（管道契约）不变。

- [ ] **Step 1: 删除前复核无动态引用**

Run: `grep -rn "paleo_workbench\.adapters\|ui\.widgets\|get_well_table\|importlib\|getattr" paleo_workbench/ --include="*.py" | grep -v "prediction.adapters\|paleo_workbench.ui.widgets" ; grep -rn "adapters\|ui\.widgets\|get_well_table" paleo_workbench/ tests/ --include="*.py" | grep -vE "prediction\.adapters|prediction/adapters|docs/"`
Expected: 仅出现计划内将删除/修改的文件；无 importlib/getattr 形式的动态引用指向待删符号

- [ ] **Step 2: 修改 `tests/test_integration_smoke.py`**

1. 删除第 3 行 `from paleo_workbench.adapters.paleo_map import PaleoMapAdapter`；文件头部（`from pathlib import Path` 之后）新增 `import json`。
2. `test_full_mvp_loop_recovers_dashboard_state` 中的导出段：

```python
    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "resources": [], "layers": []})
    export_path = tmp_path / "demo.artifacts" / "exports" / "map.geojson"
    result = adapter.export({"path": str(export_path), "format": "geojson"})
    artifact = record_export(project, doc.id, result.output_path, result.format, [pred.id, qc.id])
```

替换为：

```python
    export_path = tmp_path / "demo.artifacts" / "exports" / "map.geojson"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
    )
    artifact = record_export(project, doc.id, str(export_path), "geojson", [pred.id, qc.id])
```

- [ ] **Step 3: 修改 `tests/test_e2e_dataflow_contract.py`**

1. 删除第 11 行 `from paleo_workbench.adapters.paleo_map import PaleoMapAdapter`；在 `from pathlib import Path` 之后新增 `import json`。
2. 步骤 8 中的导出段：

```python
    adapter = PaleoMapAdapter()
    adapter.set_data(
        {
            "viewer_type": "paleo_map",
            "layers": [
                {
                    "id": "facies",
                    "features": list(doc.facies_polygons or []),
                }
            ],
        }
    )
    geo_path = tmp_path / "map.geojson"
    result = adapter.export({"path": str(geo_path), "format": "geojson"})
    art = record_export(
        project, doc.id, result.output_path, result.format, [pred.id, qc2.id]
    )
```

替换为：

```python
    geo_path = tmp_path / "map.geojson"
    geo_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": list(doc.facies_polygons or []),
            }
        ),
        encoding="utf-8",
    )
    art = record_export(project, doc.id, str(geo_path), "geojson", [pred.id, qc2.id])
```

- [ ] **Step 4: 删除 `well_table.py` 中的 `get_well_table`**

删除 `paleo_workbench/workflow/well_table.py` 第 174-178 行（含尾部空行一并整理）：

```python
def get_well_table(project: ProjectDocument, table_id: str) -> WellTable | None:
    for table in project.well_tables:
        if table.id == table_id:
            return table
    return None
```

- [ ] **Step 5: 删除死代码目录与纯契约测试**

```bash
git rm -r paleo_workbench/adapters paleo_workbench/ui/widgets tests/test_adapter_schemas.py tests/test_ui_widgets.py
```

- [ ] **Step 6: 跑受影响测试**

Run: `.venv/bin/python -m pytest tests/test_integration_smoke.py tests/test_e2e_dataflow_contract.py tests/test_well_table.py tests/test_prep_well_table_worker.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: 删除死代码 adapters/ 包、ui/widgets/ 与 get_well_table"
```

---

### Task 5: PAGE_INDEX_* 常量上移至 ui/navigation.py

**Files:**
- Create: `paleo_workbench/ui/navigation.py`
- Modify: `paleo_workbench/ui/app_shell.py:30-40`（常量定义改为从 navigation 导入再导出）
- Modify: `paleo_workbench/ui/workflow_controller.py`（3 处函数内 import 删除，改顶层导入）
- Test: `tests/test_app_shell.py`、`tests/test_stratigraphy_correlation.py`、`tests/test_visualization_jump.py`、`tests/test_page_transition.py`（均不修改，用于验证）

**Interfaces:**
- Consumes: 无。
- Produces: `paleo_workbench.ui.navigation` 模块，导出 `PAGE_INDEX_HOME/DATA/WELL_LOG/SEISMIC/SEQUENCE/STRATIGRAPHY/VISUALIZATION/PREPARATION/MAPPING/REVIEW`（值 0-9 不变）。`paleo_workbench.ui.app_shell` 继续再导出全部 10 个常量（兼容现有 import）。

- [ ] **Step 1: 创建 `paleo_workbench/ui/navigation.py`**

```python
"""Stable page indices for AppShell navigation (avoid magic numbers)."""

from __future__ import annotations

PAGE_INDEX_HOME = 0
PAGE_INDEX_DATA = 1
PAGE_INDEX_WELL_LOG = 2
PAGE_INDEX_SEISMIC = 3
PAGE_INDEX_SEQUENCE = 4
PAGE_INDEX_STRATIGRAPHY = 5
PAGE_INDEX_VISUALIZATION = 6
PAGE_INDEX_PREPARATION = 7
PAGE_INDEX_MAPPING = 8
PAGE_INDEX_REVIEW = 9
```

- [ ] **Step 2: 修改 `app_shell.py` 常量定义段**

将第 30-40 行：

```python
# Stable page indices (avoid magic numbers in callers/tests).
PAGE_INDEX_HOME = 0
PAGE_INDEX_DATA = 1
PAGE_INDEX_WELL_LOG = 2
PAGE_INDEX_SEISMIC = 3
PAGE_INDEX_SEQUENCE = 4
PAGE_INDEX_STRATIGRAPHY = 5
PAGE_INDEX_VISUALIZATION = 6
PAGE_INDEX_PREPARATION = 7
PAGE_INDEX_MAPPING = 8
PAGE_INDEX_REVIEW = 9
```

替换为（放在原有 import 区之后，保持再导出兼容）：

```python
# Stable page indices, re-exported for backwards compatibility (callers/tests
# import them from here); canonical definition lives in ui/navigation.py.
from paleo_workbench.ui.navigation import (
    PAGE_INDEX_DATA,
    PAGE_INDEX_HOME,
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_PREPARATION,
    PAGE_INDEX_REVIEW,
    PAGE_INDEX_SEISMIC,
    PAGE_INDEX_SEQUENCE,
    PAGE_INDEX_STRATIGRAPHY,
    PAGE_INDEX_VISUALIZATION,
    PAGE_INDEX_WELL_LOG,
)
```

- [ ] **Step 3: 修改 `workflow_controller.py`**

1. 文件头部 import 区新增：

```python
from paleo_workbench.ui.navigation import (
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_PREPARATION,
    PAGE_INDEX_VISUALIZATION,
)
```

2. 删除三处函数内 import：第 130 行 `from paleo_workbench.ui.app_shell import PAGE_INDEX_PREPARATION`、第 179 行 `from paleo_workbench.ui.app_shell import PAGE_INDEX_MAPPING`、第 265 行 `from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION`。其余代码不动。

- [ ] **Step 4: 跑受影响测试**

Run: `.venv/bin/python -m pytest tests/test_app_shell.py tests/test_stratigraphy_correlation.py tests/test_visualization_jump.py tests/test_page_transition.py tests/test_keyboard_shortcuts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/navigation.py paleo_workbench/ui/app_shell.py paleo_workbench/ui/workflow_controller.py
git commit -m "refactor: PAGE_INDEX_* 常量上移至 ui/navigation.py"
```

---

### Task 6: WorkflowController 私有接口公开化

**Files:**
- Create: `tests/test_workflow_controller_api.py`
- Modify: `paleo_workbench/ui/workflow_controller.py`（8 个 `_wire_*`、`_show_preview_settings`、`_apply_preview_settings`、`_preview_settings_dialog` 改公开名）
- Modify: `paleo_workbench/app.py`（对应调用点改公开名）

**Interfaces:**
- Consumes: Task 5 后的 `workflow_controller.py`。
- Produces: `WorkflowController` 公开方法 `wire_home_page()`、`wire_data_visualization_jump()`、`wire_mapping_page()`、`wire_preparation_page()`、`wire_sequence_page()`、`wire_seismic_page()`、`wire_well_log_page()`、`wire_review_page()`、`show_preview_settings()`、`apply_preview_settings(settings)`；公开属性 `preview_settings_dialog`（初始 None）。`PaleoWorkbenchWindow._preview_settings_dialog` property 保留，改为委托到 `workflow_controller.preview_settings_dialog`。

背景：已 grep 验证这 10 个方法的唯一外部调用方是 `app.py`；`window._preview_settings_dialog` 被 `tests/test_data_integration.py:70,85` 使用，故 window 上的 property 保留。controller 内部 `dialog.settings_applied.connect(self._apply_preview_settings)` 同步改名。`app_shell._switch_page`、controller 访问 `window._preview_settings_store` 不在本批范围（P2 处理）。

- [ ] **Step 1: 写失败测试 `tests/test_workflow_controller_api.py`**

```python
"""WorkflowController public API surface (P1 refactor)."""


def test_workflow_controller_exposes_public_wiring_methods():
    from paleo_workbench.ui.workflow_controller import WorkflowController

    for name in (
        "wire_home_page",
        "wire_data_visualization_jump",
        "wire_mapping_page",
        "wire_preparation_page",
        "wire_sequence_page",
        "wire_seismic_page",
        "wire_well_log_page",
        "wire_review_page",
        "show_preview_settings",
        "apply_preview_settings",
    ):
        assert callable(getattr(WorkflowController, name, None)), name


def test_window_delegates_preview_settings_dialog_to_controller(qtbot):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window._preview_settings_dialog is None
    window.workflow_controller.preview_settings_dialog = object()
    assert window._preview_settings_dialog is window.workflow_controller.preview_settings_dialog
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_workflow_controller_api.py -q`
Expected: FAIL（`wire_home_page` 等不存在）

- [ ] **Step 3: 重命名 `workflow_controller.py` 中的方法/属性**

全部改为公开名（方法体不变，仅 `def _wire_home_page` → `def wire_home_page` 等；docstring 不变）：

- `_wire_home_page` → `wire_home_page`
- `_wire_data_visualization_jump` → `wire_data_visualization_jump`
- `_wire_mapping_page` → `wire_mapping_page`
- `_wire_preparation_page` → `wire_preparation_page`
- `_wire_sequence_page` → `wire_sequence_page`
- `_wire_seismic_page` → `wire_seismic_page`
- `_wire_well_log_page` → `wire_well_log_page`
- `_wire_review_page` → `wire_review_page`
- `_show_preview_settings` → `show_preview_settings`
- `_apply_preview_settings` → `apply_preview_settings`
- 属性 `_preview_settings_dialog` → `preview_settings_dialog`（`__init__` 中的赋值、`show_preview_settings` 内 4 处自引用同步改；`dialog.settings_applied.connect(self._apply_preview_settings)` 改为 `self.apply_preview_settings`）

注意 `show_preview_settings` 方法体内的 `self.window._preview_settings_store` 保留不动（window 侧属性，P2 范围）。

- [ ] **Step 4: 更新 `app.py` 调用点**

1. `_preview_settings_dialog` property（第 89-95 行）改为：

```python
    @property
    def _preview_settings_dialog(self):
        return self.workflow_controller.preview_settings_dialog

    @_preview_settings_dialog.setter
    def _preview_settings_dialog(self, val) -> None:
        self.workflow_controller.preview_settings_dialog = val
```

2. `_show_preview_settings`（第 184-185 行）与 `_apply_preview_settings`（第 187-188 行）的方法体改为调用公开名：

```python
    def _show_preview_settings(self) -> None:
        self.workflow_controller.show_preview_settings()

    def _apply_preview_settings(self, settings) -> None:
        self.workflow_controller.apply_preview_settings(settings)
```

3. `_wire_menu_bar`（第 205-212 行）8 处 `self.workflow_controller._wire_*()` 改为对应的公开名（`wire_home_page()` 等）。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_workflow_controller_api.py tests/test_data_integration.py tests/test_app_shell.py tests/test_keyboard_shortcuts.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/workflow_controller.py paleo_workbench/app.py tests/test_workflow_controller_api.py
git commit -m "refactor: WorkflowController 接线与预览设置接口公开化"
```

---

### Task 7: 全量回归

**Files:** 无

**Interfaces:** 无

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest tests -q --tb=short -p no:cacheprovider 2>&1 | tail -5`
Expected: 全部 passed，总数 **1109 passed**（基线 1117 − 删除 test_adapter_schemas 5 个 − 删除 test_ui_widgets 5 个 + 新增 test_workflow_controller_api 2 个）

- [ ] **Step 2: 复核无遗留引用**

Run: `grep -rn "paleo_workbench\.adapters\b\|paleo_workbench\.ui\.widgets\|get_well_table\|_wire_home_page\|controller\._show_preview\|controller\._apply_preview" paleo_workbench/ tests/ --include="*.py"`
Expected: 无输出（`prediction.adapters` 不受影响）

- [ ] **Step 3: 更新 spec 状态**

将 `docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md` 的状态行改为 `状态：P1 已完成（YYYY-MM-DD），P2-P4 待实施`，然后：

```bash
git add docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md
git commit -m "docs: 标记 P1 重构完成"
```
