# Decisions — Interchange Delivery V5

## D1 — 新包 `paleo_workbench/interchange/`，不扩张 `resources/`

`resources/` 现有 classifier/import_service/exporters 是浅层 IO（分类/预览/转换），历史职责已重。
统一 adapter contract、preflight、package、batch 是新的深层能力，独立成包避免把
`resources/` 变成杂烩。`interchange` 调用 `resources/` 的既有 parser 与 `catalog/` 的
既有 service，不复制实现。

## D2 — Adapter 包装既有 parser，不重写 parser

- LAS: `geoviz_well_log.las_preview.inspect_las_file` + `native_backend.fast_las_parse_data` + lasio fallback（既有）。
- CSV/TSV/Excel: `csv` module + sniffing（新，但在 adapter 内）、pandas/openpyxl（既有）。
- Vector/Raster: GDAL `osgeo`（vendored，可选）与 rasterio（硬依赖），遵循 ADR 0060 惰性探测；**不手写矢量/栅格 parser**。
- SEG-Y: segyio（既有）只做 sniff/inspect/中小体 import 编排；transcode 继续走 `seismic_transcode.py`（不复制）。
- FLAC3D/Abaqus: `viz/geomodel/exporters.py`（既有 writer）+ 新增重读 verify。
- DLIS: 无 Python 依赖 → capability-unavailable adapter（明确报告，不伪实现）。
- VTK/OBJ/STL: capability-unavailable。

## D3 — 生命周期五段式：Inspect → Plan → Execute → Verify → Register

- inspect: 只读最小元数据。
- plan: 可 JSON 序列化的 `ImportPlan`（asset/version/managed/external/transform/warnings/estimated bytes）。
- execute: 经 `DataCatalogService.import_raw/link_external/register_*` 执行；取消安全（临时文件 + os.replace）。
- verify: 结构化重读（非存在性检查），输出 `ExportVerification` 四态。
- register: 通过 `record_export` / catalog run 记录 provenance。

## D4 — Package 格式：目录树 + 可选 zip 容器

Package = 目录（`manifest.json` + `project.paleo.json` + `artifacts/` + `CHECKSUMS`），可选
打包为 zip（`.paleopkg.zip`）。目录优先：避免 zip-only 的部分写入问题，天然支持大
artifact 流式拷贝；zip 仅作为传输容器，解包 fail-closed（I17）。不引入新数据库——
manifest 是 Catalog 已有 `CatalogDocument`/project JSON 的投影，Catalog 权威不变。

## D5 — Manifest V2 schema version = 2

现有 project JSON `schema_version=1`、catalog manifest `CATALOG_SCHEMA_VERSION=1`。
Package manifest 独立命名空间，从 `2` 起步以区分于两者，`manifest.kind = "paleo-package"`。

## D6 — Batch 并发模型：ThreadPoolExecutor + bounded workers（默认 2）

与全局资源治理（ADR 0064）一致：batch IO 属后台 lane，默认并发 2，可显式调低；
不使用进程池（避免 FD/内存翻倍），不无界。cancellation 通过共享 `CancelToken` 检查点
（每 item 开始前 + 阶段间）实现，item 内部长操作透传既有 cancel 回调。

## D7 — 路径安全统一模块 `interchange/path_safety.py`

所有解包/manifest 路径解析走同一入口：NFC 归一、拒绝绝对路径/`..`/symlink 逃逸/
Windows 保留名/casefold 碰撞/超长路径。fail-closed：拒绝而非跳过。

## D8 — UI 集成最小化：纯 model 层 + 现有对话框模式

I19 只提供 headless 可测的 Qt model（QAbstractTableModel 子类）与薄 dialog，复用
现有页面接线模式（如 data_page 的 import 流程）。不新增全局 QSS。

## D9 — Harness 边界

本分支只提供稳定 service/API（`paleo_workbench.interchange.*`），不注册 harness
ActionSpec、不建 workflow DAG。未来 Harness 分支可包装。

## D10 — 测试执行契约

使用 `run_env.sh <worktree> <tests>`（offscreen Qt、共享 geoviz PYTHONPATH、
python3.13）。GDAL 相关测试 `importorskip("osgeo.gdal")` 遵循既有模式；segyio/lasio
同样按需 skip。不重建 vendored QGIS，不运行 qgis-marked 测试。
