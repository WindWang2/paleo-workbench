# 05 — Action Surface: Single Authority (V11)

## 权威链（不变，goal §5）

```
ToolContext（frozen 快照，~60 事实字段）
  → evaluate_tool / ToolAvailability（visible/enabled/checked/disabled_reason
      + V11: severity / remediation）
  → 四表面消费：工具条 / 画布菜单（复用工具条 QAction，结构零漂移）
              / palette（经 tool_context_from_ui_snapshot 适配）
              / 执行（每次触发 re-gate，禁用→status_message("不可用：{reason}")）
```

## V11 变更

### 1. 结构化原因（goal §7 availability ≥ enabled/visible/checked/reason/severity/remediation）

`ToolAvailability` 新增 `severity`（None/"info"/"warning"/"critical"）与 `remediation`（可操作提示），不变式扩展：enabled 判决不得携带任一字段。按事实族填充（RAW/角色/冻结/阶段白名单/只读 provider → "warning"；缺选择 → "info"），不确定即 None（保守）。

### 2. QGIS 原生栈图层树接入求值器（A1 修复——两个树两套门禁）

`qgis_stack/layer_tree_panel.py` 接受与回退树相同的 `menu_probe`/`repair_probe`；`composite_document` 构造原生栈面板时传入**同一**探针。原生树菜单的开始/停止编辑、修复按求值器判决门禁（禁用项保留可见 + tooltip「不可用：{reason}"），执行侧再 gate。删除动作按回退树同口径（editable OR raw_protected 事实），无探针时行为与旧版逐位一致。

### 3. 阶段面板动作与 palette 同因（stage panel 从不禁用的修复）

- `MappingStagePanel.set_action_availability(dict[action_id → (enabled, reason)])`：禁用行灰显（TEXT_DISABLED）+ 去掉 ItemIsEnabled + tooltip 原因；再启用恢复。
- `evaluate_stage_commands(stage_value, UIContextSnapshot)`：纯函数，镜像 palette 的阶段白名单 + 工程/授权判定（复用 `stage_vocabulary`/`stage_whitelist_reason`，不造第二词表）；未知动作保守放行（执行侧 re-gate 兜底）。
- 接线：app_shell `context_changed` → 阶段面板可用性刷新（差分，无变化不扰动）。

### 4. RAW 门禁词表合一（A3 修复——三处手写措辞）

`tool_availability.raw_layer_gate_reason()` / `frozen_layer_gate_reason()` / `stage_lock_reason()` 成为唯一措辞源（与求值器回退措辞逐字一致）；`asset_context_menu`（数据资产 RAW 编辑提示）与 `map_status_bar`（编辑 chip 提示句）改为消费共享函数。判定逻辑仍属各域（资产菜单是另一个域对象），**只有措辞**统一。

### 5. 解释层接线（A5 修复——dead explainability path）

`action_help.explain()` / `format_details()`（需求/影响/缺失前提/后台任务/快捷键）此前无任何 UI 消费方。V11：palette 的 `map:*` 工具命令在过滤渲染时经 `explain(tool, tool_context_from_ui_snapshot(ctx))` 生成 tooltip 详情；禁用原因仍以原因后缀形式内联可见。

## 边界与不做

- `action_registry` 的 `native_only`/`write_tools` 词表漂移（#1255/#1256）**归 open PR #1267**——本 goal 不改（钉测试 `test_action_registry_flags_match_evaluator_tables` 在本分支失败为预存在）。
- 遗留 mapping 页 `edit_gate_open=True` 强开门（A6）：文档化为遗留表面行为，不改。
- `CommandRegistry` 的阶段白名单决策与求值器重复（A4）：措辞已同源；决策合并需要重构 palette 适用性协议，记入 12-known-limitations。

## 测试

`tests/test_v11_action_surface.py`（22）：不变式/新字段、severity 填充、共享措辞与求值器逐字一致 + 源码扫描钉住旧字面量已从两表面移除、阶段面板禁用呈现/点击无效/恢复、evaluate_stage_commands（无工程/未知阶段/正误阶段）、原生树探针门禁与无探针旧行为、构造点探针共享。
