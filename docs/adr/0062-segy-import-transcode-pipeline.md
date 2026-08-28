# ADR 0062: SEG-Y 导入即后台转码与统一任务队列

- Status: Accepted
- Date: 2026-08-28
- Deciders: WindWang2（产品裁决），ZCode wayfinder 会话
- 来源: 地图 [#1067](https://github.com/WindWang2/paleo-workbench/issues/1067) 工单 [#1071](https://github.com/WindWang2/paleo-workbench/issues/1071)；规格书 §2；承接 ADR 0059（数据管理）与 ADR 0061（格式）

## Context

100 GB 体转码即使 95 MB/s 也需 18+ 分钟；导入体验与后台资源治理需要契约。ADR 0059 已确立「导入默认托管 RAW + Link External 高级选项」与 catalog 版本体系。

## Decision

1. **导入即后台转码**：`import_raw` 完成后自动入队；转换期前端降级直读 SEG-Y（现有 segyio 路径作过渡模式）。
2. **断点续转零状态文件**：重扫 zarr store 的 shard 完成度；commit = `zarr.json` 写全 + DERIVED DataVersion 入库。
3. **挂接**：Zarr 体 = 同 DataAsset 的 DERIVED DataVersion（parent=RAW、`DataRun("segy-to-zarr")`）；重导入后旧版本 stale 标记 + 一键重转，不自动删除；资产 trash 级联。产物统一入 `*.artifacts/`。
4. **统一任务队列**：转码、属性全量计算、AI 全量推理共用单并发队列（盘带宽约束），FIFO + 浏览体插队；并行 worker = `min(物理核−2, 8)`。

## Consequences

- 验收：8 核 NVMe 上 100G 转码 ≤ 10 min；中断-重启续转零重复。
- 磁盘预算检查：导入前预估 = 原始 × 0.85（× 1.33 若启用 LOD 预建；默认懒建时为 ×1）。
- 队列成为所有盘带宽密集任务的唯一入口——新任务类型（如未来批量导出）必须入队而非旁路。
