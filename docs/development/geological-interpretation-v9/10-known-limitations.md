# 10 — 已知限制

1. **融合面 descriptor-only**：似然/置信度/方差 scalar 画布发布路径仍未接
   （基线既有；登记与目录版本完整，渲染桥接属 QGIS 方向）。
2. **fusion 重算不在 PlanExecutor**：factor_fusion 等已进入 lineage 期望与
   重算词表（可标 stale/可计划），但执行 handler 未实现——重跑需人工触发
   run_fusion / fusion.run。
3. **服务路径约束 pins 偏保守**：create_factor_map 路径对未消费的约束组也
   盖 pin（方向安全：只会多标 stale，不会漏标）。
4. **CRS 可验证性**：PaleoMapDocument 无 CRS 字段，composition CRS 不可
   结论性验证（发布警告，基线 documented limitation 13 沿袭）。
5. **engine 方法分派映射**：METHOD_LABEL_TO_ENGINE（engine 方法名词表）与
   AlgorithmSpec（算法身份词表）是两个词表，经 ui_label 桥接；统一为单一
   engine-id 字段留待后续。
6. **本机环境预存失败**（非本分支回归，base 39bc1147 同样失败）：
   tests/perf/test_interpolation_perf.py constrained-IDW wall-clock 门禁
   （本机慢于参考硬件）；test_project_package/test_dependency_audit_and_batch
   Windows 临时文件 PermissionError；e2e/test_harness_scenarios 缺 zarr；
   test_unified_map_canvas/test_native_factor_map 缺 C++ 扩展构建；
   test_workstation_lifecycle dock 最小宽（DPI 相关）；
   test_geological_mapping_pipeline 2 个 contour 测试在本 worktree 环境失败
   （主 worktree 通过）。
7. **100GB 地震体数据**：明确排除（goal §35）。既有 small/medium 地震解释
   输出仅作 evidence 引用，未做任何体数据架构开发。
