# 02 — Architecture：Canonical Tool State Contract（M1）

## 现状（审计证据见 00-overlap-audit.md §C）

生产工具状态 = evaluator B（`ui/workstation/tool_surface.py`）+ 3 个并行权威
（stage setVisible 直写 / host 改写 B 输出 / legacy `update_state` 矩阵）；
evaluator A（`mapping/tool_availability.py`）在生产是死代码。
两套 `ToolAvailability` 契约（`reason` vs `disabled_reason`；B 无 `checked`）。

## 目标架构

```
QGIS capability manifest (capability_model.py, 不动)
+ project + active layer facts (role/kind/maturity/frozen/missing/degraded)
+ role/stage/maturity 门禁结论 (CompositeDocument._role_allows_editing —— 文本权威)
+ edit session + selection + dirty + undo + snapping/topology + blocking task
+ current tool + extent history + backend 三态
                 ↓ host 只做「采集」（tool_context_inputs / action_state / 图层事实）
        Canonical ToolContext  (mapping/tool_context.py, contract_version=2)
                 ↓ 纯函数、无 Qt
        Canonical ToolAvailability (visible/enabled/checked/preferred/conflicts/disabled_reason)
        evaluator: mapping/tool_availability.py  ←—— 唯一业务真源
                 ↓
  toolbar / overflow / context menu / palette / shortcuts / stage panel
  status bar / inspector / agent surface —— 全部是 presentation projection
  (ui/workstation/tool_surface.py 只剩 adapter：re-export + UIContextSnapshot 适配 + 呈现词汇)
```

## 关键决策

1. **canonical evaluator 落在 `paleo_workbench/mapping/`**：Qt-free、headless 可测；
   mapping→mapping_workspace 模块级导入已有先例（factor_layer_products 等），
   mapping_workspace 对 mapping 只有函数级惰性导入，无环。
2. **ToolContext v2 字段扁平化**：B 的嵌套 `LayerCapabilitySnapshot` 输入改为扁平
   图层事实字段（role/kind/maturity/frozen/missing/degraded/name/label/writable）。
   UIContextSnapshot（V6 palette 上下文）经 `tool_context_from_ui_snapshot` 适配。
3. **stage 三态**：`mapping_stage=None`（表面无阶段语义，legacy 编图页）→ 不做组过滤；
   `""` 或未知值 → fail-closed（组只留基础，动作禁用+原因）。
4. **stage 过滤在 evaluator 内部推导**（单一推导）：直接读
   `StageToolProfile.edit_actions` / `governed_edit_actions`；删除 A 的
   `hidden_by_stage_profile` 宿主预计算输入，删除 `apply_stage_tool_profile`
   的 setVisible 直写（阶段切换 → 重求值）。
5. **禁用原因优先序**：宿主门禁判词 `edit_gate_reason`（权威文本）→ 事实分类
   （missing/degraded/frozen/raw_locked/stage_locked 的具体文案）→ 兜底文案。
   UI 永不自己猜原因。
6. **snapping/topology 只需活动图层**（#1236 D4-5；修复 B 错误地要求编辑会话导致
   host 强制改写）；**save_edits/rollback 受 dirty 约束进 evaluator**
   （删除 host 手写规则）。
7. **checked 语义**：canvas 工具 ← `current_tool`；toggle_editing ← editing；
   snapping/topology ← 控制器开关。native 画布上实际 QgsMapTool 由
   `canvas_shim` 记录 `last-set` 结果并在**激活失败时发信号**：UI 回退 pan +
   状态条原因（可检测一致；不新增 bridge API）。
8. **门禁顺序**（coarse→fine，先到先得）：未知工具 → blocking task（除 cancel）→
   project（除 cancel）→ native-only 能力 → 图层存在/缺失/降级 → 角色门禁 →
   阶段（组隐藏→动作白名单→受治理编辑动作）→ 会话 → 几何/角色捕获 →
   原生 manifest → 选择/输入 → 历史/选择命令。
9. **tool id 命名空间 = 45 个**（B 的 44 + `repair_geometry`）；`TOOL_GROUPS`
   IA 移入 canonical（组可见性是可用性语义）。`MapActionController._LABELS`
   继续承担图标/标签呈现词表。
10. **执行期 re-gate**：`CompositeDocument._on_command_requested` 顶部按 canonical
    availability 复查（禁用 → status message + return）——shortcut/palette 无旁路。
11. **兼容别名过渡**：canonical `ToolAvailability.disabled_reason` 提供 `reason`
    property；`tool_surface` re-export canonical 符号；消费者与测试迁移后删除
    `update_state`/`MapActionState`（证据：source scan + 测试更新）。
