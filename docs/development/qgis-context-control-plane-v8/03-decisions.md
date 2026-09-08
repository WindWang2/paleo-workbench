# 03 — Decisions（V8）

D1 **canonical evaluator 落在 `mapping/`**。Qt-free、headless 可测；
mapping→mapping_workspace 模块级导入已有先例（factor_layer_products 等），
无循环（mapping_workspace 对 mapping 只有函数级导入）。UI 层
`tool_surface.py` 降级为 presentation adapter（re-export + 快照适配 +
呈现词表），禁止再出现第二套 gate 规则。

D2 **ToolContext v2 扁平化 + 三态 stage**。B 的嵌套 LayerCapabilitySnapshot
输入改扁平图层事实字段；`mapping_stage=None`（无阶段语义，legacy 编图页）
不过滤，`""`/未知值 fail-closed（非基础组隐藏、受治理动作禁用）。修复了
B 内部「evaluator 对未知阶段不做组过滤 / public helper 却 fail-closed」
的自相矛盾——统一为 fail-closed。

D3 **blocking task 集中裁决**。原 A 的 per-rule blocking gate 顺序不一
（save/rollback/undo 甚至没有 project/layer gate），原 B 完全没有
blocking gate。统一为 evaluate_tool 内除 cancel 外全阻断（A 的 D 决策
语义），reason 固定「后台任务进行中：{task}」。

D4 **session 工具无图层时 visible+disabled**（B 语义）而非 A 的 invisible。
专业工作站的发现性优先：按钮在、灰的、hover 有原因；QGIS/Petrel 同惯例。
A 的 `_SESSION_TOOL_IDS` 隐形行为废弃。

D5 **snapping/topology 只需活动图层**（#1236 D4-5）。修复 B 错误要求编辑
会话导致 host 必须强制改写 evaluator 输出（原 composite_document
1234-1249 手写规则）——手写规则删除，归并入 evaluator。

D6 **save/rollback dirty 门禁并入 evaluator**（原 host 手写第二处）。
palette 快照因此新增 editing_dirty/selection_count/can_undo/can_redo/
blocking_task providers——palette 与工具条同因的前提是快照携带同样的
事实；执行侧 re-gate（新鲜全量求值）兜底呈现层的任何保守近似。

D7 **stage 可见性单点推导**。删除 `apply_stage_tool_profile` 的直接
`setVisible`（并行权威 1）与 A 的 `hidden_by_stage_profile` 宿主预计算
输入；evaluator 直接读 `StageToolProfile.edit_actions`/`governed_edit_actions`。
阶段切换 = set_stage + `_sync_action_state()`。

D8 **checked 与原生工具可检测一致**。canvas_shim 记录最近成功激活的原生
工具（`active_map_tool_id()`）并在 `set_map_tool` 异常时发射
`native_tool_activation_failed(tool_id, reason)`；CompositeDocument 收到后
回退 pan + status message。不新增 bridge API（V8 对方向 B 的 ownership
承诺）；fallback 画布声明同名信号（永不发射）保持宿主鸭子类型统一。

D9 **execution-time re-gate**。`_on_command_requested` 顶部用**新鲜**
`tool_availability()` 复查（不用可能过期的 `_last_availability`）——
shortcut/palette/工具条三表面共用单一受门禁执行路径；画布工具命令
（identify/measure/add_* 等）并入同一 dispatch。

D10 **palette 覆盖增量**。`map:*` 从 13 个 surface 动作扩到 +11 个核心
编辑/会话/检查命令（含 `map:toggle_editing`）。split/merge/reshape 刻意
不进 palette：其前置条件依赖会话几何细节（split_ready/merge_ready），
palette 快照无法诚实判定——宁可少覆盖也不给假可用/假禁用。修复
`active_layer_role` provider 喂 label 导致线/面角色反抢主位门禁在
palette 侧从未生效的隐性 bug（现在喂 LayerRole.value）。

D11 **repair_geometry 进 vocabulary + context menu 消费 evaluator**。
原 LayerManagerPanel._repair_available 自建 kind 判断（并行规则）→ 改为
宿主探针 `_layer_repair_availability`（把目标图层事实投影进 ToolContext
再求值），右键菜单与工具条/palette 同规则。

D12 **M4 help 全派生**。`action_help.py`：静态登记处（45 工具的前置
条件/影响/改数据/新版本/后台任务/快捷键/阶段/图层类型，测试钉完整性）
+ 动态结论（missing = evaluator 判词原样）。tooltip/statusTip/palette
hint/`CompositeDocument.explain_action`（Inspector/Agent 用）统一消费。

D13 **artifact-key 唯一构造点**（M5）。`mapping_workspace/artifact_keys.py`
统一 phase1_draft:/factor:/integrated: 构造与候选顺序，替换 4 处重复。

D14 **MapActionState/update_state/action_state 证据化删除**。生产零消费
（mapping_page 迁移后）；`action_state()` 保留为 dict 兼容别名（测试仍
用其语义断言）。

D15 **「无工程」不是可达工作站状态**。`PaleoWorkbenchWindow(project=None)`
自动创建 Untitled 工程——M2 的 no-project 门禁在纯函数层验证
（project_open=False），视觉 QA 用「空工程表面」状态（图层门禁原因可见
+ 空画布引导）表达诚实形态。
