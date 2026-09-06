# Baseline — Geological Harness 2.0（feat/harness-platform-v5）

基线 commit：`049423ab`（origin/main，2026-09-05）。审计以最新源码为准，不信任旧文档。

## 1. 现有架构（Harness 1.x）

```
ToolSource/Chat Runtime (harness/llm.py，零厂商)
  → ActionRegistry (registry.py，显式注册、拒重复、拒 DESTRUCTIVE)
  → HarnessExecutor (executor.py：lookup→input schema→权限→context→governor admit→
    handler/provider→output_schema 强制(#1178)→Scientific/Map 验证→ActionResult)
  → ActionResult {status: ok|warning|fail|cancelled}
Provider SDK (providers/)：descriptor(typed refs/schema/ResourceProfile/deterministic)
  + execute_provider(validate→admit→DataRun provenance→execute→complete_run)
Runtime：TaskScheduler(全局唯一 heavy 队列，bg 并发1+交互车道，admission hook+aging)
  + ResourceGovernor(admit/try_admit，压力 shed) + MemoryPressureMonitor
Catalog：CatalogPort(begin_run/complete_run/register_*/lineage/verify_integrity)，
  DataVersionRef/DataRunRef(input_version_ids/parameters/generator_version/input_snapshot_hash)
Workflow 现状：orchestrator.py 线性 legacy（不持久化）；service.home_workflow_steps 是
  首页 step 状态单一权威；DependencyGraph(catalog provenance→DAG、环检测、拓扑)；
  FreshnessService(脏判定)；RecomputePlan/PlanExecutor(串行执行、无持久化)
```

## 2. Action Matrix（25 个，全部 handler 型，0 个 provider 声明式）

| 域 | actions | risk | cancel | output_schema | 备注 |
|---|---|---|---|---|---|
| workspace | list_assets/search/get_lineage/get_versions/describe_context | READ×5 | 无 | 全缺 | search 降级路径静默丢 type/tag 过滤 |
| well | list/open/list_curves/create_display/apply_template | READ2+COMPUTE3 | 无 | 全缺 | apply_template 接受任意 template_id（无模板语义） |
| seismic | open_volume/get_slice/compute_attribute | READ2+WRITE1 | 1 | 全缺 | compute_attribute 嵌套 execute_provider（本轮已修嵌套准入） |
| map | create_well_location_map/create_factor_map/add_layer/set_style/apply_template/add_component/validate/export | WRITE4+COMPUTE1+READ1 | 2 | 全缺 | create_factor_map 合成样本 fallback 不在返回值可见 |
| geology | list_horizons/list_faults/create_interpretation | READ2+WRITE1 | 无 | 全缺 | |
| workflow | status | READ1 | 无 | 全缺 | **吞异常伪成功**（dashboard_state 异常→`{"error":…}` 但 status=ok） |

Provider：17 个 builtin（interpolation×2、seismic.attribute×11、inference、viz×2、export），
deterministic 全 True，版本 identity 齐全；家族词汇 importer/data_format/preview/map_component 无内置。

## 3. 审计发现的缺陷清单（H0 结论）

1. **嵌套准入重复计数**（已修复，commit b8638b62）：action 租约+provider 租约叠加超过
   streaming buffer，segyio 可用时 e2e Scenario C 必失败。
2. **output_schema 全域缺失**：executor 的 #1178 强制路径是死代码。
3. **workflow.status 吞异常**：违反"验证 FAIL 不得宣称成功"。
4. **workspace.search 降级静默丢过滤条件**。
5. **无 Workflow DAG**：PlanExecutor 串行、无持久化、无 resume、无 node 并行；
   orchestrator.py 是另一个（线性）workflow 词汇——不能扩散。
6. **无 receipt**：ActionResult 有 verification/metrics 但无标准 scientific receipt
   （无 run ID 规范引用、无输入版本引用、无 provider 版本、无 duration 语义）。
7. **无 cache identity gate**：catalog 有 find_reuse_run（DependencyGraph）但 action 层
   没有 deterministic/cacheable 声明与复用协议。
8. **Context 是可变 dataclass**：handlers 可随意改；无 project-switch 守卫；
   SelectionSnapshot 缺 map extent/CRS/horizon/selected features。
9. **provider 契约 V1 缺 verifier 钩子**；无第三方 example plugin。
10. **agent_panel 只有文本 history**：无 plan/task 模型可展示 DAG 进度。
11. agent/（规则式 swarm）与 harness 脱钩且基本 stub（#1143 已诚实化标注）——不在本
    Goal 范围重写，但新 plan model 不得复制它。

## 4. 本机基线测试（2026-09-06）

- `test_harness_core/batch4/provider_sdk/task_scheduler/resource_governance/
  dependency_freshness/factor_incremental_recompute`：183 passed, 1 skipped（修复后）。
- `tests/e2e/test_harness_scenarios.py`：修复前 C 失败（嵌套准入），修复后全绿。
- 修复 commit：`b8638b62 fix(harness,providers): nested provider executions inherit
  the enclosing admission lease`。

## 5. 资源环境契约

- 本机 62.6 GB RAM / 16 核；预算 cap 恒为 spec 默认（streaming buffer 5 GiB）。
- 编译/测试纪律：并发 ≤2；无 100GB 地震体；vendored QGIS 不重建（复用现有 build）。
