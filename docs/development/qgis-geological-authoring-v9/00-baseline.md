# 00 — Baseline（V9）

执行时间：2026-09-10。基线 `origin/main = 39bc1147`（本地 main 已 ff 同步；
V8 三 PR #1238/#1239/#1240 + review 修复 #1246/#1247 + mapping-stage 收敛与
mock 相面预测均已合入）。worktree：
`../paleo-workbench-qgis-authoring-v9`，分支 `feat/qgis-geological-authoring-v9`。

## A. 运行时状态

- **Open PR：0**；closed 最新 #1247（QTimer segfault 修复 + P2 清理）。
- **并行 worktree**：v7 系三个（已合并）、v8 系三个（已合并）——全部无未合并提交，
  与本分支无冲突面。
- **测试环境**：worktree 自建 `.venv`（Python 3.12.13 + PySide6 6.8.3 + pybind11
  3.1.0），桥构建复用
  `paleo-workbench/.worktrees/qgis-native-authoring-v7/native/qgis_render_bridge/build/qgis-vendor`
  （`PALEO_QGIS_REUSE_VENDOR=1`，链桥 ≈5–10 min，见
  docs/development/qgis-geolayer-cartography-v7/06-performance.md）。入口
  `scripts/run_qgis_env.py`（v8 配方，vendor bin → PySide6 单 Qt 规则）。
- **基线测试**：`tests/test_authoring_contracts.py` +
  `tests/test_tool_state_contract_v8.py` = 165 passed / 1 skipped（全绿；
  初次 1 失败为本 venv 缺 scipy/segyio/pyqtgraph/PyOpenGL，补装后通过——
  环境性，非代码回归）。

## B. 已交付基线（禁止重做）

| 来源 | 已交付 | 证据 |
|---|---|---|
| V7 #1236 | capability manifest/snapshot、ToolContext v2、45 工具 canonical evaluator、native identify/select/measure、reshape、endpoint/intersection snap、QGIS-first validate、EditDelta | `mapping/capability_model.py`、`tool_context.py`、`tool_availability.py` |
| V7 #1237 | GeologicalLayerSpec V2（27 roles）、geometry facade、标量栅格镜像、LayerPresentationState、增量发布 ledger、QgsPrintLayout 原生映射 | `mapping_workspace/geological_layer_spec.py`、`mapping/geometry_operations.py` |
| V8 #1238 | provider fields（fields_json→QgsFields/约束/控件）、compound topology undo、duplicate-GIS 收敛（PIP/bbox 迁移）、行指示器、legend filter、lifecycle 守卫 | `qgis_layer_schema.py`、`topology.py`、`map_stack_service.cpp` |
| V8 #1239/#1240 | 科学工作流版本化约束、context control plane（工具面同步、命令面板、状态语言） | `ui/workstation/*` |
| #1246/#1247 | review 缺陷修复、QTimer.singleShot context 绑定（#951 产品侧） | `runtime/`、`ui/qgis_stack/events.py` |
| 39bc1147 | RegistryBridgeDetach 修复、mock 相面预测、identify 无活动层门禁 + 点击弹窗、基础层 label schema | `qgis_mirror.py`、`well_prediction_surface.py`、`canvas_shim.py` |

## C. 本轮审计结论（两轮独立 subagent 审计 + 主 agent 复核）

### C1 — 工具/交互面审计要点

- evaluator 单一性成立：`tool_availability.py` 是唯一门禁真源；`tool_surface.py`
  只是 presentation adapter；执行前 re-gate 全表面覆盖（toolbar/palette/shortcut/
  context menu/stage panel 经 `_on_command_requested` 单一入口）。
- **缺口（P0）**：
  1. `topology_error_count` 生产运行时无生产者——merge 的拓扑门
     （tool_availability.py:548）永远不触发；
  2. `blocking_task` 仅 visual-QA harness 写入——全局 blocking 门在生产中死代码；
  3. `project_crs`/`layer_crs`/`scale` 不在 ToolContext（只有 `crs_valid` 布尔）。
- **缺口（P1）**：`snapping_available`/`topology_available` 硬编码 True；
  `vector_writable` 是 `layer is not None` 猜测；QGIS `topologicalEditing`
  未推送到原生画布（桥内 grep 阴性）；测量 fallback 平面度数（`math.dist`）；
  `write_granted` 契约面无生产者/无消费者；split/merge/reshape readiness
  每次上下文构建 O(layers) 重算（帧级链上）。
- **缺口（P2）**：per-LayerRole snapping 推荐完全缺失（goal §18 显式要求）；
  图层树右键编辑动作只过 `_role_allows_editing` 单点门禁（不过 blocking）。

### C2 — 几何/图层/CRS 审计要点

- **缺口（P0）**：
  1. attribute table 两套 Python widget 实现（`map_attribute_table.py`、
     `composite_attribute_table.py`），完全不消费 QGIS provider schema——
     V8 M1 建的 ValueMap/Range/CheckBox/约束在 UI 无消费者；
  2. published fields 无生产验证——`mirrorLayerSchemaJson` 仅测试消费，
     发布路径不比对 spec；
  3. 工作站编辑层永远无 role（`create_layer` metadata 无 role、role 只在
     stage membership）→ `_fields_json_for_metadata` 静默返回 "" → 编辑层
     永不物化 QgsFields；TypeError 重试丢弃 fields_json 无诊断；
  4. CRS：8 处 quiet-4326 默认 + `qgis_mirror._geographic_auth` 第二套
     （窄化）地理谓词 + extent 不合时静默丢 CRS 无诊断；无统一 CRS 契约模块。
- **缺口（P1）**：交互命中测试直连 `geometry_planar` 内核绕过 facade（共享
  内核本身是 V8 决策保留，但 `feature_query_index._intersects` 自带 AABB
  是真重复）；`singlepart_to_multipart` 纯 dict 路径误标 `ENGINE_SHAPELY`；
  数字化提交假设 canvas CRS == layer storage CRS（无守卫）。
- **保留（V8 已裁定，不动）**：PIP/bbox 共享内核为热路径宿主权威；
  fallback 双视觉栈为 documented gate；LayerGroupController 平行 desired-tree
  为组权威（QgsLayerTree 执行）。

## D. V9 范围（据此裁定）

| 工作包 | 内容 | 级别 |
|---|---|---|
| W1 | ToolContext v3：补 `project_crs`/`layer_crs`/`scale_denominator` 事实 + `snapping_available`/`topology_available` 桥能力派生 + `blocking_task` 生产生产者（scheduler 派生） | P0 |
| W2 | 拓扑深度：运行时 `topology_error_count` 生产者（编辑后失效缓存）+ QGIS `topologicalEditing` 推送（C++ 扩展 + manifest flag + 旧桥诚实降级） | P0 |
| W3 | CRS 契约统一：`mapping/crs_contract.py` 单一谓词/解析权威；qgis_mirror 谓词去重 + 静默丢 CRS 加诊断 | P0 |
| W4 | per-LayerRole snapping profile（FACIES_BOUNDARY/FAULT/SOURCE_DIRECTION/SHORELINE…）：可解释、可改、推荐非硬编码 | P1 |
| W5 | attribute table 消费 QGIS provider schema：别名表头、ValueMap/CheckBox/Range 编辑器、约束反馈、数值感知排序；QgsDualView 评估决策记录 | P0 |
| W6 | provider schema 生产验证：发布后 `mirrorLayerSchemaJson` 比对 + 漂移诊断；编辑层 role 标注（文档级单权威派生）+ fields 诊断补齐 | P0 |
| W7 | facade 收敛余项：`feature_query_index` AABB → facade；引擎标注修复；数字化提交 CRS 守卫 | P1 |
| W8 | 测量 fallback 测地化（pyproj.Geod，地理 CRS）+ 单位标注；lifecycle 压测扩展 | P1 |
| W9 | 捕获语义适配（goal §6/§12）：`GeologicalCaptureSpec`——role 派生模板字段/默认属性/snapping 推荐/样式提示，`create_layer`/`_create_role_layer` 单通道 | P1 |
| W10 | 性能：split/merge/reshape readiness 失效缓存；perf 门复跑 | P1 |

### 硬排除（沿 goal 约束）

- 100GB seismic：任何形式新增支持/基准 = 禁止。
- 新第二 evaluator / 第二 ToolAvailability / 第二 layer tree authority / Python
  复刻 QgsRubberBand 捕获（fallback 状态机为 sanctioned 路径，不扩能力）：禁止。
- QgsDualView 全托管（C++ 宿主面板）本批不做——记录评估决策（05 文档），
  Python 表格以 QGIS provider schema 事实驱动的 honest 消费者收编。
- vendored QGIS 重建：禁止（复用既有 vendor build，仅链桥扩展）。

## E. 执行顺序（编译预算约束）

C++ 改动（W2 topologicalEditing + W1 mapScale getter + manifest flag +
版本 0.5.0a0）合为**一次桥批次**；host 侧 W1/W3/W4/W6/W7/W8/W9/W10 纯 Python
可先行并在桥批次后并联验证。
