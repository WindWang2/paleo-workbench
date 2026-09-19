# 09 — 审核治理、质量规则与可验证发布 · task_plan

## 目标（goal）

在最新 origin/main（06211541）上完成 09 线职责：C++ 转换 + 现有新功能迁移 + 产品闭环，
交付可审查 PR。持续“盘点→实现→验证→独立审查→修复→复验”循环，直到本线验收成立。

### 平台支持记录（诚实声明）

- 执行平台无 `/goal`、`/goal-loop` 命令（`which goal` 不存在、无自定义 commands 目录、
  可用技能列表无对应项）。采用同构的**文件持久化循环**：本目录四文件即恢复点；
  上下文压缩/重启后先读本文件 + findings/progress/acceptance 再继续。
- 预算：请求 360,000,000 tokens（上限而非目标）。平台未提供可编程预算计量接口，
  以对话轮次与子代理数量自律约束（根 agent 直接子代理 ≤3）。实际额度无法从平台读取，
  不宣称额度已生效。

## 基线

- 仓库：https://github.com/WindWang2/paleo-workbench
- 开工 SHA：origin/main = `06211541ae1ccce22b0d5ba9258ce722170ca98b`（与任务描述锚点一致，
  git fetch 已确认）。UI-13/UI-17、A–E、CONV-33、CI YAML 修复均在其历史中。
- 分支：`codex/cpp-close-09-review-publish-20260920`（已 unset upstream，防误推 main）
- Worktree：`/home/kevin/project/worktrees/cpp-close-09-review-publish`（独立，主工作区未动）
- 协调登记：`.git/codex-coordination/cpp-close-wave/09-line.json`（common-dir 内，不入库）

## 独占范围

- libs/ui_review（仅 additive：ReviewExportPage::set_actions_provider）
- libs/closure_review（新建）：QC 规则核、定稿版本核、报告导出核、IReviewActions 真实后端
- apps/paleo_workbench_platform/closure_review_install.{hpp,cpp}（新建）+ 命名块装配
- closure_review_* 全部语义；审核策略与发布事务协调归本线
- 不拥有：通用 interchange 格式核（10）、工作流 QC 数值核编排（02）、编图事实（08）

## 实现计划（分轮）

- R1 盘点（已完成，见 findings）：缺陷点 app_shell.cpp:198 provider 返回 nullptr；
  Python 冻结源 = workflow/qc.py + workflow/map_qa_rules.py + workflow/versioning.py +
  workflow/qc_report_export.py + resources/export_service.py::default_export_dir。
- R2 实现 libs/closure_review：
  - review_qc_core：BASIC_QC_RULES 六规则 + EXTENDED 十规则（含 coverage 诚实记账）、
    make_issue（geometry+centroid 定位）、upsert-by-map、active_quality_reports 语义
  - review_versioning：finalize 全守卫（demo-draft/lineage）、supersede、
    snapshot+fingerprint、contour draft final、run→export_ready
  - report_export：原子写（tmp+fsync+parse 验证+rename）、非有限浮点→null、
    ExportArtifact 登记；失败 → DataError，绝不产生成功回执
  - project_review_actions：IReviewActions 实现，文档解析器/保存委托注入
- R3 装配：closure_review_install + main_window.cpp 命名块 + CMake（根/平台 app）+
  PwbDataStore::save_document()（认领共享保存缺陷，函数租约已登记）
- R4 测试：closure_review_tests（headless，真实 .paleo.json fixture：有错/无错工程）、
  ui_review 测试回归、平台装配测试；资源门内构建
- R5 独立审查（子代理）→ 修复 → 复验 → PR

## 验收（本线）

1. 替换 app_shell.cpp:198 的 nullptr provider（经 installer，不改 app_shell.cpp 本体）
2. 真实有错/无错工程输出可解释 QC（status/issues/rule_status/coverage）
3. 导出 layer filter、生效版本与权限/只读限制正确；短写/磁盘满失败无成功回执
4. 重开可追溯发布产物（export_artifacts/version_sets 落盘）
5. 未绑定工程明确状态（页面守卫保留）
