# 06 — Lineage 与 Staleness

## 依赖链贯通（goal §19）

```
well version → factor version → compilation input set
    → integrated interpretation → map product
```

传播路径：`MappingDependencyService`（工作区权威）+ `FreshnessService`
（catalog/run 权威）+ 约束 pins 三引擎，经 `workflow/interpretation/
staleness.py` 的**统一 verdict 词汇**汇聚：

```
CURRENT | STALE_CONTENT | STALE_VERSION | MISSING_INPUT | SUPERSEDED | UNKNOWN
```

适配器：`from_constraint_pin` / `from_workspace_status` /
`from_run_freshness`（单向映射，不重实现评估）。
`evaluate_verdict(document, artifact_key)` 为单入口；
`propagate_to_products` 供发布门禁消费。
**UNKNOWN 是问题态**（不可签发），无证据绝不猜 CURRENT（R3-F7：
无目录=不可验证≠输入被清理）。

## Lineage 期望 ops（P1-12 修复）

`_LINEAGE_EXPECTED_OPS` 与 recompute 词表补齐：factor_fusion（+
confidence/variance）、constraint_commit、map_product_assembly、
integrated_interpretation——无 lineage 的这些 run 现在读 UNKNOWN
（不再 fresh-by-default），且可进入重算计划词表。
`step_freshness` 增加 fusion 阶段。

## 双引擎一致性（R3-F1 修复）

产品发布门禁同时检查指纹路径（product_staleness）与统一 verdict；
QA ERROR 级发现（含两引擎分歧中的悲观方）阻断 publish——绝不拣乐观方。
