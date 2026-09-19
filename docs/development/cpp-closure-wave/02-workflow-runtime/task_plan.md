# 02 — 工作流编排、版本和重算闭环 · task_plan

## goal-loop 记录

- 平台 /goal 与 /goal-loop：本执行环境可用技能列表中不存在该命令/技能（zcode-guide 仅诊断类）。**如实记录：采用文件持久化循环（本四文件 + 协调登记），不伪造命令成功。**
- 预算：请求 360,000,000 tokens 上限（根+子代理累计）。平台未提供 token 计量接口，无法确认额度生效；按需推进、完成即停，不宣称额度已生效。
- 子代理限额：根 ≤3 直接子代理，子 ≤3 递归。计划：盘点用直接读文件（不派生），实现主手 + ≤1 审查子代理。

## 候选基线

- base = origin/main 06211541ae1ccce22b0d5ba9258ce722170ca98b（PR #1410 CONV-33 + #1411 CI 修复已入）
- branch = codex/cpp-close-02-workflow-runtime-20260919
- worktree = /home/kevin/project/worktrees/cpp-close-02-workflow-runtime（common-dir 共享 /home/kevin/project/paleo-workbench/.git）

## 范围（独占）

libs/workflow_runtime、libs/workflow_engine、libs/workflow_interpretation 及本线测试；新增 closure_workflow_*（适配/装配层）。不拥有 catalog 内核、科学算法、全局命令面板。

## 已核对基线能力（先扣除已实现）

- CONV-26（已并入 main）：freshness/current_context(数据面)/recompute_plan/constraint_versions/provenance_graph/staleness/node_adapters/runtime_service + oracle 126 例。
- CONV-32 = PR #1378（已合并核对）：RunEngine 全语义面（create/run/resume/rerun/cancel、条件、重试、缓存身份跨 run 复用、__checkpoint__ 失败、双跑/项目守卫、$ref/$slot/$context）+ store 原子 checkpoint + receipt 26 字段 + plan_view 七态 + interpretation 8 TU。598 checks。
- CONV-33 = PR #1410（已合并核对）：orchestrator/service/recipe/versioning/qc/map_qa_rules 移植 + libs/project version_models。

## 真实缺口（本线要做，33-findings A3 + 32-findings A3 扣除后）

1. current_context.resolve_current_project_version_context 真实五段 project 注入 + _deselect_superseded_domain_tips（现 C++ 仅有数据面，resolve 未移植）。
2. map_product.py (1078) catalog OUTPUT 编排面消费者（P1-D fail-closed）。
3. integrated_compilation.py (683) 证据集→FusionModel→融合→角色摘要消费者。
4. engine `_drive_parallel`/`submit_to_scheduler`/scheduler token 同步 + 任务取消（32-findings D5 延后项）。
5. engine `_register_cache_run` catalog provenance 轨 + cache-run catalog 持久化。
6. engine session 指针 merge/restore 宿主注入（重开恢复）。
7. 既有 UI 控制器接入 workflow 服务（closure_workflow 装配层）。
8. 可解释重算计划/版本差异/失败恢复的产品面串联。

## 验收闭环（本线 acceptance）

导入数据→选 recipe→执行→产物版本/provenance→修改输入判 stale→仅重算必要节点→重开恢复；失败短路、取消、过期完成、cache 命中真实验证。已知重复 id/环依赖/证据解析问题先复现再修。

## 资源纪律

- 资源门：scripts/cpp-migration/invoke-resource-gate.sh（读取真实参数后使用）；j≤4 默认 j2；CTEST_PARALLEL_LEVEL≤2；OMP/OPENBLAS/MKL=1。
- 8 GiB 可用内存门槛；大链接串行。
