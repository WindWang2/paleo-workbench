# 04 — File Lifecycle（V13）

## 1. RAW 不可变（复用 + 呈现强化）

RAW 物理只读（chmod）+ ImmutableVersionError + hash 永不覆盖
（`catalog/storage.py`/`queries.py`，V11）。V13 增量：
- 删除/移出前的 impact 门（`ui/pages/impact_preview_dialog.py`）——
  有下游/地图引用时必须显式确认（默认取消），无影响静默；
- Inspector 概要页「编图图层引用/地图产品」行——RAW 也能反查用途。

## 2. 修改流（不变式）

```
RAW DataVersion → create_working_copy（复用不覆盖，#1211）
  → 编辑（外部工具/在应用）
  → register_manual_edit_run（running，输入=源版本+端口）
  → commit_working_copy(run_id)（同资产升版或新资产）
  → complete_manual_edit_run（输出端口 manual_edit；部分提交如实）
```

## 3. 中间产物口径（W-D 决策表落地）

`catalog/intermediate_policy.py`——「什么必须登记/什么可以缓存/
什么属于 working state/什么是科学结果」：

- **必须登记**：factor grid、prediction 中间体、解释、属性体、成图产品、
  QC 报告、导出件（INTERMEDIATE/DERIVED/OUTPUT）；
- **EPHEMERAL**（任务期存续）：渲染临时 SVG、原子写 .tmp、workflow
  checkpoint（%TEMP% paleo-workflow-runs）、interchange 工作目录；
- **CACHE**（可重算可删）：指北针 SVG、预览缓存；
- **收编修复**：无工程时 `p2-attribute-*` mkdtemp 失败必清、
  产物被 catalog move 走后清空壳（`harness/actions/seismic.py`）。

## 4. 状态词汇（UI 呈现位）

原始/工作副本/未提交（working_copies 表 checked_out/dirty）/已提交/
当前版本（asset.current_version_id）/历史版本/stale（ImpactService 派生，
永不回写）/pinned（version.metadata.pin）/missing source
（EntityViewService.missing_source_asset_ids）/integrity damaged
（verify_integrity）。

## 5. 未收编残留（known limitations）

- factor grid「活窗」（插值→保存之间未入库）：staging lease 仅一路径覆盖；
- `<artifacts>/intermediate`、`derived/attr.zarr` 双存储位置（已登记但
  payload 在 artifacts 树而非 catalog 布局）；
- workflow checkpoint 目录无按龄清扫（计划入 14-known-limitations）。
