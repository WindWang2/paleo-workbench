# 01 — 用户工作流与 UI 承诺（E2E 验收映射）

## Scenario A — Phase 1 智能预测

| 步骤 | UI 承诺 | 机制 |
|---|---|---|
| 打开工程 → 进入① | 阶段条标记①；工具条组可见性按阶段推导 | `stage_group_visibility` 单点 |
| RAW 相图可见不可编 | 选中 RAW：状态 chip「RAW · 只读」；树菜单「开始编辑」禁用（原因）+「复制为草稿…」；evaluator 对 add_* 全线禁用（RAW 判词） | `_role_gate` + `layer_menu_facts` |
| 创建 DERIVED 草稿 | 阶段动作「创建解释草稿」；新层自动成为活动目标 | stage_actions（dispatcher） |
| Add Polygon 可用 | preferred 提示（下缘 accent 线）；tooltip「当前编辑目标：…（面图层 · 角色 · 成熟度）」 | `preferred` + `_action_status_blocks` |
| snapping 依 role 设置 | 捕捉 tooltip「当前配置 = 角色推荐/用户自定义」；容差/模式/参与引用层 | ToolContext v4 捕捉事实 |
| 编辑 → dirty → save | chip「Edit 草稿 ● 未保存」；save 后立即回落「编辑中」 | `apply_context` |

## Scenario B — Phase 2 约束

* 物源方向线/相带边界（线角色）：add_line 为 preferred；add_polygon 被
  「抢主位」防护拒绝（判词指引用添加线）。
* 插值边界/掩膜（面角色）：add_polygon preferred；add_line 拒绝。
* 捕捉/拓扑开关状态条常显；拓扑错误 > 0 → 「⚠ 拓扑: N 个问题」chip 可点击
  （显式校验 + 首问题定位）。

## Scenario C — 综合编图

* factor 证据查看 → Inspector（角色/成熟度/新鲜度/几何/CRS/会话/推荐动作）。
* integrated draft 编辑（同 A 的捕获语义）。
* QA → 冻结：chip「已冻结」；编辑入口全线禁用（冻结判词）。
* 导出：`map_export`（阶段③白名单）。

## UI 不能让用户猜（Goal §4 的答案面）

| 问题 | 呈现面 |
|---|---|
| 我在哪个工程/阶段 | app bar / 阶段条 |
| 活动图层/角色/RAW-DERIVED | 树装饰 + 状态 chip + Inspector |
| 可编辑/会话/dirty | 状态 chip（Edit/● 未保存/RAW · 只读/已冻结） |
| 当前 MapTool | 工具条 checked（evaluator checked ← current_tool） |
| 捕捉/拓扑 | 状态条读数 + tooltip 详情 |
| CRS/比例尺 | 状态条 CRS:xxx/未声明/⚠ + 1:N |
| 选择数 | 状态条「已选 N」 |
| 为什么灰 | tooltip 判词（evaluator 唯一来源） |
| 推荐工具 | preferred 提示 + Inspector 推荐动作 |
| 阻塞 | 状态条 Renderer/任务中心（blocking 判词进 tooltip） |
