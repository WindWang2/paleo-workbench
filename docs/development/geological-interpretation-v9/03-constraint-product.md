# 03 — ConstraintProduct（约束产品）

## 身份

组身份 = `ConstraintLayers.id`（与 `constraint_versions` 的提交/版本链一致）。
`ConstraintProduct`（`workflow/interpretation/constraint_product.py`）投影：
kinds（地质词汇）、engine_kinds、per-line strength/confidence（声明才有效，
缺省 1.0/unknown 且标注）、CRS 声明态、content hash、已提交版本链、
maturity（draft/committed）、组级 staleness、validity（未提交编辑提示）。

## 双枚举收敛（P1-4）

`to_engine_kind()`：地质 `ConstraintKind`（10 态）经
`CONSTRAINT_INTERPOLATION_ROLE` 唯一映射到 engine `ConstraintKind`（5 态）。
同名异义枚举不再直传。

## CRS 纪律（P1-3）

`assert_constraints_crs_compatible(factor_crs, group_crs)`：
声明不匹配 → ValueError（单任务与批量共享 plan 两条路径都检查）；
未声明 → 诚实注记进 constraint diagnostics。

## 编辑生命周期（goal §11）

```
QGIS 几何编辑 → stage_save 回填（content_fingerprint）
    → commit_constraints（UI，P0-2 修复）或 constraint.commit（harness）
    → catalog DERIVED 版本链 + constraint_commit DataRun
    → 下游 factor pins 感知（stale_content/stale_version）
```
单一实现（commit_all_constraints/commit_constraint_group），双入口。
