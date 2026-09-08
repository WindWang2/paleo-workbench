# 00 — Overlap Audit（Phase 0，编码前审计）

审计时间：2026-09-09。基线：`origin/main @ d5181cb3`（本 worktree `feat/qgis-context-control-plane-v8`）。
审计方法：全量 PR/issue 查询 + 双 subagent 逐行消费面/测试面扫描（证据 file:line 见下）。

## A. 运行时基线

- `git fetch --all --prune` 后 origin/main = `d5181cb3`（本地旧 main `836db3df` 落后 7 个提交，开发基于 origin/main）。
- **open PR = 0，draft PR = 0**。无与本 Goal 并行的新 PR 需要重叠矩阵。
- open issues（2）：
  - #1230 `[CI][P2] slow 真实数据族不进 PR 门禁 + QGIS 触发面 + #951 未修` — CI 配置项不在本 Goal 范围；其中提及的 stale-QTimer 生命周期风险列入 M8 调查。
  - #1224 `[Runtime][P2] WellLogLoadWorker/MapExportWorker 假取消` — worker 槽位问题，非工具状态权威，本 Goal 仅在 lifecycle review 中不引入同类模式。

## B. 已交付基线（禁止重复实现）

| 最近 merged PR | 交付能力 | 本 Goal 关系 |
|---|---|---|
| #1235 workstation-ux-v7 | contextual tool surface（evaluator B）、toolbar 分组/overflow、stage-aware availability、typed inspector、layer tree decorations、visual QA V7、token ratchet、palette `map:*` surface 动作 | EXTEND：B 成为 canonical 契约的呈现层；不重做 toolbar/inspector/decoration |
| #1236 qgis-native-authoring-v7 | `mapping/capability_model.py`、`tool_context.py`、`tool_availability.py`（evaluator A）、30 工具状态矩阵、native measure/identify/reshape、EditDelta、QGIS-first 校验、capability manifest | REFACTOR：A 的规则/语义并入 canonical evaluator；`capability_model.py` 保持权威 |
| #1237 qgis-geolayer-cartography-v7 | GeologicalLayerSpec V2、LayerPresentationState、scalar raster mirror、factor products、symbols、incremental publish、cartographic QA | 消费方（不改）；M5 只消费 presentation contract |
| #1231/#1206/#1201/#1200/#1198/#1199 (V5/V6) | staged workspace、grouped layer tree、QGIS-native map production、Design System V5、100k catalog、DAG harness、linked workstation | 已存在，不触碰 |
| main follow-ups `10647f0`/`c5a1d322`/`7fcf0bb1`/`d5181cb3` | submodule 指针恢复、toolbar overflow 恢复/inspector 计数/evaluator 同步修复、tool_surface 回归修复 + authoring kernel gates 集成、pipeline MultiPolygon/测试修复 | 已包含在基线 `d5181cb3` 中，不重复 |

## C. 核心架构缝（M1 证据，subagent 逐行审计结论）

当前生产工具状态实际存在 **1 个主权威 + 3 个并行权威 + 2 个死/遗留路径**：

1. **主权威**：evaluator B `ui/workstation/tool_surface.py` —
   `CompositeDocument.tool_context()`(composite_document.py:1119) →
   `availability_for_context`(tool_surface.py:366) →
   `MapActionController.apply_availability`(map_action_controller.py:165+)。
   契约：`ToolAvailability(enabled, visible, reason)` — 无 `checked`/`preferred`/`conflicts`。
2. **死代码**：evaluator A `mapping/tool_availability.py` —
   `evaluate_all` 在 composite_document.py:62 导入后**零调用**；`_build_tool_context`(composite_document.py:1768) 仅被 `tests/test_workstation_authoring_kernel.py` 调用。
   契约：`ToolAvailability(tool_id, visible, enabled, checked, disabled_reason, preferred, conflicts)`。
3. **并行权威 1**：`apply_stage_tool_profile`(composite_document.py:1091-1115) 直接 `action.setVisible(...)`（与 evaluator B 的 `_edit_action_stage_gate` 对同一 StageToolProfile 政策做两次独立推导）。
4. **并行权威 2**：host 手工改写 evaluator 输出（composite_document.py:1234-1249）：`snapping` 强制 enabled、`save_edits`/`rollback` 手写 dirty 门禁 —— 即在 B 之上重实现 A 的两条规则（B 错误地把 snapping/topology 放进 `_NEEDS_EDITING`，而 #1236 决策 D4-5 明确 snapping/topology 只需活动图层）。
5. **并行权威 3（legacy）**：`MapActionController.update_state`(map_action_controller.py:134-154) 手写 enable 矩阵，仍被 `pages/mapping_page.py:1938,1967` 在 `apply_availability` 之前调用（双权威顺序覆盖）；`MapEditToolbar`(map_edit_toolbar.py) 为 hidden shim。
6. **兼容 shim**：`getattr(result,"reason",...) or getattr(result,"disabled_reason","")`（map_action_controller.py:172、composite_document.py:3042）—— 两套契约并存的直接症状。
7. **checked 漂移**：`_sync_action_state`(composite_document.py:1792) 只读 Python 工具栈；native canvas 上 `canvas_shim.py:659-730` monkey-patch `set_active_tool` 单向写入，无 `mapToolChanged` 回读；native 激活失败仅 log + status 信号（canvas_shim.py:701-710），**UI checked 不回退**。
8. **palette 缺口**：`map:*` palette 命令仅 13 个 surface 动作（shell.py:657-668），无 `map:toggle_editing` 等核心编辑命令；执行侧 `_on_command_requested`(composite_document.py:1498-1584) 为手写 if/elif，无 execution-time re-gate。

## D. 本 Goal 提案条目判定

| 条目 | 判定 | 说明 |
|---|---|---|
| Canonical ToolState contract（M1） | **NEW/REFACTOR** | A 与 B 都存在但生产只走 B；正确终点 = 以 A 的字段语义 + B 的 IA/阶段/角色门禁合并为唯一 evaluator，落在 `mapping/` 层（Qt-free，mapping→mapping_workspace 模块级导入已有先例，无循环） |
| `mapping/capability_model.py` 权威 | KEEP | 不动（#1236 已完成） |
| TOOL_GROUPS IA | EXTEND | 移入 canonical（组可见性是可用性语义，不是皮肤） |
| evaluator A 死代码路径 | REFACTOR→ALIVE | `_build_tool_context`/`tool_context_inputs` 全量 dict 接上 canonical evaluator，`CompositeDocument` 生产路径消费 |
| stage setVisible 直接调用 | DROP-AS-DUPLICATE | 收敛进 evaluator（#1235 D9 的未竟部分） |
| snapping/dirty host 改写 | DROP-AS-DUPLICATE | 规则进 canonical evaluator |
| `update_state` legacy 矩阵 | REFACTOR | mapping_page 迁移到 canonical adapter 后降级/删除（证据化 source scan） |
| palette `map:*` 全覆盖 + re-gate | NEW | M6 |
| contextual help 派生 | NEW | M4（唯一新增 UI 面，从 contract/registry 派生） |
| layer tree/inspector 增量 | EXTEND | M5 只做 artifact-key 集中化、degraded reason 等增量 |
| visual QA v8 states | EXTEND | M7 在 visual_qa_v7 harness 上加状态 |
| perf/lifecycle 预算 | EXTEND | M8（复用 test_perf_bounds_v7 / test_v7_stability_probes 模式） |
| 100GB seismic 任何形式 | OUT OF SCOPE | 明确排除 |

## E. Changed-file ownership / 冲突风险

- 本方向主 ownership：`paleo_workbench/ui/**`、`paleo_workbench/ui/workstation/**`、`paleo_workbench/mapping/tool_*.py`（contract-level）、`tests/test_tool_surface*.py`、`tests/test_authoring_contracts.py`、visual QA。
- 对方向 B（bridge）只消费 `capability_manifest` 既有契约；`native/qgis_render_bridge/**` 不改。`ui/qgis_stack/canvas_shim.py` 属 UI 侧，仅加窄的工具状态回读/失败回调（不新增 bridge API）。
- 不触碰：科学算法、DataCatalog、geological_pipeline（`d5181cb3` 刚修过）、submodules。

## F. 测试基线（本地验收方式）

- 快速门：`QT_QPA_PLATFORM=offscreen python -m pytest -m "not slow and not welllog_binding" --ignore=tests/perf`（pytest-qt，`qt_api=pyside6`，per-test timeout 45s）。
- 本机全量易崩 → 用 `scripts/run_suite_batched.py`（每文件一进程 + 崩溃重试）。
- 语义 visual QA：`pytest tests/test_visual_qa_v6.py tests/test_visual_qa_v7.py`；像素 diff 从不是门禁（v6 D8 决策）。
- 既有契约钉子：`tests/test_authoring_contracts.py`（钉 A）、`tests/test_tool_surface.py`（钉 B）、`tests/test_workstation_authoring_kernel.py`（A×CompositeDocument 集成，生产死路径的测试）、`tests/test_tool_surface_integration.py`（B×QAction 集成）、`tests/test_stage_tool_filtering.py`、`tests/test_mapping_stage_ui.py`、`tests/test_ui_context_model.py`、`tests/test_toolbar_overflow_v7.py`。

结论：无 open PR 重叠；本 Goal 的全部增量 = 把"单一真源"从口号变成事实（A 并入 canonical、3 个并行权威拆除），并在唯一契约上补 M2 矩阵、M4 explainability、M6/M7/M8 收敛。**允许进入实现。**
