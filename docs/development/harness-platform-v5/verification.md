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

（待各实现里程碑填入）
