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
- register: **导入与导出双侧都记录 provenance**（评审轮次修正）：
  - 导入：`ImportExecutor` 通过 `DataCatalogService.register_run` 记录
    `interchange.import` run（成功 completed / 失败 failed，带 plan 参数）。
  - 导出：`ExportExecutor(catalog=...)` 在校验通过后走仓库唯一导出咽喉点
    `catalog.lifecycle.register_export_output`（与 `project.artifacts.record_export`
    同一实现），OUTPUT 资产 kind="export"，run 带源版本 lineage
    （`ExportPlan.source_version_ids`/`linked_id`）；校验失败导出记录为
    failed export run，绝不伪装成功。
  - 已知不对称（记录在案）：`import_raw` 不接受 run_id，故导入版本缺少
    version→run 反向指针（run→version 已建立）；待 catalog 暴露该能力后补齐。

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
模型文件按仓库惯例放在 `paleo_workbench/ui/pages/interchange_models.py`
（评审轮次从 interchange/ 迁入，依赖方向 ui→interchange）。

## D9 — Harness 边界

本分支只提供稳定 service/API（`paleo_workbench.interchange.*`），不注册 harness
ActionSpec、不建 workflow DAG。未来 Harness 分支可包装。

## D10 — 测试执行契约

使用 `run_env_io.sh <worktree> <tests>`（offscreen Qt、共享 geoviz PYTHONPATH、
python3.13）。GDAL 相关测试 `importorskip("osgeo.gdal")` 遵循既有模式；segyio/lasio
同样按需 skip。不重建 vendored QGIS，不运行 qgis-marked 测试。

## D11 — 嗅探置信度策略（评审轮次确立）

- 内容证据分三级：high（magic/结构特征，如 TIFF magic、SQLite-GPKG app-id、
  SEG-Y 3500 偏移 revision 标记、LAS ~V 段、GeoJSON FeatureCollection 标记）；
  medium（结构性启发）；low（扩展名+弱信号）。
- high 且与扩展名冲突 → 硬错误（fail-closed）。
- medium/low 且与扩展名冲突 → 仅建议（warning），按扩展名 adapter 解析。
- 纯文本可打印率不再作为 SEG-Y 证据（曾导致任意 ≥3.6KB 文本被误判并拒绝导入）。

## D12 — 包完整性校验口径（评审轮次确立）

manifest 自身也受校验：条目 NFC/casefold 重复拒绝；`total_size_bytes` 与逐条
校验合计必须一致；`schema_version` 必须是 JSON 整数；zip 容器条目不得是目录；
目录形式解包前先做 symlink 全树拒绝（validate-then-copy），杜绝借符号链接
内联包外内容。
