# Target State — Geoscience Interchange, Project Packaging & Batch Delivery V5

可勾选验收清单。每项完成时勾选并在括号内注明验证方式（测试文件 / 命令）。

## I1 — Adapter Contract

- [ ] `paleo_workbench.interchange` 包存在，定义统一 `FormatAdapter` protocol：`format_id / extensions / sniff / inspect / plan_import / import_data / plan_export / export_data / verify_output / capability`（tests/test_interchange_contract.py）
- [ ] `InterchangeRegistry`：按 format_id 注册/查询；`sniff_format(path)` 结合 extension + magic/header 有限读取，不依赖扩展名作为唯一判定（tests/test_interchange_registry.py）
- [ ] inspect 只读不写；plan 可 JSON 序列化；execute 可取消；verify ≠ 文件存在

## I2 — Import Preflight

- [ ] `ImportPreflightService.inspect(path)` 输出 detected format/size/metadata/CRS/units/warnings/estimated disk/managed-vs-external 建议（tests/test_import_preflight.py）
- [ ] preflight 失败时不产生任何 Catalog asset（fail-closed，测试断言 catalog 无新 asset）

## I3/I4 — Well-log & Tabular

- [ ] LAS adapter：header/curves/units/duplicate mnemonic/null/depth order/encoding/malformed 行 → 结构化诊断（tests/test_interchange_las.py）
- [ ] CSV/TSV adapter：delimiter/decimal/encoding sniff，header 别名，duplicate 行，坐标列识别（tests/test_interchange_tabular.py）
- [ ] Excel adapter：sheet 枚举 + 每表 inspect（依赖 openpyxl 已有）
- [ ] schema mapping plan 可序列化为 import preset，preset 不含绝对路径（测试断言）
- [ ] LAS 导出仅限已可靠表达的 CSV/JSON summary，带 verify

## I5/I6 — GIS Vector & Raster

- [ ] Vector adapter（GDAL 可用时）：Shapefile/GeoPackage/GeoJSON inspect（geometry 类型/feature 数/字段/CRS/encoding/sidecar 完整性/混合几何/无效几何诊断）（tests/test_interchange_vector.py）
- [ ] GeoJSON 导出 + verify（重新解析对比 feature 数/bounds）；GDAL 缺失时 GeoJSON 仍可用、capability 明确降级
- [ ] Raster adapter（GDAL/rasterio 可用时）：GeoTIFF inspect（geotransform/CRS/nodata/band/dtype/scale-offset）+ 导出前 finite/nodata/bounds/溢出检查（tests/test_interchange_raster.py）
- [ ] 大 raster 走 block/window IO（decimated overview 读取路径，无整文件读入 RAM 的实现）

## I7/I8/I9 — SEG-Y / 3D / Export Verification

- [ ] SEG-Y adapter：sniff/inspect（trace/sample/geometry/单位时间采样）、中小体 ingest 建议走既有 transcode/import 语义、checksum 指纹、cancel（tests/test_interchange_segy.py）
- [ ] SEG-Y export capability 明确 unavailable（registry capability 报告，不伪实现）
- [ ] FLAC3D/Abaqus export verify：重读解析、节点/单元数、结构校验（tests/test_interchange_model.py）
- [ ] VTK/OBJ/STL 为 capability-unavailable 声明
- [ ] 统一 `ExportVerification`：VERIFIED / VERIFIED_WITH_WARNINGS / FAILED / UNVERIFIED，且 UNVERIFIED 不在任何报告里显示为 Verified（tests/test_export_verification.py）

## I10/I11/I12 — Portable Package

- [ ] `PackageBuilder`：project → package 目录（project.paleo.json + artifacts/ + manifest.json + CHECKSUMS），external 引用三策略 keep/vendor/exclude（tests/test_project_package.py）
- [ ] Manifest V2：schema_version/identity/timestamp/app version/entries(relative path+sha256+size)/external/missing/provenance/total size，全部相对路径（tests/test_package_manifest.py）
- [ ] `verify_package(path)`：manifest/hash/缺失/未知文件/schema 版本/相对路径/path traversal/symlink（tests/test_package_verify.py）
- [ ] package → 新临时根 → reopen：managed artifacts 解析、external 引用仍显式、map product/version 可访问（tests/test_package_reopen.py）

## I13 — External Dependency Audit

- [ ] `ExternalDependencyAuditor`：valid/missing/changed/unknown/relink candidate 分类；依据 path+size+mtime+hash，禁止 basename-only 自动重连（tests/test_dependency_audit.py）
- [ ] relink 建议仅建议；执行复用 catalog 现有服务，不新增第二权威

## I14 — Batch Conversion

- [ ] `BatchConversionService`：bounded concurrency（默认 ≤2）、progress、cancellation、per-item result、failure isolation、summary、disk estimate（tests/test_batch_conversion.py）
- [ ] 1000 文件 metadata 批量测试无 FD 泄漏、内存平稳（tests/test_batch_scale.py）

## I15/I16 — Delivery Profiles & QA Report

- [ ] 内置 profiles：Internal Project Archive / Reviewer Package / Paper Figure Package / GIS Exchange / Modeling Handoff；JSON 可序列化；无硬编码机构名（tests/test_delivery_profiles.py）
- [ ] `DeliveryReport`：JSON + Markdown 双输出，含 assets/versions/formats/CRS/units/missing/external/warnings/verified/checksums/size/app version（tests/test_delivery_report.py）

## I17 — Security / Path Safety

- [ ] `safe_relative_path` / `safe_extract`：`../` traversal、绝对路径注入、symlink 逃逸、zip 恶意 entry、NFC 归一重复、casefold 碰撞、Windows 保留名、超长路径 全部 fail-closed（tests/test_path_safety.py）

## I18 — Compatibility Matrix

- [ ] fixtures：normal（minimal/Unicode 中文名/空可选字段/多层）+ damaged（truncated/坏 header/坏 encoding/缺 sidecar/错扩展名/缺 CRS/缺单位/校验和不匹配）+ cross-root（package→新路径/external 变更）（tests/test_compatibility_matrix.py）
- [ ] fixtures 全部程序化生成，小体积

## I19 — UI Integration

- [ ] Preflight 结果模型 + Batch 摘要模型 + Package 向导模型（纯 model 层，headless 可测）（tests/test_interchange_ui_models.py）
- [ ] 不新增全局 QSS，消费既有 tokens/样式

## I20 — Save/Reopen/Crash Consistency

- [ ] import/batch/export/package 的 cancel-before-commit、mid-copy failure（注入 fs 失败）、reopen 不留半成品、不污染 Catalog（tests/test_interchange_crash_consistency.py）
- [ ] 临时文件 + atomic rename 策略贯穿所有写入路径

## 硬约束

- [ ] Catalog 仍是唯一数据生命周期权威；无第二 asset/version 数据库
- [ ] 无第二套 Workflow DAG；batch service 仅 orchestration
- [ ] 不处理 100GB 地震体；SEG-Y 仅中小规模
- [ ] 不重建 vendored QGIS；native 并发 ≤2
- [ ] 三轮 review（correctness/architecture/adversarial）完成并修复
- [ ] 全部新测试本地通过；既有相关测试未回归
