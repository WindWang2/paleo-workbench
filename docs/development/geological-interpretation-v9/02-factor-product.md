# 02 — FactorProduct（单因素产品）

## 身份与投影

`FactorProduct`（`workflow/interpretation/factor_product.py`）是一次单因素分析的
领域投影——身份 = `FactorMapTask.id`；载荷权威不变（live cache → npz artifact →
catalog INTERMEDIATE 版本）。grid / contours / polygons / uncertainty / qc 是
同一产品的 artifacts（`FactorArtifactRef`：presence + version ref + 诚实
absent_reason），不再是被此无关的渲染期产物。

## 字段契约（goal §7 对照）

| goal 要求 | 来源 | 说明 |
| --- | --- | --- |
| factor_id | task.id | 稳定身份 |
| factor_type / family | task.factor_type → FACTOR_FAMILIES 反查 | 未知家族=""（不猜） |
| inputs / input_versions | grid version → run → inputs | 未保存=空（诚实） |
| method / parameters | registry.canonical_algorithm_id(task.method) | 未注册方法保留原串+标记 |
| unit | grid 契约 > task 参数 > 家族默认 | unit_declared 区分声明/默认 |
| CRS | grid descriptor | crs_declared |
| uncertainty | variance 指标 / has_variance_grid | 缺失原因由注册表能力推导 |
| QC | quality_metrics 已知键子集 | |
| run_id / version | catalog 解析 | |
| maturity / staleness | workspace 状态 + 依赖评估 | |

## AlgorithmSpec 注册表（ADR-5）

`algorithm_registry.py` 是能力唯一权威：algorithm_id（engine 规范 id）、
别名表（收敛 UI 中文标签/engine id/历史写法）、parameter_schema、
supported_constraints（从 constraint_capabilities 投影）、supports_cancel、
requires_crs、produces_uncertainty、backend。
`tokens.INTERPOLATION_METHODS` 从注册表派生（UI 标签值不变）。
模板库（mapping/geological_pipeline/templates）与算法库严格分离。

## Staleness 锚点（P0-1 修复）

`GeologicalMappingService.create_factor_map` 现在与 `factor.interpolate`
路径一样盖上：约束 pins（内容哈希）+ 输入指纹（GeologicalFactor 属性集）
+ 声明单位。指纹失败 warning 可见（不静默）。
