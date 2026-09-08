# 02 — Architecture（V7 实施架构）

原则：扩展现有权威（CommandRegistry / UIContextService / StageToolProfile /
MapActionController / tokens / state_language），不建第二套。新增代码集中在
`paleo_workbench/ui/workstation/tool_surface.py`（纯 Python，可无 Qt 测试）与
各消费表面的接线。

## 1. 模块图（新增/改动）

```text
mapping_workspace/（域权威，最小改动）
  stages.py · layer_roles.py · stage_profiles.py · stage_state.py   [不动语义]
    └─ stage_profiles.StageToolProfile                              [V7: 词表派生见 §4]

ui/workstation/tool_surface.py                      [新增 — V7 核心]
  QgisCapabilitySnapshot   (mode: native|degraded|unavailable + reason)
  LayerCapabilitySnapshot  (id/name/role/kind/maturity/editable/block_reason/
                            frozen/missing/degraded/selection-aware 字段)
  ToolContext              (上述 + stage/editing/dirty/selection/undo/extent/
                            capability/write_granted/topology_error_count/…)
  ToolAvailability         (enabled/visible/reason)
  evaluate_tool(tool_id, ctx) -> ToolAvailability        [纯函数, 全矩阵]
  TOOL_GROUPS              (专业分组 IA: navigate/select/inspect/edit_session/
                            capture/geometry/snapping/layer/symbology/factor/
                            qa/layout_export)
  availability_for_context(ctx) -> dict[tool_id, ToolAvailability]

ui/workstation/ui_context.py                        [扩展]
  UIContextSnapshot 增字段: active_layer_kind / active_layer_role_label /
  dirty / capability_mode / capability_reason / topology_error_count /
  factor_task_running(bool)（仍为派生只读；provider 来自 composite/seam）

ui/map_action_controller.py                         [扩展]
  apply_availability(dict[id, ToolAvailability])     [enabled+visible+reason→
   tooltip/statusTip/accessibleName 统一渲染；update_state 保留勾选态职责]

ui/workstation/composite_document.py                [改造]
  _build_toolbar → TOOL_GROUPS 驱动（组级 stage/layer 可见性、compact、overflow）
  _sync_action_state → 构造 ToolContext → evaluate_tool → apply_availability
  （split 的特殊条件并入 evaluator 的输入，不再二次改 enable）
  apply_stage_tool_profile → 保留（可见性由 evaluator+group 统一后仍以
  profile.edit_actions 为阶段语义真源）

ui/pages/mapping_page.py                             [收敛第二权威]
  其 MapActionController 状态喂给改为同一 evaluate_tool（适配其自有编辑栈
  → ToolContext adapter）；不再维护独立 enable 规则

ui/workstation/shell.py                              [扩展]
  阶段面板按钮/面板菜单/右键菜单动作 → 统一从 availability 或 CommandSpec
  applicability 派生（单一字符串源）

ui/command_registry.py                               [激活]
  stage:* palette 命令与新增 map:* 命令注册 applicability 谓词 = 同一
  evaluator（ctx→reason）；requires_write 首批真实消费者（导出/发布类）

ui/workstation/layer_decorations.py                  [新增]
  LayerPresentationState (frozen/published/stale/error/qc_count/dirty/
  reviewed/missing/degraded/running…) ← group_controller + membership +
  freshness + maturity 聚合（消费现有权威）
  decoration_token(state) -> StateToken（state_language 扩 vocabulary）
  两棵树共用渲染：LayerManagerPanel(QTreeWidget 列/图标/delegate) +
  QgisLayerTreePanel（Python 侧能及的表面 + hover/摘要行；桥侧仅既有铅笔
  指示器——不扩 C++）

ui/workstation/inspector.py                          [类型化]
  show_layer/show_feature/show_factor_raster/show_map_product 结构化分节；
  数据来自 layer_domain_status / edit_controller.layer / factor tasks +
  live grid peek / MapProduct publish 状态（消费现有域，不伪造）

ui/workstation/state_language.py                     [扩词汇]
  新 category: presentation(frozen/published/missing/degraded/dirty/
  reviewed/qc_count)；tone 语法统一映射到 PwbBadge tones（桥接表）
```

## 2. 可用性求值顺序（evaluate_tool 内部）

1. capability gate：需要 QGIS 原生后端的工具（layer properties native /
   symbology native 等）在 unavailable 时 disabled+原因（fallback 可用的
   工具不受影响——如实区分）。
2. context gate：无工程 / 无活动图层 / 图层 missing 或 degraded。
3. role gate：RAW/受保护角色 → 矢量编辑类 disabled+RAW 原因；frozen/published
   → disabled+冻结原因；stage lock → 证据锁定原因。
4. stage gate：StageToolProfile（edit_actions 并集内）→ 阶段外 hidden
  （工具条）/ palette 侧 disabled+阶段原因（沿用 V6 的 hide vs disable 分工）。
5. kind gate：add_point/add_line/add_polygon 与活动图层 kind 不匹配 →
   disabled+几何原因（§4.2 主捕获工具矩阵）。
6. editing gate：需会话的工具（save/rollback/undo/redo/capture/move/vertex/
   delete/split/merge/snapping/topology）→ 未开始编辑 disabled+原因。
7. selection gate：delete/split 需选择；merge 需 ≥2 兼容多边形；拓扑错误
   阻断 merge（如有计数）。
8. write gate：导出/发布类命令 requires_write → 未授权 disabled+授权原因。

每条规则产生**唯一优先级最高的原因**（先到先得，顺序即优先级），保证四个
表面（tooltip/status/palette/inspector）一致。

## 3. ToolContext 构造路径

CompositeDocument 持有全部权威（edit_controller / stage_controller / canvas /
reference layers）→ `build_tool_context()` 每 state_changed/selection/stage/
capability 事件时构造（廉价 frozen dataclass，无 Qt 调用），既喂
action_controller.apply_availability，也经 provider 喂 UIContextService（palette）。
MappingPage 用 `build_tool_context_from()`（同构 adapter）保证一致语义。

## 4. 三套阶段词表的统一（不新增第四套）

- `StageToolProfile.edit_actions` 保持**阶段语义真源**（mapping_workspace 域）。
- `MappingStagePanel._PHASEn_ACTIONS` 改为从 dispatcher 暴露的
  `stage_context_actions(stage)` 表派生（id/label/cb 单点）；palette 注册
  shell 循环同一表 → 面板按钮与 palette 天然同步。
- `StageToolProfile.context_actions` 死 id 清理：仅保留 dispatcher 实现的；
  未实现的从 profile 删除（诚实）。
- `command_groups` 删除（0 消费者）→ TOOL_GROUPS（UI 层 IA）接管分组概念，
  profile 不再重复声明。

## 5. 图层树装饰通道

- 域侧 `LayerPresentationState` 聚合（layer_decorations.py）是唯一装饰真源；
  组级 `group_summary()`（已存在）扩展 running/pending factor + published/
  frozen 摘要。
- 回退树（LayerManagerPanel, QTreeWidget）：状态列（SVG icon + 数量角标 +
  accessibleName 文本）+ 组行摘要 + hover tooltip + 双击定位。
- 原生树（QgisLayerTreePanel）：Python 侧面板头/摘要行 + tooltip 通道；
  图层行内装饰受桥能力限制（当前仅铅笔指示器）——如实文档化，不伪造。
- 树更新走差分（结构 snapshot diff 已有 tree_sync 基础；QTreeWidget 侧
  按 layer_id 对齐更新，不全清重建）。

## 6. 状态词汇统一

- canonical = `state_language.StateToken`（UI 状态）+ `tokens.STATUS_TEXT/
  TASK_STATUS/QC_RESULT`（数据状态）。
- 新增 tone 映射表：state_language.tone ↔ PwbBadge tone（one-way 桥）。
- 9 个本地 `_STATUS*` 方言迁移为导入 canonical（import-lint ratchet 禁止
  新建本地状态映射）。

## 7. 视觉 QA V7

- `visual_qa_v7.py`（ui/ 下，沿用 v6 模式）：新状态 driver + semantic checks。
- 矩阵：4 尺寸 × 3 主题 × 2 密度按状态选择性组合（全笛卡尔不必要；每状态
  至少 light+dark，关键状态 +HC）。
- 语义断言 hard-gate 于 `tests/test_visual_qa_v7.py`；pixel diff 仍 non-gating
 （V5 D8 政策延续）。
- 修复 `--update-baseline` 死旗标（删除或实现）。

## 8. 明确不做（本 Goal）

- 不构建 qgis_render_bridge（保持 main 同构环境；桥侧能力以既有 API 为界）。
- 不改 native/qgis_render_bridge C++。
- 不做 100GB seismic 相关任何项。
- 不重写 QGIS Symbol Selector/Renderer/Style Manager 内部（只做入口+门禁）。
- 不删除 5-hub 页面架构本身（120 active 页面仍是生产面；只清死页与接缝）。
