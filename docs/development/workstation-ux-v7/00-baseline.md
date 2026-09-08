# 00 — Baseline（V7 起点，只读审计）

- 基线：`main` @ `db21f6cf`（2026-09-08 fetch 后与 origin/main 一致）
- 分支：`feat/workstation-ux-v7`（worktree `.worktrees/workstation-ux-v7`）
- 审计方式：5 路并行源码审计（命令面 / 页面与 dock / 视觉债务 / 上下文与状态服务 /
  视觉 QA 与既有目标文档），全部结论带 file:line 证据；本文件为整理后的结论层。

## 1. 现有权威（production consumer，V7 必须扩展而非重建）

| 权威 | 位置 | 状态 |
|---|---|---|
| Design tokens / QSS / 主题 / 密度 | `paleo_workbench/tokens.py` + `ui/theme.py` + `ui/style.py` | 真源健康；light/dark/high_contrast × compact/comfortable 已接线 |
| CommandRegistry（palette 真源） | `ui/command_registry.py` | 48 命令；V6 适用性机制（stages/requires_write/applicability/hidden_when_unavailable）**已建未用**（0 个生产注册使用后三者） |
| UIContextService | `ui/workstation/ui_context.py` | 真服务；15 字段快照；仅 palette + 状态条消费 |
| MapActionController | `ui/map_action_controller.py` | 30 QAction（12 互斥工具 + 18 命令）；`MapActionState` 8 字段，无 stage/role/write/capability 输入，无禁用原因 |
| StageToolProfile | `mapping_workspace/stage_profiles.py` | 只治理工具条**可见性**；与阶段面板按钮表、dispatcher 处理表构成 3 套平行词表 |
| RAW/证据锁门禁 | `composite_document._role_allows_editing` | 单点门禁，带人类可读原因（好范式） |
| LayerRole / ArtifactMaturity / MappingStage / FreshnessStatus | `mapping_workspace/*` | 域权威健全；树面板未消费 role（用字符串标志） |
| TaskScheduler | `runtime/task_scheduler.py` | 真协作取消（Event + check_cancelled + sleep_interruptible） |
| layer tree 权威 | `QgisLayerTreePanel`（原生）+ `LayerManagerPanel`（回退）+ 域侧 `LayerTreeSnapshot` | 五套树实现并存（另 2 套在 legacy 页面） |

## 2. 主要缺陷登记（V7 要修的）

### 命令/工具面
- **C1 (P0)** 工具可用性无统一真源：工具条/菜单/右键/palette 各自判断；
  `MapActionState` 缺 stage、role、几何类型、raster、write、capability 维度。
- **C2 (P0)** 禁用无原因：QAction 无 reason 语义；palette 有机制但
  `applicability` 0 生产使用。
- **C3 (P1)** 第二权威：`MappingPage` 自建 `MapActionController` +
  编辑栈（与 CompositeDocument 平行）；`CompositeDocument._sync_action_state`
  在控制器外二次改 enable（split）与 checked。
- **C4 (P1)** 3 套阶段词表（profile.edit_actions / 面板 _PHASEn_ACTIONS /
  dispatcher map）互不推导；`command_groups`、半数 `context_actions` 无任何消费者（死元数据）。
- **C5 (P2)** 死动作：composite 面里 `refresh/clear_selection/select_all/invert_selection`
  创建但不可达；`MapEditToolbar` 永久隐藏 shim 全接线；`register_meta` 死代码；
  QMenuBar 无实例但 tokens 有规则。
- **C6 (P2)** 快捷键：14 条在中央注册表，11 条在外（QAction × 2 实例 + data_page）；
  `conflicts()` 看不见外部绑定；文本输入守卫双份且类型清单不一致。

### 页面 / 布局
- **L1 (P0)** Hub force-float 遗留：整个 5-hub 页面栈住在 `hub_dock`，每次导航强制
  浮动（`shell.py:705-709`）；preset 全部 hub=False；预设定制追踪排除之 —— 双架构接缝。
- **L2 (P1)** 死页面/死 preset：`fallback_preview`（0 引用）、`well_seismic_joint_page`
  （仅字符串引用）、7 个 test-only 页面、4 个死 `WorkspacePreset` 枚举、
  `float_visible` 死字段、`screen_inventory.py` 陈述与现状不符（测试钉住旧 11 页）。
- **L3 (P1)** 双 dock 架构（host QDockWidget vs 页内 FloatController/FloatingPanel）+
  双 preset 系统 + 3 份"页面清单"（screen_inventory / navigation / explorer 硬编码）。
- **L4 (P2)** 无 1366×768 处理；无 DPR>1；窗口默认 1440×900。

### 视觉系统
- **V1 (P0)** 主题切换留残影：44 文件在构造期内插 light-token 常量且无 `style.bind`
  （最重 `geological_modeling_3d_page.py` 47 处 / 20 字号字面量）。
- **V2 (P0)** ratchet 现红：`agent_panel.py` 3>2、`curve_operation_dialog.py:155` 1>0。
- **V3 (P1)** 104 处字面 font-size；42 处字面定宽（220/240 侧栏 fights reflow）。
- **V4 (P1)** 表情符号 43 行 + 符号字形 99 行绕过 50+ SVG 图标库。
- **V5 (P1)** 状态词汇 9+ 方言、3 套 tone 语法、8 种徽章实现、4 种空态/3 种加载态
  方言；PwbBadge/PwbEmptyState/PwbErrorState 采用率≈0。
- **V6 (P2)** 302 objectName 中 118 有 tokens 规则；12 条 tokens #id 无 setter（死规则）。

### 图层树 / Inspector
- **T1 (P0)** 树无状态装饰：仅"编辑中"铅笔；dirty/stale/error/reviewed/frozen/
  published/missing/degraded 全缺；`group_summary()`（stale/error 聚合）已算无消费者。
- **T2 (P1)** Inspector stringly-typed：无 feature 级、无 factor raster、无 MapProduct
  分节；域行仅靠 host 注入 seam。
- **T3 (P1)** 阶段切换对树展开/滚动/选择的影响未验证保护。

### 上下文 / 能力
- **X1 (P1)** 目标接口不存在：`QgisCapabilitySnapshot` / `LayerCapabilitySnapshot` /
  `ToolContext` / `ToolAvailability` / `LayerPresentationState`（goal §16）需建 seam。
- **X2 (P1)** capability 只有单 bool（bridge available）；无 native/degraded/unavailable
  三态；降级字符串散在画布 backend_status。

### QGIS 入口 / 任务 / QA
- **Q1 (P2)** Style Manager 包装无生产入口；无 CRS 入口；符号系统入口有门禁有原因（好范式）。
- **Q2 (P2)** 任务中心无取消中之外的重试语义缺口（retry 重放 spec 闭包）。
- **Q3 (P1)** 视觉 QA：缺 1366×768、2560×1440、多数状态的 dark/HC、缺 phase1-RAW/
  编辑会话/约束线/因子栅格/树 stale-error/取消中/降级/inspector-factor/export 状态；
  V5 状态无语义断言；`--update-baseline` 死旗标；无动态区掩蔽。

## 3. 数量基线（ratchet 冻结点）

| 指标 | 基线值 |
|---|---|
| palette 命令 | 48（stages 12 / context_tags 1 / requires_write 0 / applicability 0） |
| MapActionController 动作 | 30/实例 × 2 实例 |
| 中央注册表快捷键 | 14（外部 11 绑定不可见） |
| 页面文件 | 131（120 active / 11 非 active） |
| host dock | 13；preset 6 活 + 4 死枚举 |
| setStyleSheet | 234（44 文件 light-snapshot 无 bind；19 纯字面量） |
| font-size 字面量 | 104；定宽字面量 42 |
| 表情符号行 | 43 + 99 符号字形行 |
| 状态词表方言 | 9+ 本地映射；徽章实现 8；空态 4；加载 3 |
| 树状态装饰 | 1（编辑铅笔） |
| 视觉 QA 状态 | 12(V5)+6(V6)；尺寸 3；主题稀疏 |

## 4. 环境事实

- Windows 11 + Git Bash；uv 0.10.9；venv cp312（本 worktree 独立）。
- 原生 pyd 复制自主 checkout（cp312 ABI 兼容）；`qgis_render_bridge` 未构建
  （main 亦然）→ `qgis` 标记测试 skip，fallback 画布/树是**已验证的生产行为**。
- QGIS 4.2.0 安装于 `C:/Program Files/QGIS 4.2.0`（本 Goal 不构建桥）。
- 全量 fast 基线测试：见 `.baseline-full.log`（首轮完整日志损坏于 tail 截断，已重跑；
  已知 main 上存在 5 个环境性失败 + `test_lod_render_path` Windows 硬崩溃，见 V6 记录）。

## 5. V6 明确遗留（= V7 backlog 摘要）

`docs/development/workstation-ux-v6/10-known-limitations.md` 的 16 项全部落入本 Goal
范围或显式记录为不做（如 100GB seismic、跨平台）。
