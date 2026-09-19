# 01 线 task_plan — 数据目录、工程生命周期与生产服务绑定

## 执行环境记录
- 执行器：glm5.3-flash；平台 ZCode（builtin:bigmodel-coding-plan/GLM-5.3-Flash）。
- `/goal`、`/goal-loop`：平台技能列表与插件缓存中**不存在**这两个命令（2026-09-19 检查
  `~/.zcode/cli/plugins/cache/zcode-plugins-official/` 与会话技能清单）。按任务书要求采用
  同等的**文件持久化循环**（本目录四文件 + `.git/codex-coordination/cpp-close-wave/` 登记），
  如实记录，未安装未知插件、未伪造命令成功。
- 预算请求：360,000,000 tokens（含全部子代理累计，上限而非目标）。平台未提供显式预算
  配置接口；以会话实际用量为准，额度耗尽时在本文件保存恢复点。平台按会话计量，
  无法精确聚合子代理 token —— 已知限制，如实记录（子代理返回含 usage 字段，逐轮抄录
  到 progress.md）。
- 子代理上限：根 agent 直接 ≤3；每个子代理直接 ≤3（递归同限）。已用：1/3（Explore
  盘点，agent_9353851c，163,539 tokens）。预留：1 实现辅助（可选）、1 独立审查。

## 基线
- 仓库 https://github.com/WindWang2/paleo-workbench；`git fetch` 后 origin/main =
  `06211541ae1ccce22b0d5ba9258ce722170ca98b`（与任务书锚点一致；开放 PR 查询为空，
  与任务书陈述一致）。
- 分支 `codex/cpp-close-01-catalog-project-20260919`，worktree
  `/home/kevin/project/worktrees/cpp-close-01-catalog-project`。主工作区未 checkout/reset/clean。

## 能力清单（implemented / merged / wired / verified 四列，动态维护）
| 能力 | implemented | merged | wired | verified |
|---|---|---|---|---|
| catalog 深核（DirtySet/apply_changes/CAS/lease/WC/模型注册/bundle/manifest） | ✔(#1398) | ✔ | 部分（无生产调用） | oracle 97 节（#1398） |
| Transaction::commit 错误传播 | ✘（吞错，本线修复） | — | — | — |
| CatalogServiceApi/CatalogPortApi/ICatalogApi 具体适配器（真实服务） | ✘（本线） | — | — | — |
| 资产变化订阅（change feed） | ✘（本线新增语义） | — | — | — |
| 工程→查询/筛选→导入注册→WC→提交→关闭重开 闭环 | 部分（核心在，缺组合层） | — | — | — |
| 中断恢复报告 + 冲突用户语义（不自动覆盖） | 部分（recover 在核内，缺面向用户聚合） | — | — | — |
| 生产调用链绑定（ProjectControllerCore 驱动真实适配器） | ✘（本线） | — | — | — |

实际 Python 冻结源（参考/oracle 基准）：
- `paleo_workbench/catalog/service.py`（DataCatalogService；import_raw L2055）
- `paleo_workbench/catalog/edit_session.py`（EditSession checkout/commit/cancel）
- `paleo_workbench/project/manager.py`（ProjectManager.load/save/prepare_save/execute_save）
- `paleo_workbench/ui/project_controller.py`（open_project_path→load→DataCatalogService.open→save）

## 范围
- 独占：libs/catalog、libs/project、libs/workspace、数据服务适配；apps/paleo_workbench_platform/closure_catalog_*
- 不做：预览页面、AppShell、通用表格；不做无边界产品扩张
- 12 装配组合根；本线交付 adapter/installer/guard/测试

## 轮次计划
1. R0 盘点（本轮）：四列清单、缺口定位（Transaction 吞错、无具体适配器、无生产绑定）。
2. R1 实现：sqlite 错误传播修复 → closure_catalog_service 适配器（+订阅+恢复报告）→
   closure_catalog_install → 数据/e2e 测试。
3. R2 验证：资源门下最小回归（新增测试+受影响 data.* 平台面）×2；ON/OFF 闭包。
4. R3 独立审查（第 2 个子代理）→ 修复 → 复验。
5. R4 提交/PR，维护 ledger；验收门核对 acceptance.md。

## 恢复点约定
上下文压缩/重启后：先读本文件 + findings.md + progress.md + acceptance.md，再读
`.git/codex-coordination/cpp-close-wave/task-01-catalog-project.md`，恢复同一目标与预算记录。
