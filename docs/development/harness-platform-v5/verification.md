# Verification — Geological Harness 2.0

随实现滚动更新。每条含命令、结果、日期。

## 基线（2026-09-06）

- 修复前发现 2 个既有失败：
  1. `test_execute_output_schema_mismatch_fails`（错误信息被 ActionValidationError
     前缀覆盖）→ 修复：label 参数。
  2. `test_scenario_c_coherence_on_active_volume`（嵌套准入双重计数）→ 修复：
     租约继承（commit b8638b62）。
- 修复后：harness/provider/runtime/workflow 基线 183+63 全绿。

## 里程碑记录

### M1 阻断缺陷修复（commit b8638b62 + 前置 fix）

- `test_execute_output_schema_mismatch_fails`：错误前缀覆盖 → label 参数修复。
- `test_scenario_c_coherence_on_active_volume`：嵌套准入双重计数（1GiB action +
  5GiB provider > 5GiB buffer）→ 租约继承修复。segyio 可用机器上原必失败。
- 修复后基线：harness/provider/runtime/workflow 全绿。

### M2 ActionSpec V2 + 六态（harness/spec.py, executor.py）

- tests/test_harness_spec_v2.py：30 项（字段默认兼容、cacheable 门、递归 schema
  校验、六态映射、verifier fail-closed、governor 拒绝→rejected）。
- 全 harness 家族回归 256 passed。

### M3 Workflow DAG 引擎（workflow/dag/）

- tests/test_workflow_dag.py：31 项 — 拓扑/菱形依赖、绑定（slot/ref/context/默认
  值）、条件跳过、retry、取消传播（引擎 + scheduler 桥）、崩溃 resume（仅重跑
  被打断节点）、rerun 携带（identity 相同才携带）、缓存门（假 ID 拒绝/删除文件
  拒绝/参数变更 bust）、损坏 checkpoint 拒绝执行、项目切换守卫。

### M4 Recipe（workflow/recipe.py）

- tests/test_workflow_recipe.py：12 项 — 原子读写、后缀规范、秘密/绝对路径/SQL
  结构拒绝、未来版本拒载、clone 新身份、diff、from_run 烘焙 slot 默认值、
  rerun-with-new-inputs 闭环。

### M5 Context Snapshot（harness/context.py）

- tests/test_harness_context_snapshot.py：frozen、字段覆盖、derived() 隔离、
  $context 白名单只读。

### M6 Provider V2 + examples

- tests/test_provider_examples.py：9 项 — build_identity、verify 通过/拒绝/崩溃、
  两个 example 真实执行（真实 GeologicalFactorDataset 统计 + 真实
  FallbackMapRenderBackend 渲染 PNG + 包含检查拒绝逃逸路径）。

### M7 Action Library（51 actions / 10 domains）

- tests/test_action_library_v2.py：13 项真实执行。
- tests/test_harness_policy.py：12 项全注册表策略扫描（WRITE 必须声明副作用、
  产出 action 必须声明 output_schema、重 IO 的 READ 必须声明 io_weight、重型
  action 估值下限、地震 ROI 契约）。
- 策略扫描立即产出修复：20 个 action 补 output_schema；map.add_component 的
  `added` 语义被 schema 揭穿并如实声明。

### M8 Plan model + 面板接线

- tests/test_plan_view.py：符号/进度/摘要重建/面板进度信号与清单渲染。
- workflow.run/resume 进度经 action context 流出（worker→queued signal→label）。

### M9 对抗性矩阵 + A/B/C 验收

- tests/test_adversarial_harness.py：16 项 fail-closed 场景全过。
- tests/e2e/test_harness_workflow_abc.py：3 条真实端到端工作流（含真实 PNG 导出、
  真实目录版本、真实完整性校验、recipe 保存/复现说明/携带重跑对比）全过。
- 汇总：256 passed, 1 skipped（2026-09-06，本机 62.6GB RAM/16 核，无 OOM/无
  高并发编译，未触 vendored QGIS 重建）。

### 性能证据

- harness 派发开销保持基线（<10ms 预算内，README/ADR-0066 既有测试覆盖）。
- 单工作流（9 节点，含一次 kriging 插值 + 一次 PNG 导出）端到端 <1.1s（本机）。
- 引擎每节点一次原子 checkpoint（tmp+os.replace），无轮询线程。

