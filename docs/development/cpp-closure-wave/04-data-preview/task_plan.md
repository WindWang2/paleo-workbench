# 04 — 统一数据页、解析注册表和预览分派（task_plan）

- 分支：`codex/cpp-close-04-data-preview-20260919`
- worktree：`/home/kevin/project/worktrees/cpp-close-04-data-preview-20260919`
- 基线：`origin/main` @ `06211541ae1ccce22b0d5ba9258ce722170ca98b`（2026-09-19 fetch 后确认，与任务书锚点一致；开放 PR 查询为空）
- 平台支持：ZCode 本地技能清单**无** `/goal`、`/goal-loop` 命令（已核实，只有 browser-use/document-skills/skill-creator/zcode-guide）。按合同采用**文件持久化循环**（本四文件）执行，预算记录为 3.6 亿 tokens 上限（请求值，非计量读数；平台未提供累计 token 计量接口）。
- 子代理预算：根任务直接子代理 ≤3（已用 1：盘点 Explore；预留 1：独立审查）。

## 目标

把 UI-17 遗留的 deferred（DataPage 缺失、LocalVizProvider message 占位、preview_settings 宿主动作缺失）与 E 线已合并的数据 dock 收敛为一份真实资产选择状态；补齐"真实资产选择→解析→正确 presenter→缩放/选择/导出"闭环，含统一预览设置与可取消加载。

## 范围（独占）

- `libs/ui_pages_data` 装配层、`libs/ui_pages_preview` 装配层
- `apps/paleo_workbench_platform` 的 `viz_e_*` 数据宿主、新增 `closure_preview_*`
- 本线测试与 ledger

不触碰：viz_charts 绘制核、A/B/D presenter 实现域（只消费注册表）、AppShell 全局结构（12 所有；本线以函数级租约方式在 `app_shell.cpp` 的 build_pages/wire 段做最小增量）。

## 验收（本线）

1. 真实资产选择→解析→正确 presenter→缩放/选择/导出 闭环有测试。
2. 快速切换、删除资产、工程切换、取消、解析失败、媒体环境不可用 均有状态断言。
3. 图表导出校验真实数据内容（非空文件、非占位）。
4. 不以 message 占位伪装实际预览；message 仅在能力真实不可用时如实呈现。

## 实施顺序（每步可验证）

1. 盘点定稿（findings.md）：DataWorkspace vs VizEDataPage 选择状态、preview_dispatch 现状、LocalVizProvider seam、catalog 源、presenter 注册表消费者。
2. 资产选择状态收敛：单一真实 source-of-truth（catalog 仓储驱动），DataWorkspace 与 viz_e dock 共享。
3. DataPage 净缺口 + LocalVizProvider base seam 接真解析注册表（ingest/preview registry）。
4. 统一预览设置 + 可取消加载（JobCenter/JobOwner 范式，不在 GUI 线程做重解析）。
5. presenter 分派消费 05/07（LAS/time-depth/seismic）+ 既有 image/table/JSON/PDF 保留。
6. 验证轮（资源门内）+ 独立审查 + 修复复验。

## 轮账

| 轮 | 候选 SHA | 目标 | 结果 | 下一步 |
|---|---|---|---|---|
| 0 | 06211541 | worktree/分支建立、coordination 登记、资源门 Probe | RESOURCE_READY 40.9GiB jobs=2 | 盘点定稿 |
| 1 | worktree | 实现：bus/adopt/base/install/租约块/两测试目标 | 过程中发现并修复 D1–D5（见 findings） | 验证轮 |
| 2 | cebb65e9 | 验证：pa_flow 143 检查 + platform.closure_preview + 受影响集 30/30 ×2 + MALLOC 4/4 + 全量构建；提交 | 全绿 | 独立审查→修复→PR |
