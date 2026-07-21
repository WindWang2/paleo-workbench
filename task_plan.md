# Task Plan: Paleo Workbench 整体简化、重构与文档整理

## Goal

对 `paleo_workbench` 项目进行全面的系统性重构与代码简化（P1-P4），斩断反向依赖，清理死代码与重复样板，拆分上帝类，并整理项目文档与配置文件，确保测试 100% 保持全绿。

## Current Phase

Phase 5 — Complete & Verified

## Phases

### Phase 1: P1 — 低风险去重 + 死代码清理

- [x] 提取共享任务面板基类，合并 `prediction_task_panel.py` 与 `seismic_task_panel.py`
- [x] 合并 `seismic_prediction.py` 与 `well_log_prediction.py` 的公共预测工作流
- [x] 删除死代码：`adapters/` 包、`workflow/well_table.py` 无用函数及未使用的 UI 组件
- [x] 提取 `PAGE_INDEX_*` 到 `ui/navigation.py`，暴露 `workflow_controller` 公开 API
- **Status:** complete (Commit `933d769`)

### Phase 2: P2 — 分层架构修复

- [x] 斩断 `viz → ui` 依赖：下沉 `mapping_helpers`、`prediction_helpers`、`seismic_prediction_helpers`、`geoviz_preview_host` 到 `viz/`
- [x] 消除 `resources → workflow` 依赖：迁移 `record_export` 到 `project/artifacts.py` 并删除旧模块
- [x] 上移并清理 30+ 处函数内 import
- **Status:** complete (Commit `a7bcd59`)

### Phase 3: P3 — 预览子系统归位与控件拆分

- [x] 将格式解析下沉到 `resources/preview_parsers/`（含 table, well_log, seismic, office, document 解析器）
- [x] `_build_preview` 改用 `PreviewRegistry` 注册表模式
- [x] 将 `preview_widgets.py` 拆分为 12 个独立预览控件模块，保留 100% 兼容门面
- **Status:** complete (Commit `ac291e0`)

### Phase 4: P4 — 拆分 `map_edit_scene.py` (上帝类瘦身)

- [x] 抽取 `map_edit_factory.py`（图形项工厂纯函数）
- [x] 抽取 `map_edit_draft.py`（草图绘制状态机与预览控制）
- [x] 抽取 `map_edit_snap.py`（控制点吸附与候选点缓存管理）
- [x] 抽取 `map_edit_topology.py`（拓扑校验与几何合并/拆分编排）
- [x] `map_edit_scene.py` 代码行数从 1382 行降至 604 行（缩减 56%）
- **Status:** complete (Commit `8974bbe`)

### Phase 5: 文档整理与配置清理 (Documentation & Planning Cleanup)

- [x] 审计与清理过期导入路径（如 `tests/test_fallback_preview.py`）
- [x] 规范化 `document_parsers.py` 中 `rasterio` read 的 2D shape 参数，消除 NumPy 2.5 废弃警告
- [x] 整理与更新项目根目录 Planning 体系（`task_plan.md`、`findings.md`、`progress.md`）
- [x] 验证全量 1109 个 Pytest 测试 100% 绿灯通过
- **Status:** complete

## Decisions Made

| Decision | Rationale |
|---|---|
| 保留旧模块 (如 `preview_widgets.py`, `fallback_preview.py`) 作为 re-export 兼容门面 | 维持 100% 向后兼容性，避免对依赖第三方或动态 monkeypatch 的测试造成破坏。 |
| 将 `resources/preview_parsers/` 下沉到 `resources/` | 保持 `resources` 作为基础资源/格式解析层，符合 `ui → viz/workflow/resources/mapping → project` 的分层依赖规则。 |
| 拆分 `map_edit_scene.py` 为 4 个高内聚辅助模块 | 将几何工厂、草图状态机、吸附管理器、拓扑算法与主 Scene 事件路由解耦，提高可维护性。 |

## Errors Encountered & Resolved

| Error | Attempt | Resolution |
|---|---:|---|
| `AttributeError: '_safe_stat'` during test monkeypatch | 1 | 在 `PreviewProvider` 重新暴露 `_safe_stat` 并注入 `safe_stat_fn` 参数。 |
| `setPageMode` failure on stub `QPdfView` | 1 | 统一通过 `preview_widgets.QPdfView` 动态反射获取 `PageMode` 枚举值。 |
| `NumPy 2.5 DeprecationWarning` in `document_parsers.py` | 1 | 将 `dataset.read(1, out_shape=(1, h, w))` 的 3D shape 改为标准的 2D shape `(h, w)`。 |
