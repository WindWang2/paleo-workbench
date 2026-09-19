# 14b-findings — interchange archive/OS/container/adapters（CONV-14 续作）

基线 `origin/main` `ff67dcf3`。本切片目标（用户任务书）：补齐 14-findings 明确
「不在本切片移植」的缺口 —— safe_members / archive validation / extract_archive /
os_replace_atomic / atomic output / package builder+verifier runtime /
FLAC3D+Abaqus interchange adapters / native import-export service。

## Scope ledger（分支边界）

**本分支负责（新移植，libs/interchange）**
- `interchange/path_safety.py` 的 `safe_members` / `extract_archive` /
  `os_replace_atomic`（首切片 D14-2 明确留下的三件）。
- `resources/exporters.py` 的 `atomic_output`（temp+replace 上下文语义，C++ RAII）。
- `interchange/package/verifier.py` 全量：`VerifyIssue` / `PackageVerifyReport` /
  `materialize_package` / `verify_package` / `_verify_directory` / `open_package` /
  `KNOWN_PACKAGE_EXTRA_FILES`。
- `interchange/package/verifier_zip.py` 全量：`verify_zip_container`（不解包校验）。
- `interchange/package/builder.py` 全量：`ExternalPolicy` / `PackageOptions` /
  `PackageItem` / `PackagePlan` / `BuildResult` / `PackageBuilder` /
  `zip_package_dir`（CatalogSource 抽象 seam 替代 Python catalog 对象）。
- `interchange/adapters/model_adapter.py` 全量：`MeshFacts` / `parse_flac3d` /
  `parse_abaqus` / `_StructuredModelAdapter` / `Flac3dAdapter` / `AbaqusAdapter`
  （写器复用 CONV-22 `pwb::geomodel::export_contract::legacy_export_to_*`，
  严禁复制解析器）。
- `interchange/registry.py` 的 `FormatAdapter.plan_import` 默认语义 +
  `InterchangeRegistry.capability_matrix`（model adapters 消费的窄面）。
- `interchange/contracts.py` 窄面：`CancelToken` / `NULL_CANCEL` /
  `ProgressCallback` / `FormatCapability` / `VerificationState` /
  `VerificationCheck` / `ExportVerification` / `ExportPlan` /
  `FormatNotSupportedError` / `CancelledError`。
- native import/export service 面（`service.hpp`）：capability matrix + inspect +
  plan_import/plan_export + export_data/verify_output 的适配器门面；package
  build/verify/materialize/open 由 `package_runtime.hpp` 自由函数直接暴露
  （同等 Python-free，两者共同构成 native import/export 面）。

**本分支不负责（显式归类，防重复实现）**
- `interchange/delivery.py`（DeliveryProfile/DeliveryService/DeliveryReportBuilder/
  render_report_markdown）：交付配置+QA 报告层，依赖 dependency_audit；
  **Python-only（removal-candidate：待 C++ catalog service 落地后移植）**。
  其 KNOWN_PACKAGE_EXTRA_FILES 与 os_replace_atomic 写报告模式已由本切片承载。
- `interchange/executor.py` / `batch.py`：批处理编排（Qt session/catalog 驱动），
  **Python-only（产品编排层）**。
- `interchange/dependency_audit.py`：依赖审计（catalog 对象驱动），**Python-only**。
- `interchange/registry.py` 的 `sniff_format`/`_sniff_*`：内容嗅探，C++ 侧
  preflight.hpp 已以 Sniffer seam 承载决策树；嗅探本体留给后续切片
  （well-log/segy magic 需要读文件样本语义）。
- 其余 adapters（las/tabular/raster/vector/segy/geojson）：依赖
  lasio/pandas/rasterio/GDAL/segyio/geoviz —— **需 C++ 引擎对位（QGIS/GDAL、
  well-log-engine），不属于本切片**；model_adapter 是其中唯一纯文本、无外部
  依赖的生产 adapter，故本切片先迁它。
- `viz/geomodel/exporters.py` 写器本体：**CONV-22 已移植**
  （libs/geomodel export_contract，geomodel_contract_oracle.json 冻结）——本分支
  只复用，不重复实现。

**共享/冲突文件（与其他并行 worktree）**
- `libs/interchange/**`（本分支主战场；CONV-21 只依赖它，不改它）。
- `libs/interchange/interchange_tests/CMakeLists.txt`（追加 archive 测试目标，
  纯追加；仅 `libs/interchange/src/manifest.cpp` 是对既有文件的行为保持重构）。
- apps/ 与 libs/ui 本切片零接线零改动（native service 的消费方在后续 UI/平台
  切片接入）。
- 根 `CMakeLists.txt`：**零改动**（PWB_BUILD_CONV_14 块已存在，新增文件都在
  libs/interchange/CMakeLists.txt 内追加）。
- `tools/oracle/generate_interchange_fixtures.py`：**不改**（首切片冻结物）；
  本切片新增独立生成器 `generate_interchange_archive_fixtures.py` +
  独立 fixture `interchange_archive_oracle.json`。
- `.goal-loop-ledger.md`：追加独立 section（惯例）。

## 逐符号 findings（新移植面）

### path_safety.py — `safe_members(archive, what)` / `extract_archive(...)` / `os_replace_atomic(...)`
- safe_members：逐 ZipInfo；`(external_attr >> 16) & 0o170000 == 0o120000`
  → `"{what}: symlink entry rejected: {name!r}"`；再 safe_relative_path +
  check_collision；返回规范化名列表（str(PurePosixPath)：尾部 `/` 丢弃、
  `.` 折叠）。顺序即 infolist 顺序。
- extract_archive：**validation-first**（全量 safe_members 先于任何字节落盘）；
  逐条 ensure_within_root；目录条目 mkdir；文件 1MiB 块流式拷贝；返回写入
  绝对路径表。失败即中止（调用方 materialize 负责 rmtree staging 零残留）。
- os_replace_atomic：os.replace + 目标父目录 fsync；Windows PermissionError
  指数退避 10 次（0.05·2^min(i,6)s）；最终失败 log+raise。POSIX 单次 rename。
- C++：ZipReader/ZipWriter（zlib raw deflate + 自实现 container：EOCD/CD/
  ZIP64 读；写器固定 date_time=(1980,1,1,0,0,0)、UTF-8 flag 0x800、>65535
  条目或 ≥4GiB 报错=中等规模上限）；条目名 cp437/UTF-8 flag 解码与 Python
  zipfile 一致；读取 CRC 校验。cancel seam：逐条目 checkpoint。
- oracle：真实 zipfile 造 zip（含 symlink/traversal/NFC/casefold/保留名/
  空档/嵌套目录/deflate+stored/corrupt 字节）base64 冻结；决策+消息+写盘
  相对路径表+内容 sha256+失败零残留断言。

### resources/exporters.py — `atomic_output(output_path)`
- mkstemp 前缀 `.{name}.` 后缀 suffix 于同目录；yield temp；成功
  `Path.replace`；失败 unlink temp 再 raise。C++ RAII `AtomicOutputFile`
  （O_EXCL 0600 + 随机 8 字符 [a-z0-9_]，commit 走 os_replace_atomic）。

### package/verifier.py + verifier_zip.py
- 报告结构/issue 顺序/全部中文文案逐条对齐（missing-manifest、corrupt-manifest
  前缀、wrong-kind、unsupported-schema、missing/corrupt-project、no-catalog
  warning、missing-entry、entry-is-directory、size-mismatch、checksum-mismatch、
  unknown-file、symlink-entry、symlink-extra、unsafe-entry、unsafe-manifest-path、
  total-size-mismatch、bad-zip、unsafe-zip-entry、missing-package）。
- JSON 解析错误尾巴（json.JSONDecodeError 文本）不可跨实现冻结 → oracle 对
  corrupt-project/catalog/manifest 冻结 severity+code+中文前缀，C++ 断言前缀。
- zip 侧 infos 映射：safe_members 返回名（去尾 `/`）与 infolist 位置配对 →
  manifest 条目按规范化名查 info；目录条目 → entry-is-directory。
- materialize：zip → `{stem 去 .paleopkg}` 目标 + staging + extract_archive +
  os_replace_atomic；dir → 先全量 symlink 扫描（`包内符号链接被拒绝: {p}`）
  再 copytree(symlinks=False, ignore=*.staging) + rename；目标已存在 →
  `目标已存在: {p}`。
- open_package = materialize + verify（fail-closed 报告）。

### package/builder.py
- plan()：project 条目恒 included；catalog 版本 external/missing/excluded
  （outputs-only、formats 过滤）/stale（size 与记录不符仍打包）/included；
  无 catalog → 项目 JSON resources 兜底（_ResourceShim：managed=not external、
  stage=input、size=None）。
- build()：staging `.{name}.staging` → 工程文件 → artifacts 树
  （INCLUDE_ARTIFACT_DIRS=raw/derived/intermediate/outputs/metadata/blobs，
  EXCLUDE=working/trash/cache/thumbnails，metadata 排除 catalog.sqlite*；
  symlink 即 `受管数据中出现符号链接: {p}`；rel 含 `{name}.artifacts/` 前缀，
  safe_relative_path(what="artifact path")）→ externals 按策略（keep/exclude
  记 manifest.external_dependencies；vendor → `artifacts/external/{asset}/
  {version_id or 'unknown'}/{basename}`）→ missing_dependencies → provenance
  （runs[:1000]+run_count、generated_outputs=output 版本 id[:1000]，任何
  catalog 异常静默返回空）→ total_size_bytes → write_manifest →
  os_replace_atomic 单次原子发布；任何异常 rmtree staging。
- _copy_payload：**先拷贝后哈希 staged 字节**（TOCTOU-safe）。
- zip_package_dir：`.{name}.tmp` → deflated、sorted rglob、symlink 拒绝
  （`包内出现符号链接: {p}`）→ os_replace_atomic；异常 unlink tmp。
- application_version：C++ 以构造参数显式注入（Python 读包内
  `__version__`）；artifact_dir_for = `<dir>/<stem>.artifacts`。
- CatalogSource seam：list_assets/list_versions/resolve_path（异常→
  `project.parent/version.path` 兜底）/export_manifest/list_runs。
- oracle：真实 PackageBuilder 跑合成工程树（datetime 定格 created_at）；
  plan.summary/manifest.json 字节/条目集/verify 报告全部冻结；绝对路径以
  `{ROOT}` 占位。

### adapters/model_adapter.py
- parse_flac3d/parse_abaqus：严格语法扫描（流式、行号 1 起）；
  `G id x y z`（5 token）/`Z B8 id n1..n8`（≥3 token 且 tokens[1]=="B8"，
  refs=tokens[3:] 恰 8）；Abaqus `*NODE` 4 列 / `*ELEMENT` 9 列 section 状态机
  （`**` 注释、`*END` 清空）；问题文案 `行 {n}: ...`；缺失引用
  `{len} 个单元引用了未定义的节点（如 [..3 个排序样本..]）`；节点编号连续性
  `节点编号不连续（max id {max} vs count {n}）`；坐标非有限值（Python
  float() 语义：nan/inf/infinity 大小写、下划线数字分隔）。
- adapter：capability（read=False/inspect=True/export=True/roundtrip_verify=
  True + notes）；inspect（stat→parse→gridpoints+zones=0 即
  `未识别到网格记录（不是本仓库写出的结构化网格）`；problems[:16] 进 errors、
  `结构问题共 {n} 处` warning）；plan_import=unsupported+
  `模型网格为导出专用格式：无导入路径`；import_data → FormatNotSupportedError
  `{id}: 模型网格无导入路径（仅导出）`；plan_export（后缀必须 .f3grid/.inp、
  nx/ny/nz 必填 `缺少网格维度参数: {', '.join(missing)}`、min<1 或积>8e6 →
  `网格维度非法或超过导出规模上限`、estimated=(n+1)³·64+n³·64）；export_data
  （atomic_output + geomodel legacy writer 字节）；verify_output（reparsable/
  gridpoint_count/zone_count，`预期 {e}，实际 {a}`；结构问题 →
  `结构问题: {'; '.join(problems[:4])}`）。
- oracle：真实 export_to_flac3d/export_to_abaqus 小网格产物 + 手工坏档
  （G 记录坏值/引用缺失/编号断档/nan/inf/7 引用/空文件/无关文本）冻结
  MeshFacts；verify_output 全 checks；plan 错误文案。

## 验收面
- ctest 目标 `interchange.archive`（zip/atomic/package/model 四段 replay +
  安全负例 + 零残留 + cancel seam + 双树编译）。
- oracle 生成器 `tools/oracle/generate_interchange_archive_fixtures.py`
  （真实 import，无手写期望；datetime/随机性定格）。
