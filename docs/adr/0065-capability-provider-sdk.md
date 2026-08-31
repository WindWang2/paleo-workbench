# ADR 0065: Capability Provider SDK（P.REG 落地）

- Status: Accepted
- Date: 2026-08-31
- Deciders: WindWang2（产品裁决），ZCode P2 convergence 会话
- 关联: ADR 0055（插件运行时分期，本 ADR 即其 P.REG 切片）、ADR 0056（Data Catalog Core）

## Context

扩展专业能力 = 直接改核心代码。已有的深模块（CatalogPort、ModelProvider+模型注册表、
MapRenderBackend、Interpolator、KERNELS 表）各自完整但词汇不统一；`DataAssetRegistry/FormatSpec`
设计了却无生产 caller。ADR 0055 明确首期不做 unrestricted Python 插件，而是
**P.REG（注册式 provider）**。

## Decision

**capability provider = 唯一扩展单元**（`paleo_workbench/providers/`）：

1. **契约是数据不是猜测**：`ProviderDescriptor`（frozen：provider_id/family/version、
   JSON-schema parameters、typed input/output 名、`ResourceProfile`、cancel/resume、
   deterministic、threading_model）；`validate_descriptor` 结构化校验，绝不 inspect 签名。
2. **typed refs**：`refs.py`（WellRef/SeismicVolumeRef/MapDocumentRef/FactorDatasetRef/
   FactorGridRef/PathRef）+ 复用 catalog 的 `DataVersionRef`（+ 进程内领域对象入词汇表：
   GeologicalFactorDataset/MapDocument）。禁止 anonymous dict 进 provider。
3. **注册表**：显式注册 + 重复/版本冲突检测 + 隔离（invalid/抛错工厂→quarantine，带原因，
   启动不受影响）；entry-point 发现 opt-in（`PALEO_PROVIDER_ENTRY_POINTS=1`），永不扫目录。
4. **统一执行**：`execute_provider` = resolve → schema 校验 → typed 输入检查 → governor
   admission（P2-A）→ ProviderContext（catalog/cancel/progress/work_dir）执行 → DataRun
   provenance（begin/complete/fail，generator_version=provider version）→ ProviderResult
   （artifacts/warnings/diagnostics/provenance/metrics）。契约错误透传，外来异常包装隔离。
5. **内置 provider 全部包裹既有生产 seam**：kriging/idw（Interpolator）、
   seismic.attribute.*（按 KERNELS 表逐 kernel）、inference.tiled_onnx（委托
   prediction.TiledOnnxProvider，模型注册表/晋级门不变）、export.map_product（画布/导出同
   解释器）、viz.map_render.qgis|fallback（probe 诚实可用性）。无占位 provider；
   DATA_FORMAT/PREVIEW/MAP_COMPONENT 家族留词汇不内置。

## Consequences

- 新增一个算法 = 实现一个 descriptor+execute 的小对象并注册；获得 schema 校验、准入、
  隔离、provenance 与 agent 可见性，无需改核心。
- 数据产出必须进 catalog（register_derived/register_output）——目录权威不被绕过；
  zarr 目录 store 走 `register_derived_store`（结构性指纹，而非整读 sha）。
- `parameters_schema` 支持无依赖 JSON-schema 子集（type/required/enum/min-max/items/
  minItems/additionalProperties）；需要全量 JSON-schema 时由调用方自验，不引入硬依赖。
- 与 ModelProvider 世界的关系：不重造——tiled_onnx 委托原 provider；模型注册表/晋级门/
  manifest 继续是推理域权威。
