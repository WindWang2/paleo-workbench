# 09 — Agent Command Contract（W-S，V13）

## 原则

UI 与 Agent 共用同一 domain 实现——不是"各自调用相似函数"，而是
**同一模块函数/同一 service 入口**：

| 操作 | UI 路径 | Agent action | 共用实现 |
|---|---|---|---|
| 规划导入 | IngestPlanDialog | data.ingest_plan / data.ingest | resources/ingest_plan.build/execute |
| 快速导入 | DataPage 旧路径 | —（用规划导入） | import_service（人专用快速道） |
| 新建工作副本 | new_version_from_asset | data.create_working_copy | service.create_working_copy |
| 提交版本 | 同上 + EditSession | data.commit_working_copy | catalog/lifecycle manual_edit 助手 |
| 查地图用途 | InspectorPanel provider | data.map_usage | mapping_workspace/source_usage |
| 重算过期 | workflow_controller | data.recompute_stale | recompute_plan.PlanExecutor + 同一 factor_map handler 领域调用 |
| 图层重排/激活 | 树拖拽/面板 | —（本轮未加 action） | LayerGroupController.observe/register（域唯一入口；harness 化留待下轮，见 14） |

## 契约属性

- typed：JSON schema 输入/输出（ActionSpec input_schema/output_schema）；
- deterministic：ingest 从 (root, catalog 态) 确定性重建计划；
- auditable：所有写操作落 DataRun/manual_edit provenance；
- replayable：ingest 幂等（path+sha 重查）、commit 依赖 working_copies 权威行；
- precondition aware：required_context 门（project/catalog）+ 风险分级
  （READ/COMPUTE/WRITE）+ 权限门（WRITE 需显式授予）。

## 执行护栏

HarnessExecutor guard pipeline（schema→risk→context→admission→handler→
verify）不因新动作而绕过；`category` 取值遵守 TaskCategory 注册表
（background.io/background.compute/interactive.query）。

## 语义差异（有意）

UI ingest：`execute_unconfirmed=False`——人工确认后执行；
agent `data.ingest`：显式调用即确认（decisions 逐项覆盖），
非重复项缺省 accept。差异在**确认主体**，不在执行实现。
