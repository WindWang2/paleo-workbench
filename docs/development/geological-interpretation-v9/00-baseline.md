# 00 — V9 Baseline（基线审计）

Branch: `feat/geological-interpretation-workbench-v9` (base `39bc1147`, latest main 2026-09-10).
审计方式：两个只读 subagent（scientific/domain architecture audit + workflow/catalog/provenance
audit）+ 主 agent 交叉验证关键契约。所有结论带 file:line 证据（相对 worktree 根）。

## 1. 现状数据流（真实）

```
raw import (catalog RAW version, 内容寻址, 不可变)
   → well table / workarea / seismic (project 文档实体)
   → [Phase 1] facies draft: RAW checkout → UserVectorLayer (INITIAL_FACIES_DRAFT)
              + LayerMembershipRecord.source_version_id pin
              + prediction (mock facies, overlay-only)
   → [Phase 2] ConstraintLine (文档) ←→ QGIS 编辑层 sync (content_fingerprint)
              commit_constraint_group → catalog DERIVED 版本链 + constraint_commit DataRun
              factor interpolate → FactorGridResult (live cache → npz artifact →
              catalog INTERMEDIATE version at save) + constraint pins
   → [Phase 3] compilation_input_set: dict[label → "factor:<task>:<ver>" | "draft:<id>"
              | "constraints:current"] (workspace state)
              → run_integrated_fusion → summary dict + descriptor registrations
                (likelihood/confidence/variance DERIVED versions)
              → integrated draft layer (INTEGRATED_FACIES, 可编辑, 无版本)
              → assemble_map_product → MapProductRecord + catalog OUTPUT version
              → freeze / publish gate (agent-only 路径)
```

关键权威：Catalog（SQLite, CAS, 不可变版本, DataRun 溯源）是唯一数据权威；
`ProjectDocument` 持有任务/图层/成员资格索引；QGIS project 是纯 mirror。

## 2. 已有的强契约（V9 复用核心，不重造）

| 契约 | 位置 | 价值 |
| --- | --- | --- |
| `FactorGridResult` 网格契约（CRS/unit 显式可空、永不猜测） | `workflow/factor_grid_result.py:239` | factor 载荷权威 |
| `ConstraintApplication` requested/applied/partial/ignored/unsupported | `workflow/constraint_capabilities.py:178` | 约束能力诚实矩阵 |
| `commit_constraint_group` 内容寻址提交 + pin + staleness | `workflow/constraint_versions.py:214,374,439` | 约束生命周期核心 |
| `publish_map_product` 硬门禁（stale/QC error/警告可拒） | `workflow/map_product.py:662` | 发布门禁语义 |
| `MappingDependencyService` staleness 传播（draft→integrated→product） | `mapping_workspace/dependencies.py:270` | 工作区传播引擎 |
| `FreshnessService` 运行级新鲜度（UNKNOWN 不猜 CURRENT） | `workflow/freshness.py:379` | catalog 级新鲜度 |
| ActionSpec 执行器（fail-closed 校验、verifier、cancel） | `harness/spec.py` / `executor.py` | 动作治理面 |
| `EditDelta` 编辑观测（who/what/order/session） | `mapping/edit_delta.py:91` | 人工编辑种子 |
| 约束线级 compare / 产品 compare | `constraint_versions.py:539` / `map_product.py:482` | 版本比较原语 |

## 3. P0 缺陷（科学诚实性阻断）

| # | 缺陷 | 证据 |
| --- | --- | --- |
| P0-1 | UI/服务路径 `create_factor_map` 绕过约束 pin + 指纹 → 约束编辑永远无法将该路径的 factor 标 stale | `services/geological_mapping_service.py:211-333`（无 `constraint_pins_for_task` 调用；对比 `factor_interpolation.py:279-292`） |
| P0-2 | constraint commit 仅 harness/agent 可达；生产 UI 无法提交约束版本 → `constraints:current` 永久 UNKNOWN | 仅调用方 `harness/actions/scientific_pipeline.py:602`；`stage_actions.py:62-67` P2 动作表无 commit |
| P0-3 | 预测结果（含 mock facies）overlay-only，不能作为 evidence 被 pin 进 Compilation Input Set | `stage_actions.py:1073-1088`（select_evidence 仅 drafts/factors/constraints） |
| P0-4 | 综合解释无身份对象：fusion 返回 dict + 可编辑层，无 input-set pin、无 QA 绑定、无版本 | `integrated_compilation.py:495-634`；`stage_actions.py:1105-1134` |
| P0-5 | 混合已声明/未声明 CRS 的融合静默通过（`crs_a and crs_b` 守卫，一方 None 绕过） | `factor_fusion.py:309-315` |
| P0-6 | 人工解释编辑覆盖图层内容，无 revision 历史、无证据归因（"谁基于哪个 factor/constraint 改的"不可回答） | `stage_save` 只 flush+sync：`stage_actions.py:1449-1463` |
| P0-7 | 核心写入 `factor.interpolate` 消费 live task 而非 pinned 输入版本；完成≠已登记版本（版本在 save 时才物化） | `scientific_pipeline.py:25` side_effect_notes；`factor_grid_artifacts.py:5-11` |
| P0-8 | 双调用路径：人类 UI 直接调算法（无 verifier/准入/收据），只有 agent 路径走 ActionSpec | `stage_actions.py:1223-1413`、`mapping_page.py:520-615` vs `agent_panel.py:456` |

## 4. P1 结构性缺陷

1. **三套生命周期**互不引用：`MapProductRecord.final/superseded/frozen`、`ArtifactMaturity.draft..published`（reviewed/published 生产路径从不设置）、`VersionSet open/final/superseded`。
2. **两套新鲜度引擎**两套词汇：`FreshnessState`（FRESH/STALE/UNKNOWN/MISSING/FAILED/RUNNING）vs `FreshnessStatus`（CURRENT/STALE/MISSING_INPUT/SUPERSEDED/UNKNOWN）+ constraint pin 六态；Inspector 各自合并。
3. **freshness/recompute 不认识 fusion / constraint_commit / map_product_assembly**：`_LINEAGE_EXPECTED_OPS`（`freshness.py:98-108`）、`OPERATION_LABELS_ZH`（`recompute_plan.py:106-116`）缺失这些 op → 融合结果 stale 后无重算路径。
4. **缺失动作**：`compilation.create_input_set`、`interpretation.checkout/commit/compare`、`map_product.assemble`、`map_product.publish`（现叫 `map.publish`）。
5. **MapProductAssembly 不能引用 fusion 输出/综合解释层**（`map_product.py:35-42` 只有 factor_task_ids + 解释 refs）；Stage-3 组装丢弃 `interpretation_refs/composition_ref`（`stage_actions.py:1409-1412`）。
6. **fusion 计算用当前网格而非 pin 版本**（`integrated_compilation.py:110-118`）——pin 过期事后标记，但计算已用错数据且无警告。
7. **两个同名 `ConstraintKind` 枚举**（engine 5 态 `constraint_capabilities.py:41` vs 地质 10 态 `layer_roles.py:149`）。
8. **约束 CRS 与 factor CRS 从不比对**（`constraints.py:62-107`）。
9. **unit 三处重复**（grid.unit / task.parameters / quality_metrics）；**方法词表 ≥5 处重复**（tokens/factor_interpolation/interpolation_fingerprint/constraint_capabilities/dialogs）。
10. **无 summary 契约**（FactorSummary 等不存在）；UI 直接读内部模型。
11. **任务状态无 CANCELLING/DEGRADED**（`task_scheduler.py:51-56`；DEGRADED 仅 action 层）。
12. **解释无 compare API**（仅 fingerprint classify_stale）。
13. **无 QGIS 侧 provenance 属性**（mirror 单向）。

## 5. 规模现状（10万+实体 / 1000 层 / 10k 井）

已好：lazy catalog open、keyset 分页、O(1) id 映射、lineage 有界（max 5000）、
factor grid LRU（64/256MiB）、DAG cache index。
隐患：`MappingDependencyService.evaluate` 每次阶段切换全量扫描 artifacts×versions
（`dependencies.py:149-206`）；`compute_summaries` 全版本遍历。

## 6. V8/V7 已占用方向（避免重复）

- Scientific Workflow V8（PR #1239）：versioned constraints 运行时/线束生产化 —— V9 复用其 commit/pin 语义。
- QGIS Context Control Plane V8（PR #1240）/ Spatial Authoring V8（PR #1238）：QGIS 权威收敛 —— V9 不动 QGIS native 工具。
- Cartography V7（PR #1237）：模板/制图管线 —— V9 只消费 template library，不混入算法注册表。
- mock facies prediction（main 0b052fe9..39bc1147）：V9 将其输出纳入 evidence 模型。

## 7. 100GB 地震体数据

明确排除（goal §35）。现有 small/medium 地震解释输出仅作为 evidence 引用，不进入体数据架构。
