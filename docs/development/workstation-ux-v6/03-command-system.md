# Workstation UX V6 — 03 命令系统（单一注册表 + 适用性）

Date: 2026-09-07 · Module: `paleo_workbench/ui/command_registry.py`（扩展，未建第二套）

## 1. 原则：一处定义，多面呈现

命令只有 `CommandRegistry` 一个真源；palette / 面板菜单 / 阶段面板动作都是呈现面。地图工具条保持 `MapActionController` 为 QAction 权威（V6 只做可见性过滤，不建第二套 QAction）。

## 2. CommandSpec 适用性元数据（V6 新增，全部可选、V5 兼容）

```python
context_tags: tuple[str, ...]        # 发现标签（fuzzy haystack 一部分）
stages: tuple[str, ...]              # 编图阶段白名单；空 = 全阶段
requires_write: bool                 # 需会话 WRITE 授权
hidden_when_unavailable: bool        # 不可用时隐藏（默认保留+原因——可发现性优先）
applicability: ctx -> None | 原因    # 领域谓词，在权限/阶段门之后求值
```

`evaluate(command_id, context)` 判定顺序：存在性 → WRITE 授权 → 阶段白名单（**未知阶段 fail-closed**，review round 1）→ 领域谓词（谓词异常按「无法判定」禁用）。无 context = 全可用（V5 逐字节兼容路径）。

## 3. 呈现面行为

- **palette**（`app_shell.CommandPalette` + `context_provider`）：禁用命令灰显 + 原因后缀（`（当前编图阶段不可用…）`），不可激活；`hidden_when_unavailable` 的命令按上下文移除。模糊匹配把 context_tags 并入 haystack（"mapping" 可命中 `等值线`）。
- **工具条阶段过滤**（`CompositeDocument.apply_stage_tool_profile`）：受治理全集 = 各阶段 `edit_actions` 并集（`governed_edit_actions()`）；阶段1 隐藏 `add_line`、阶段2/3 开放；`add_point` 不在任何 profile 并集内 → 不受阶段治理；导航/识别/选择永不隐藏。构造与切阶段都应用（恢复持久化阶段同样生效）。
- **阶段面板动作入 palette**：`stage:<stage>:<action>`（标签前缀「阶段动作 · 」避免与导航命令抢分），阶段限定；标签不再双份硬编码的面板列表（面板仍持有自己的按钮文案，动作 id 单源 = `StageToolProfile.context_actions` 的 dispatcher）。
- **窗口级领域命令**：`workflow:recompute`（更新受影响成果）由 `app.py _register_window_commands` 注册——首个 chrome 之外的领域命令，修复 baseline F-P1-2 孤儿流。

## 4. 快捷键纪律

所有应用级快捷键经 `ui/shortcuts.py register_shortcut`（含 Ctrl+S/N/O/F——此前直接 QShortcut 双绑，已收敛为一绑 + 冲突检测覆盖）。文本输入守卫与冲突告警保持 V5 行为。

## 5. 测试

`tests/test_ui_context_model.py`（适用性判定/失败路径/标签匹配）、`tests/test_palette_context.py`（渲染/拦截/无上下文兼容）、`tests/test_stage_tool_filtering.py`（阶段过滤 + shell 接线）、`tests/test_agent_ux_v6.py`（recompute 注册）。
