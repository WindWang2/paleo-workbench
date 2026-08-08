# ADR 0056: Data Catalog Core — Canonical Metadata, Immutable Versions, SQLite Index

- Status: Accepted
- Date: 2026-08-08
- Branch: feat/data-catalog-core

## Context

资源管理长期以 `ResourceItem` + 文件路径登记为核心：import 只登记路径不复制文件、checksum 可选、无版本/生命周期/lineage/tags 实体、无 schema version、无本地索引。科研数据管理需要可审计的数据生命周期：RAW 不可变、版本不可变、可迁移、可验证完整性、可重建索引。

## Decision

新包 `paleo_workbench/catalog/`，核心概念：

- **DataStage**：`RAW / DERIVED / INTERMEDIATE / OUTPUT` 正式生命周期枚举，不用 tag 表达。
- **DataAsset** / **DataVersion** / **DataRun** / **Tag**：pydantic 模型。DataVersion 记录 stage、managed/external、项目相对受管路径、source_uri、SHA-256、parent_version_ids、run_id。已 commit 版本不可变；变化产生新版本（每资产单调递增 version_number）。
- **Canonical store**：`<project>.artifacts/metadata/catalog.json` 是 DataAsset/DataVersion/DataRun/Tag 的唯一主存储（原子写 + 目录 fsync，含 `schema_version` 与单调 `catalog_revision`）。`.paleo.json` 的 `resources[]` 仍是 legacy `ResourceItem` 的主存储，两者职责不重叠，无双主。
- **SQLite index**：`<project>.artifacts/metadata/catalog.sqlite` 是纯可重建查询索引（assets/versions/tags/runs/lineage/sync_state 表）。打开时比对 catalog_revision；missing/stale/corrupt 一律安全 rebuild，绝不阻塞项目打开。mutation 走事务。
- **Managed storage**：`artifacts/{raw,derived,intermediate,outputs,working,trash,metadata}`。受管文件路径 `{stage}/{asset_id}/{version_id}/{filename}`。既有 `factor_maps/predictions/paleomaps/qc/exports` 不搬迁，渐进映射。
- **Import 语义**：`Import into Project` = managed snapshot（hash-while-copy 单遍读写、fsync、原子落位、只读位防误）。`Link External` = 显式 unmanaged 引用，可后续 materialize 为 managed RAW。
- **Integrity**：SHA-256 为真实性来源（`catalog/checksum.py` 统一下沉，scanner 复用）。verify 报告 missing/verified/modified/unknown；mismatch 绝不自动改 catalog。
- **Legacy migration**：单向投影，`DataAsset.id = ResourceItem.id`，deterministic + idempotent；ResourceItem 原样保留，旧引用（FactorMap/Prediction/WellTable/JointAnalysis/ExportArtifact.linked_id）不断。
- **DataAssetRegistry** 保持 format/IO registry 职责，不与生命周期 catalog 合并。`VersionSet/VersionSnapshot`（古地图定稿语义）不动。

## Consequences

- UI/业务未来统一经 `DataCatalogService` 写入；直接 `project.resources.append` 与自写 artifact 文件的模式逐步淘汰（集成属 Gemini/zcode 分支）。
- catalog.json 会随版本历史增长，但独立于 .paleo.json save/load 路径，不拖慢项目开关。
- 大文件 import/verify 是 IO 密集同步操作；checksum/copy 为独立可调用单元，QThread 异步包装边界留给 UI 集成层。
