# 14-findings — interchange 纯核（path_safety / package manifest / preflight）

基线 `origin/main` `35987e13`。§5 清单全部文件已 **Read 全文**（非 grep）。
本文按文件索引，每个公开符号给出：输入 / 输出 / 边界（空、非法、并列）/ 与已有 C++ 核
的关系 / 测试缺口。C++ 侧目标库 `libs/interchange`（新增，Qt-free、Python-free，
仅依赖 Pwb::Domain 的 Json 约定），冻结 oracle 由
`tools/oracle/generate_interchange_fixtures.py` 用系统 python3（可 import
paleo_workbench 0.2.17a0，unicodedata Unicode 16.0.0）跑真实模块生成。

---

## paleo_workbench/interchange/path_safety.py（223 行，本切片主移植对象）

模块级策略：一切「manifest 字符串 / 归档条目名 → 文件系统路径」必须走本模块；
fail-closed：可疑输入抛 `UnsafePathError`（`ValueError` 子类），绝不静默消毒。
防御面：`../` 穿越与绝对路径注入（POSIX+Windows 形式）、symlink 逃逸、
NFC 归一后的重名、casefold 大小写碰撞、Windows 保留设备名、超长路径。

### `UnsafePathError(ValueError)`
- 输入：不直接构造（由各校验函数抛出）。输出：fail-closed 拒绝信号。
- C++ 关系：`pwb::interchange::UnsafePathError : std::runtime_error`；
  oracle 冻结的是**消息文本**（含 Python `repr` 语义），不是异常类型层级。
- 空值：无空概念——任何一次拒绝都以消息完整呈现。
- 测试缺口：现有 pytest 只断言 `raises(UnsafePathError)`，**消息文本从未被断言**；
  oracle 需要冻结每条消息（这是 C++ 侧可对账的最强契约）。

### `MAX_COMPONENT_LEN = 200` / `MAX_RELATIVE_LEN = 900`
- 单组件与整串相对路径的字节上限（Python 按 str 长度=码点数计）。
- C++：UTF-8 长度≠码点数，必须按码点数截断/计数（sanitize_filename 同理）。
- 测试缺口：现有测试只测 `"x"*300` 与 400 层目录，中文字符长度未测 → oracle 补。

### `_WINDOWS_RESERVED` / `_BAD_CHARS_RE`
- 保留名：CON PRN AUX NUL + COM1..9 + LPT1..9（大写比较）。
- 坏字符正则 `[<>:\"|?*\x00-\x1f]`（NUL 已被更早分支拒绝，但区间仍含它）。
- 注意 stem 规则：`part.split(".")[0].upper()` → `con.txt` 命中、`console` 不命中。
- C++：手写等价判定（字符集循环），无需正则引擎。
- 测试缺口：`LPT4`、`aux`（小写）、`com1 .txt`（尾空格先触发）未测 → oracle 补。

### `safe_relative_path(name, *, what="entry") -> PurePosixPath`
- 输入：任意 str；`what` 仅进错误文案。输出：合法相对 POSIX 路径对象。
- 判定顺序（**决定错误消息，顺序不可换**）：
  1. 空/全空白 → `{what}: empty path`；
  2. `\x00` in name → `{what}: NUL byte in {name!r}`；
  3. `unicodedata.normalize("NFC", name) != name` → `{what}: non-NFC path {name!r}`
     （**拒绝而非改写**：两个 manifest 条目不得只差归一形）；
  4. `PurePosixPath(name.replace("\\","/"))` 后：`is_absolute()` 或
     normalized 以 `/` 开头 或 `^[A-Za-z]:` 命中（**在未替换反斜杠的 normalized 上**）
     → `{what}: absolute path not allowed: {name!r}`；
  5. parts 为空 → `{what}: no components in {name!r}`（如 "."）；
  6. 逐组件：`.`/`..` → traversal；`not part.strip()` → blank component；
     `part != part.rstrip(" .")` → trailing dot/space（NTFS 静默截断防线）；
     `len(part) > 200` → too long（文案含 **name** 而非 part）；
     `part.split(".")[0].upper()` 保留名 → Windows reserved name；
     坏字符 → reserved character；
  7. `"/".join(parts)` > 900 → `{what}: path too long: {name!r}`。
- PurePosixPath 语义要点：`"."` 组件被丢弃（`a/./b.txt` 合法 ≡ `a/b.txt`）；
  重复 `/` 折叠；尾部 `/` 丢弃；`..` **保留**给组件循环判穿越。
- C++：返回 `std::string`（join 后的相对路径）即可满足全部下游
  （`str(pure)` / `as_posix()` 是唯一被消费的形态）。NFC 判定用生成的
  Unicode 16.0.0 表（算法分解 + 组合排除 + CCC 排序 + Hangul 公式）。
- 测试缺口：现有 17 个拒绝案例 + 4 个接受案例；缺 NFC 中文、`a/./b` 变体、
  `LPT9`、`\u007f`（DEL，落在 \x7f 不在坏字符区间 → **合法**，Python 同）、
  组件恰 200 码点等边界 → oracle 全部补齐并冻结消息。

### `check_collision(name, seen_casefold, seen_nfc)`
- 输入：已过 safe_relative_path 的名字 + 两个集合（可变，原地更新）。
- 先 NFC 精确重复 → `duplicate entry after normalization: {key!r}`；
  再 `casefold` 碰撞 → `case-insensitive collision: {key!r}`；否则双双登记。
- casefold 是 full case folding（ß→ss、Σ→σ…），C++ 用生成的逐码点折叠表。
- 空集合起点由调用方持有（manifest.validate_paths、safe_members、verifier）。
- 测试缺口：现有 zip 测试覆盖 `Data/file.txt` vs `data/file.txt`；NFC 重复
  （两个 NFD 变体都先被 safe_relative_path 拒绝 → 真正能到 collision 的只有
  已 NFC 相等串）→ oracle 明确这条路径语义。

### `ensure_within_root(root, candidate) -> Path`
- `root.resolve()`；candidate 是 symlink → `symlink rejected: {candidate}`；
  `candidate.resolve()` 后不等于 root 且 root 不在其 parents → `path escapes package root: {candidate}`。
- 解析跟随 symlink，所以「被 symlink 的目录下的文件」也会被 root 包含性检查抓住。
- C++：`std::filesystem::weakly_canonical` + 前缀比较（POSIX 本切片）；
  错误文案含调用方传入的 path 字面量（Python `str(Path)`）。
- 测试缺口：现有 3 例（inside/escape/symlink-escape）；缺「root 本身是 symlink」
  与「candidate==root」→ oracle 用双方运行时各自临时目录重放（oracle 只冻
  决策 inside/symlink/escape + 相对余量，不冻绝对路径）。

### `safe_members(archive, *, what="archive") -> list[str]`
- zip 专有：`ZipInfo.external_attr>>16 & 0o170000 == 0o120000`（S_IFLNK）→
  `{what}: symlink entry rejected: {name!r}`；逐条 safe_relative_path +
  check_collision；返回规范化名字列表。
- **不在本切片移植**：C++ Qt-free 核无 zip 容器读取器；manifest/路径规则
  已由 safe_relative_path + check_collision 完整承载。记入 decisions。
- 测试缺口（Python 侧）：external_attr 位运算分支有覆盖（link.zip）。

### `extract_archive(archive, dest_root, *, what="package") -> list[Path]`
- 先全量验证（safe_members）再写任何字节（validation-first，恶意包零落盘）；
  目录条目 mkdir，文件 1MiB 块拷贝；返回写入路径表。
- **不在本切片移植**（同上，zip 依赖）。语义已由 tests/test_path_safety.py
  TestZipExtraction 在 Python 侧钉死。
- C++ 侧不提供 `extract_archive`；不伪造。

### `sanitize_filename(stem, fallback="export") -> str`
- NFC 归一 → 替换 `[<>:\"|?*\x00-\x1f/\\]` 为 `_` → `strip(" .")` →
  空则 fallback → stem 保留名则前缀 `_` → 截 200 码点。
- 现有断言：`a/b<c`→`a_b_c`、`CON`→`_CON`、`""`→`export`、`"  . "`→`export`、
  500 字符 ≤200。注意 `"  . "`：替换不改 → strip 后空 → fallback（**非**前缀 _）。
- 测试缺口：非 ASCII（中文）、非 NFC 输入（sanitize 是全模块唯一**改写** NFC 的口）→ oracle 补。

### `is_reserved_or_unsafe(name) -> bool`
- 包装 safe_relative_path 的布尔视图；`data/file.bin`→False，`../x`/`CON`→True。
- C++：一行 try/catch。oracle 与 safe_relative_path 案例同表复用。

### `os_replace_atomic(temp_path, target_path)`
- os.replace + 目录 fsync；Windows 过滤驱动锁 10 次指数退避；最终失败 log+raise。
- **不在本切片移植**：OS 语义层（Windows 重试策略对 POSIX 无意义，POSIX 无
  对应过滤驱动问题）。C++ manifest 写盘用一次性 temp+rename 实现（decisions 记录）。

---

## paleo_workbench/interchange/package/manifest.py（151 行，本切片主移植对象）

### `MANIFEST_FILENAME = "manifest.json"` / `MANIFEST_KIND = "paleo-package"` / `MANIFEST_SCHEMA_VERSION = 2` / `SUPPORTED_SCHEMA_VERSIONS = (2,)`
- 常量即契约；schema_version=2 与 project JSON 的 1、catalog manifest 的 1 区分
  （interchange-delivery-v5 decisions.md D5）。C++ `inline constexpr` 同值。

### `PackageEntry`（path/sha256/size_bytes/kind="artifact"）
- `to_dict()` 键序：path, sha256, size_bytes, kind（**有序**，影响 dumps 字节）。
- `from_dict`：path/sha256/size_bytes 强转 str/str/int；kind 缺省 "artifact"。
- kind 词汇：`"project" | "artifact" | "metadata"`（builder 写入）。
- C++：nlohmann::ordered_json 保持键序；oracle 冻结 dumps 全文。

### `PackageManifest`
- 字段：kind/schema_version/project_name/project_file/created_at/
  application_name="paleo-workbench"/application_version/entries/
  external_dependencies/missing_dependencies/generated_outputs/provenance/
  options/total_size_bytes。
- `to_dict()` 键序（**manifest.json 的字节布局**）：kind, schema_version,
  project{name,file}, created_at, application{name,version}, entries[],
  external_dependencies, missing_dependencies, generated_outputs, provenance,
  options, total_size_bytes, **entry_count（= len(entries)，由 to_dict 派生）**。
- `from_dict`：`schema_version` 必须是 JSON int 且非 bool
  → 否则 `ValueError(f"schema_version 必须是整数，得到 {raw_version!r}")`
  （repr：True→`True`、2.0→`2.0`、`"2"`→`'2'`）；application.name 缺省回
  "paleo-workbench"；其余键宽松缺省。
- `dumps()`：`json.dumps(to_dict(), ensure_ascii=False, indent=1)` ——
  无 BOM、非 ASCII 原样 UTF-8、缩进 1 空格、`": "` 分隔。
  C++ `ordered_json::dump(1, ' ', false)` 需逐字节对账（oracle 冻结全文）。
- `entry_paths()` → set(entries.path)（verifier 的 known 集合用）。
- `validate_paths()`：逐 entry `safe_relative_path(path, what="manifest entry")`
  + `check_collision`（共享两个 seen 集）；`project_file` 非空再过一次
  （what="manifest project file"）。fail-closed：任何 UnsafePathError 上抛。
- 测试缺口：现有测试只断言相对性/无 `..`；**无 dumps 字节对账、无 from_dict
  错误文案对账** → oracle 补（含中文文件名、嵌套 entries、错误 schema 类型）。

### `write_manifest(manifest, package_root) -> Path`
- validate_paths 先行 → `atomic_output` 写 `{root}/manifest.json`（UTF-8 文本）。
- C++：校验 + temp+rename 写；不移植 atomic_output 的 mkstemp 细节（decisions）。

### `read_manifest(package_root) -> PackageManifest`
- `json.loads(读文件)` → from_dict → validate_paths；损坏 JSON / 不安全路径上抛。
- C++：nlohmann parse（异常文案与 Python JSONDecodeError **不逐字对账**，
  记 decisions）；from_dict/validate_paths 层逐字对账。

---

## paleo_workbench/interchange/preflight.py（218 行，本切片主移植对象：纯决策层）

契约：preflight 严格只读；失败绝不建 catalog 资产（executor 只在通过的计划上跑）。

### `PreflightIssue(severity, code, message)` + `to_dict()`
- severity ∈ {"info","warning","error"}；to_dict 键序 severity,code,message。
- C++：struct + ordered_json。

### `PreflightReport`
- 字段：path/sniff/adapter_id/inspection/issues[]/recommendation
  （默认 "unavailable"；词汇 managed_copy|link_external|unavailable）/
  estimated_disk_bytes(=0)。
- `ok` 属性 = 无 severity=="error" 的 issue。
- `to_dict()` 键序：path, sniff{format_id,confidence,evidence}, adapter_id,
  inspection(=inspection.summary() 或 None), issues[], recommendation,
  estimated_disk_bytes, ok。**注意 sniff 的 to_dict 不含 extension 字段**
  （SniffResult 四字段只序列化三个）。
- C++：inspection 以 `summary()` 等价的 Json 表示传入/传出。

### `ImportPreflightService.inspect(path) -> PreflightReport`（决策树，逐分支）
1. 不存在 → sniff=("",low,"missing-file",ext)，issue=error/missing-file/"文件不存在"，
   直接返回（adapter_id=None, inspection=None, recommendation 默认 unavailable, 0 字节）。
2. 目录 → sniff=("",low,"directory","")，issue=error/directory/"目录导入请使用批量服务"。
3. `sniff_format(path, registry)`；`sniffed_id = SNIFF_FORMAT_ALIASES.get(id, id)`
   （geotiff→raster、gpkg→vector_gdal、shapefile→vector_gdal）；
   `extension = path.suffix.lower().lstrip(".")`。
4. determined 才取 adapter=registry[sniffed_id]：
   - adapter 为 None 且扩展名命中 extension_adapter：
     - determined 且 confidence=="high" → **error** extension-content-mismatch
       （文案：`扩展名 .{ext} 指向 {ext_adapter.format_id}，但内容嗅探为 {sniff.format_id}（{sniff.evidence}）`，注意源码里字符串相接无空格，实际消息形如
       `扩展名 .tif 指向 raster，但内容嗅探为 las（las-version-section）`——
       `（{evidence}）` 后还有 `，`？逐字以 oracle 为准，源码为
       `f"扩展名 .{extension} 指向 {extension_adapter.format_id}，" f"但内容嗅探为 {sniff.format_id}（{sniff.evidence}）"`）；
       adapter=None；
     - determined 且非 high → **warning** sniff-advisory + 按 extension_adapter 解析
       （文案含 `置信度 {confidence}；按扩展名按 {id} 解析`——逐字以 oracle 为准）；
     - 未 determined（sniff 空）→ 直接用 extension_adapter，**无 issue**。
   - adapter 非 None 且 extension 非空且 extension ∉ adapter.extensions →
     **warning** extension-mismatch（`内容识别为 {id}，但扩展名为 .{ext}`）。
5. adapter 仍为 None → **error** format-unknown（"无法识别格式（无内容特征且扩展名未注册）"），
   返回（recommendation=unavailable）。
6. `inspection = adapter.inspect(path)`；errors→逐条 error/inspect-error/{msg}；
   warnings→逐条 warning/inspect-warning/{msg}。
7. `capability.import_data` False → **error** import-unavailable
   （文案=notes 非空则 notes，否则 `{id} 不支持导入`），recommendation=unavailable；
   elif inspection 不 ok → unavailable；else **managed_copy**。
8. `estimated = inspection.size_bytes if inspection.ok else 0`（注意：7 的
   import-unavailable 分支后 estimated 仍按这行取——unavailable 时 report 显式
   estimated 参数只给 unavailable 返回分支传 0；主干分支 `estimated` 取值如上）。
   **主干返回的 report 不显式传 recommendation=unavailable（7 的第一子分支也走
   主干 return，此时 recommendation="unavailable" 已赋值）**。逐字以 oracle 冻结。
- C++：把「内容嗅探 + 真实解析」抽象为输入（sniff 三元组 + InspectionInput），
  注册表 AdapterSpec（format_id/extensions/import_data/notes）来自真实
  `build_default_registry().capability_matrix()` 冻结表；重解析引擎
  （rasterio/segyio/geoviz/GDAL）留在 Python，不在本切片（decisions）。
- 测试缺口：现有 pytest 走真实 LAS/sniff，C++ 无法复刻 geoviz 解析 →
  oracle 用**stub 适配器驱动真实 ImportPreflightService** 冻结全分支决策表
  + 真实注册表的三条无解析分支（missing/dir/unknown）。

### `ImportPreflightService.plan(path, *, managed, asset_name, options) -> ImportPlan`
- report 不 ok / adapter_id None / inspection None →
  `PreflightFailedError("；".join(错误 messages) or "preflight 未通过，无法生成导入计划")`。
- managed_effective = managed if managed is not None else True → adapter.plan_import。
- C++：`plan_error_message(report)` 纯函数（join 逻辑）冻结；plan_import 本体
  （默认计划组装）随 contracts 的 ImportPlan 词汇一并记录，不在本切片移植
  （catalog 执行链不在纯核范围）。

---

## paleo_workbench/interchange/contracts.py（277 行）

### 异常族 `InterchangeError` / `FormatNotSupportedError` / `PreflightFailedError` / `CancelledError`
- 语义分层：基础失败 / 无适配器或能力 / preflight 拒绝（未登记任何东西）/
  取消检查点触发。C++ 对应异常类型（message 逐字，类型层级简化，decisions）。

### `CancelToken`（+ `NULL_CANCEL`）
- cancel(reason) 幂等记首次；check()/checkpoint() 在取消时抛 CancelledError(reason or "cancelled")。
- 线程安全的合作式取消；写入侧全部 temp+原子替换，故中途取消不破旧状态。
- C++：本切片纯核无长操作，不移植（executor/batch 属 M9 后续切片）；findings 留档。

### `SniffResult(format_id, confidence, evidence, extension="")`
- `determined` = format_id 非空。confidence ∈ high/medium/low。
- **to_dict 形态只出现在 PreflightReport.to_dict**（三字段，无 extension）。
- C++：struct 同字段；`sniff_format` 本体属 registry（见下）。

### `FormatCapability(read, inspect, import_data, export, roundtrip_verify, notes)`
- 「诚实声明」的能力六元组；unavailable 适配器全 False + notes 说明。
- C++：进 AdapterSpec 冻结表（import_data/notes 参与决策；其余仅报告面）。

### `VerificationState` / `VerificationCheck` / `ExportVerification`
- 四态 VERIFIED / VERIFIED_WITH_WARNINGS / FAILED / UNVERIFIED；
  `ok` = 前两态；`unverified(detail)` / `failed(checks, detail)` 工厂；
  `summary()` 键序 state,detail,warnings,checks[{name,passed,detail}]。
- **UNVERIFIED 永不呈现为 Verified**（tests/test_interchange_contract.py 钉死；
  delivery 报告 markdown 也逐字断言）。
- C++：本切片不移植（导出校验链属后续切片）；词汇已记，防后续漂移。

### `InspectionResult` + `summary()`
- 字段 format_id/ok/size_bytes/metadata/crs/units/dataset_bounds/object_type/
  warnings/errors；summary() 键序 format_id,ok,size_bytes,crs,units,object_type,
  bounds(None 或 [4]),metadata,warnings,errors。bounds 为 4 元组或 None。
- C++：preflight 核消费其 ok/size_bytes/errors/warnings + summary() 键序；
  其余字段透传（Json）。

### `ImportPlan`（to_dict/from_dict 往返恒等——有 pytest 钉死）
- action 词汇 managed_copy|link_external|transform_import|unsupported。
- C++：本切片仅冻结 `PreflightFailedError` 文案与 to_dict 词汇，不移植结构。

### `ImportExecutionResult` / `ExportPlan`
- 执行/导出侧结果与计划；`ExportPlan.source_version_ids`（lineage）与
  `linked_id` 是 export provenance 咽喉点的关键字段（verifier 轮修正）。
- C++：不移植（executor 链后续切片）。

---

## paleo_workbench/interchange/registry.py（344 行）

### `SNIFF_PREFIX_BYTES = 8192` / `SNIFF_FORMAT_ALIASES`
- 嗅探只读前缀（有界）；别名把内容家族映射到适配器 id。
- C++：别名表进 preflight 核（决策树用）；PREFIX 常量随嗅探本体留 Python。

### `FormatAdapter`（抽象）
- 类属性 format_id/display_name/extensions；`sniff` 默认 low/extension 证据；
  `matches_extension`；抽象 capability/inspect；`plan_import` 默认
  （inspection 不 ok→unsupported，managed→managed_copy 否则 link_external，
  asset_name 缺省=文件名，warnings/estimated/metadata/options 透传）；
  import/plan_export/export/verify 默认抛 FormatNotSupportedError。
- C++：不移植类层级；AdapterSpec 承载决策所需投影（decisions：投影而非仿真）。

### `InterchangeRegistry`
- register（重复且非 replace→ValueError `duplicate adapter format_id: {id}`；
  空 format_id→ValueError）/ get / adapters（插入序）/ adapter_for_extension
  （扩展名先 lower 去 "."，**按注册序第一个命中**）/ capability_matrix（行键序
  format_id,display_name,extensions,read,inspect,import,export,roundtrip_verify,notes）。
- C++：`pwb::interchange::Registry` 同语义（数据驱动 AdapterSpec）；
  oracle 冻结真实默认注册表全表。
- 测试缺口：registry 的 ValueError 文案现有测试未对账 → oracle 冻结。

### 嗅探器（`_read_prefix/_printable_ratio/_sniff_gpkg/_sniff_zip_family/_sniff_text/sniff_format`）
- gpkg：SQLite magic + 68 偏移 "GPKG"（high）。
- zip 家族：PK\x03\x04 → 扫本地头名字：[Content_Types].xml/xl/workbook.xml→xlsx
  (high)、__descriptor__→factor_grid (high)、否则 zip (medium)。
- TIFF magic II*/MM* → geotiff（扩展名 tif/tiff→high else medium，证据相应两态）。
- Shapefile：首 4 字节大端 9994 → high。
- 文本（可打印率≥0.9）：FeatureCollection→geojson high；type+Feature+geometry→
  geojson medium；~V/VERS.→las high；~VERSION/WRAP+ASCII→las medium；
  *HEADING/*NODE→abaqus_inp high；`G `+f3grid→flac3d medium；
  sgy/segy 且 ≥3600B→segy low（extension-size）。
- SEG-Y 3600 后：3500 偏移 `SEG` →（扩展名 sgy/segy?high:medium）segy；
  elif sgy/segy 且前 3200 可打印率>0.75 → segy low。
- 候选按 confidence rank 排序取首（stable? Python sort 稳定，插入序决胜）。
- C++：**不在本切片**（读文件内容属 I/O 嗅探，纯决策已由 preflight 核覆盖）；
  stub 驱动的 oracle 已覆盖 sniff 结果 → 决策的全部映射。decisions 记录。

### `default_registry()`
- 转发 adapters.build_default_registry；注册序：las,csv,tsv,xlsx,geojson,
  vector_gdal,raster,segy,flac3d_f3grid,abaqus_inp,dlis,vtk_model,mesh_exchange。
- oracle 直接冻结名单+扩展名+能力（adapter_for_extension 顺序依赖它）。

---

## paleo_workbench/interchange/package/builder.py（438 行）

- `INCLUDE_ARTIFACT_DIRS=("raw","derived","intermediate","outputs","metadata","blobs")` /
  `EXCLUDE_ARTIFACT_DIRS=("working","trash","cache","thumbnails")` /
  `EXCLUDED_METADATA_FILES=("catalog.sqlite","-wal","-shm")`（sqlite 是可重建索引
  非可携真相，ADR 0056）。
- `ExternalPolicy.KEEP/VENDOR/EXCLUDE`；VENDOR 路径
  `artifacts/external/{asset}/{version_id or 'unknown'}/{basename}`（version_id 防碰撞）。
- `PackageOptions(external_policy, include_outputs_only, include_formats, include_provenance)`。
- `PackageItem(version_id, asset_name, path, size_bytes, stage, status, detail)`；
  status 词汇 included|external|missing|stale|excluded；stale=size 与 catalog 不符
  （仍打包，一条诚实记录）。
- `PackagePlan.summary()`：counts 按 status 计数 + project_file + estimated_bytes +
  excluded_dirs。
- `PackageBuilder`：构造即校验 `.paleo.json` 后缀（ValueError `不是工程文件: {name}`）；
  `plan()`（project 条目 + 逐版本分类）；`build()`（staging 目录 + 单次原子改名，
  已存在→FileExistsError；异常清 staging）；`_copy_payload` **拷贝后哈希**
  （TOCTOU）；`_copy_artifacts_tree`（symlink 先于 is_dir 检查→ValueError 显式拒；
  metadata 排除 sqlite；rel=相对 artifacts_dir.parent）；`_handle_externals`
  （keep/exclude 记录，vendor 缺文件→missing）；`_record_provenance`
  （runs 截 1000，run_count 全量）；`_iter_project_resources`（无 catalog 时从
  工程 JSON resources[] 读外部引用，`_ResourceShim` 伪装 managed/id/stage/size）。
- `zip_package_dir`：临时 zip + os.replace 原子发布；symlink→ValueError。
- C++：**本切片不移植**（catalog 依赖 + 大文件流式拷贝属 M9 执行切片）；
  manifest 内核为其唯一被移植产物。测试缺口无（Python 侧覆盖良好）。

## paleo_workbench/interchange/package/verifier.py（261 行）

- `VerifyIssue`（severity/code/message + as_dict 键序 severity,code,message）；
  `PackageVerifyReport`（ok=无 error；errors()/warnings() 过滤；to_dict 键序
  package_path,ok,checked_entries,total_size_bytes,issues,project_name）。
- `materialize_package`：zip → validate-then-extract（extract_archive 已先验全部
  名字）；目录 → **先全树 symlink 拒绝再 copytree**（防解引用内联包外内容）。
- `verify_package(deep=True)`：zip 走 verifier_zip，目录走 `_verify_directory`：
  missing-package / missing-manifest / unsafe-manifest-path / corrupt-manifest /
  wrong-kind / unsupported-schema / missing-project / corrupt-project /
  corrupt-catalog / no-catalog(warning) / unsafe-entry / symlink-entry /
  missing-entry / size-mismatch / checksum-mismatch（deep，**error 非 warning**）/
  symlink-extra(error) / unknown-file(warning，KNOWN_PACKAGE_EXTRA_FILES=
  delivery-report.json/md 豁免) / total-size-mismatch（manifest 不得谎报）。
- `open_package`：materialize+verify，失败报告照实返回。
- C++：**本切片不移植**（校验循环依赖 sha256_file 与 fs 遍历；规则文本已记，
  后续切片对账）。已知包外文件豁免集是 `frozenset({"delivery-report.json","delivery-report.md"})`。

## paleo_workbench/interchange/package/verifier_zip.py（126 行）

- 不解包校验 zip：safe_members → 缺 manifest→error；from_dict+validate_paths 失败→
  corrupt-manifest；kind/schema 同目录版；project_file/catalog.json 逐条解析；
  条目缺失/目录化（entry-is-directory）/size/sha256（1MiB 块流式）；未知文件 warning。
- C++：本切片不移植（zip 依赖）。entry-is-directory 与 info.file_size 口径已记。

---

## paleo_workbench/interchange/adapters/（9 文件）

### `adapters/__init__.py: build_default_registry()`
- 注册序见上；**顺序即 adapter_for_extension 的优先级**（geojson 在 vector_gdal
  前，故 .geojson 归 geojson 适配器）。

### `las_adapter.py: LasAdapter`（format_id="las"，extensions=("las",)，resource_type="well_log"）
- `capability`：read/inspect/import/export/roundtrip 全 True，notes「导出仅支持
  CSV/JSON 摘要（lasio）；不提供 LAS 写入器」。
- `_FULL_SCAN_MAX_BYTES=64MiB`：超过只报头事实（header_only），并移除「数据区空」
  误报、加「跳过深度顺序检查」。
- `inspect`：size 失败→error「无法读取文件状态: {exc}」；geoviz
  `inspect_las_file` 头解析（well_name/null_value/wrapped/delimiter/row_count/
  curves[{mnemonic,unit,description}]）；重复助记名（排序去重逗号 join）warning；
  row_count≤0 warning「~A 数据区为空或不可读」；units 按曲线。
  geoviz 不可用 → 有界回退解析（~C 段曲线、NULL/WELL 键），warning
  「geoviz 引擎不可用：使用受限头解析（无行数统计）」。
- `_check_encoding`：前 8192 字节非 UTF-8 → warning「文件前缀不是有效 UTF-8…」。
- `_parse_depth_header`：STRT/STOP/STEP 正则（MULTILINE+IGNORECASE）。
- `_scan_ascii_stream/_scan_ascii_lines`：~A 段流式；列数不足/非数值→malformed
  计数；null/非有限深度不入方向链（不锁方向）；方向 increasing/decreasing 首次
  差分锁定；反向→non_monotonic 计数；warning 文案三条（行格式异常 / 空值 /
  顺序异常）；`_check_declared_extent`：rows+1 < STRT/STOP/STEP 推算 → 截断警告。
- `plan_import`：metadata.setdefault("object_type","well_log")。
- `import_data`：catalog.import_raw（type=well_log, format=las）。
- `plan_export`：目标后缀限 .csv/.json（否则 FormatNotSupportedError「LAS 仅支持
  导出为 CSV 或 JSON 摘要；不提供 LAS 写入器」）；estimated=源 size；warning
  「LAS 导出为摘要转换…」。
- `export_data`：las_to_csv / las_to_json_summary（resources.exporters）经 atomic_output。
- `verify_output`：JSON 路径 json_parsable + curve_names_preserved（源曲线名集合
  ⊆ 输出 mnemonic 集合，detail 计数）；CSV 路径 csv_parsable + 行数<2 →
  csv_nonempty_data fail + 表头缺列→warnings；fail→FAILED；有 warning→
  VERIFIED_WITH_WARNINGS；否则 VERIFIED。
- `plan_to_curve_names(plan)`：plan.options["curve_names"] 优先；否则 geoviz 头
  （header_only）读曲线名；源缺失/异常→空集。
- C++：不移植（geoviz/lasio 依赖）。 LAS 的 preflight 分支已由 stub-oracle 覆盖。

### `tabular_adapter.py`
- `CANONICAL_COLUMN_ALIASES`：well_name/depth/x/y/value 五组别名（casefold 命中）。
- `sniff_delimiter(sample)`：前 32 非空行 × (, \t ; |) csv.reader 列数方差评分
  `(mean-1)/(1+variance)` 最高者；全部 <2 列回 ","。
- `TabularMappingPreset`（delimiter/encoding/has_header/header_map/decimal/units）
  to_dict/from_dict；**不含绝对路径**（测试断言 repr 无 tmp 路径）。
- `CsvLikeAdapter`：`_decode_sample` utf-8-sig→gb18030→replace 三段；
  inspect 报 delimiter/encoding/columns/header_map/has_header/row_count/decimal；
  warnings：非 UTF-8 编码 / 无数据行 / 重复表头 / 首行不像表头 / 列数不一致
  （min~max）/ 逗号小数（≥50% 且多于点）/ 主体非数值 / 缺井名 / 坐标列不完整。
  `_looks_like_header`：首行全文本且次行非全文本。`_is_numeric`（首位小数替换后 float）。
  `_count_data_rows`：上限 2,000,000 行，扣表头。
  plan_import 附 mapping_preset（metadata+options 双写）；import_data 判定
  needs_transform（delimiter≠"," 或 encoding∉utf-8(-sig) 或 normalize 选项）→
  归一化到 work 目录 `.normalized.csv`，`_verify_normalized_csv`
  （utf8_parsable/consistent_columns/no_bom）失败 RuntimeError；注册 format="csv"
  metadata 加 normalized_from；finally 删 staged。
  plan_export 限 .csv/.tsv；export 按嗅探源分隔符读、按目标扩展写；
  verify_output：parsable/consistent_columns/row_count_within_1（源按相反分隔符
  快速计数）。
- `CsvAdapter`（csv，","）、`TsvAdapter`（tsv/txt，"\t"）。
- `ExcelAdapter`（xlsx/xls；openpyxl 只读 data_only；sheets[{name,max_row,
  max_column,columns,header_map}]；重复列名/多表 warning；import 整簿保留）。
- C++：不移植（openpyxl/编码域）。delimiter 嗅探是纯算法——后续切片候选，
  本切片不动（surgical scope）。

### `geojson_adapter.py: GeoJSONAdapter`（geojson；extensions=("geojson","json")）
- `_MAX_INSPECT_BYTES=512MiB`；`_GEOMETRY_TYPES` 七种；`_iter_bounds_update`
  嵌套坐标累积 [minx,miny,maxx,maxy]（前两元数值才收，非有限跳过）。
- inspect：非 UTF-8/JSON 失败→ok=False + error（「文件不是有效 UTF-8 编码」/
  「JSON 解析失败（文件可能截断）: {exc}」）；FeatureCollection/单 Feature
  （+warning「单个 Feature（非 FeatureCollection）」）/其他→error
  「不是 GeoJSON（type={type!r}）」；无效成员/缺 geometry/混合几何/缺 CRS
  四类 warning；metadata{feature_count,geometry_types(sorted),property_keys
  (sorted 截 64),has_crs_member}；bounds→dataset_bounds。
- `_extract_crs`：crs.properties.name（str）或 crs 字符串。
- export 归一 FeatureCollection（+crs member）；verify reparse_ok/
  featurecollection_type/feature_count/bounds_preserved（rel 1e-6 abs 1e-9）。
- C++：不移植（本切片；JSON 结构扫描后续切片候选）。

### `vector_adapter.py: VectorAdapter`（vector_gdal；shp/gpkg/kml/gml/geojson/tab/mif）
- capability 依 `gdal_available()`；不可用全 False + notes（ADR 0060）。
- shp sidecar 硬校验（.shx/.dbf 缺→ok=False「Shapefile sidecar 不完整」+警告；
  .prj 缺→warning）；GDAL OpenEx 只读矢量；逐层 name/feature_count/extent/crs
  （AutoIdentifyEPSG 回填）/fields（>10 字节截断警告）/geometry_types（4096 上限
  探测）/invalid 几何计数；首层 crs/extent 上浮 dataset_bounds。
- plan_import：shp+managed+ok → action=transform_import、transform=
  shapefile_sidecar_bundle、warning；import_data 打包 zip（ZIP_STORED，
  basename 归档）注册 format="shp_bundle" metadata.bundled_from；staged 删除。
- verify_output：无导出路径→unverified。
- C++：不移植（GDAL 依赖）。

### `raster_adapter.py: RasterAdapter`（raster；tif/tiff/img/grd）
- rasterio 硬依赖；`_INSPECT_MAX_SIDE=1024` decimated、`_MAX_INSPECT_PIXELS=5.12e8`。
- inspect：CRS（无→warning）、bounds、nodata、units(band_i)、metadata{driver,
  width,height,count,dtypes,nodata,geotransform,scales,offsets,colorinterp,
  overviews,crs_wkt}；超限→跳过统计；decimated 统计 finite_ratio/nodata_ratio
  （round 6）；finite_ratio≤0→warning。
- export：标准化 GTiff（窗口 IO，1MiB… 实为 1024 块窗），dtype 转换 clip
  （iinfo 范围，nan→0），nodata 越界按目标 dtype 解析（越界丢弃优于坏文件）；
  逐 band 写 SCALE/OFFSET tags。
- verify_output：reopen_ok/grid_shape/crs_preserved（EPSG 或 WKT）/bounds_preserved
  （round 6 相等）/nodata_preserved（isclose 1e-9；dtype 变换时按目标解析）/
  dtype_converted/pixel_probe（中心 64 窗，同款转换后逐像素相等，nan→-1e30）。
- `_resolve_nodata` / `_probe_window_equals` / `_convert_like` 如上。
- C++：不移植（rasterio/GDAL 依赖）。

### `segy_adapter.py: SegyAdapter`（segy；sgy/segy）
- `MANAGED_COPY_MAX_BYTES=2GiB`（超→link_external+建议 zarr-v3 转码）；
  `_GEOMETRY_PROBE_MAX_TRACES=200k`；`_FINGERPRINT_MAX_BYTES=1GiB`。
- inspect：<3600B→error「文件小于 SEG-Y 最小头长度（3600 字节），可能截断」；
  segyio 缺→error；头信息 trace/sample/interval/format/il-xl first + 有界
  几何探针（≤8 全查，否则 step≤64 个点）+ inline/crossline varies + 轴首末 +
  text 前 320 字符；units["twt"]="us"（segyio 轴存 µs 口径）；首道全 0/
  inline 不变/大体积三类 warning。
- `_probe_indices`：0..trace_count 步进 max(1,tc/min(budget,64)) 取前 64。
- fingerprint：超预算只 size+mtime+hash=None+note。
- import_data：link_external→catalog.link_external（format=后缀）；否则 import_raw。
- plan_export / verify_output：明确不可用（「本仓库无 SEG-Y 写出器…」/ UNVERIFIED）。
- C++：不移植（segyio 依赖；seismic_io 已有独立 C++ SEG-Y 读取器，勿混淆）。

### `model_adapter.py`
- `MeshFacts(gridpoints,zones,problems)`；`_check_ids`（max≠count→编号不连续）；
  `_finite`（==自己 且 |v|≠inf）。
- `parse_flac3d`：行语法 G id x y z / Z B8 id n1..n8（B8 必须 8 引用）/ `*` 注释；
  未定义节点引用（sorted 样本 3 个）+ 编号不连续。
- `parse_abaqus`：*NODE/*ELEMENT/*END 段；node 4 列、element 9 列（C3D8）。
- `_StructuredModelAdapter`：capability（read False、write-only，notes 提 writer 名）；
  inspect：0 记录→error「未识别到网格记录…」；problems 前 16 进 errors+计数 warning；
  plan_import→unsupported+warning「模型网格为导出专用格式：无导入路径」；
  plan_export：后缀限制 + nx,ny,nz 必须 + 1≤min 且乘积≤8e6 + 估算
  (nx+1)(ny+1)(nz+1)*64 + nx*ny*nz*64；export 经 viz.geomodel.exporters writer
  （atomic_output，writer False→RuntimeError）；verify_output：reparsable/
  gridpoint_count（「预期 36，实际 36」detail 逐字）/zone_count/problems→FAILED。
- `Flac3dAdapter`（f3grid）、`AbaqusAdapter`（inp）。
- C++：不移植本切片（writer 依赖 viz.geomodel；结构扫描是纯算法，后续候选）。

### `unavailable.py`
- `UnavailableAdapter` 基类：capability 全 False+notes=reason；inspect ok=False
  errors=[reason]（size 尽力）；plan_import→action=unsupported+warning；
  plan_export→FormatNotSupportedError；verify→UNVERIFIED。
- `DlisAdapter`（dlis/lis；reason 提 C++ 适配器未绑 Python+无 dlisio）、
  `VtkModelAdapter`（vtk/vtu/vtp）、`MeshExchangeAdapter`（obj/stl）。
- 「capability-unavailable，绝不伪实现」是 v5 决策 D2 的诚实性要求。
- C++：AdapterSpec 表达全 False 能力行即可（决策面等价）。

---

## paleo_workbench/interchange/executor.py（241 行）

- `ImportExecutor`：action=unsupported→PreflightFailedError「计划标记为不可导入: {src}」；
  未知适配器 ValueError；cancel 检查点先行；import_data 异常→register_run(failed) 再抛；
  成功 register_run(completed)；`_record_run` provenance 失败不掩盖导入结果；
  close() 清自建 work_dir。
- `ExportExecutor`：execute(verify=True)：export→UNVERIFIED(verify=False)/
  verify_output（异常→UNVERIFIED「校验器异常: …」）；`_record_export` 经
  `catalog.lifecycle.register_export_output` 唯一咽喉点（ok 时）；失败 run
  status="failed"；provenance 异常→verification.warnings 追加。
- C++：不移植（catalog 接线属 M9）。

## paleo_workbench/interchange/batch.py（304 行）

- `ConversionJob/ BatchItemResult(status: converted|failed|skipped|cancelled)/
  BatchResult(summary counts+was_cancelled+total_duration_ms+estimated_disk_bytes)`。
- `BatchConversionService`：并发 ≤ min(max_workers, clamp_workers("background.io"))
  （无治理器→cap 4）；`estimate`（逐 job plan_export 累加，失败进 warnings）；
  `convert`：确定性排序 (source,target_name)→`_dedupe_targets`（casefold 冲突
  `-2/-3` 后缀）→ 单/多线程两路径；**仅共享 token 取消才中止**（job 内
  CancelledError=失败隔离）；progress 回调异常降级不丢结果；结果按 source 排序；
  FAILED 才算 failed；UNVERIFIED(verify=True) 记 detail 仍 converted。
- `_target_path`：sanitize_filename 或 `{stem}.{extensions[0] or bin}`。
- C++：不移植（线程编排属后续切片）。

## paleo_workbench/interchange/delivery.py（363 行）

- `DeliveryProfile`（profile_id/display_name/description/external_policy/
  include_outputs_only/include_formats/include_provenance/container/verify_package/
  report_formats）to_dict/from_dict（include_formats None 语义保留）。
- 5 内置 profile（internal-archive/reviewer-package/paper-figure-package/
  gis-exchange/modeling-handoff）；`get_profile` 未知→KeyError（可用清单入文案）。
- `DeliveryReportBuilder.build`：kind=paleo-delivery-report + generated_at +
  application + project（name==path，都是文件名）+ profile + package.plan +
  assets（count/by_type/versions_by_stage/names_preview 截 200）+ crs
  （catalog metadata ∪ 工程 coordinate 三键 ∪ resources[].crs，sorted）+
  warnings（缺失/变化依赖 + 包校验失败）；package.verified/verify_state
  （VERIFIED/FAILED/UNVERIFIED）/checked_entries/total_size_bytes/issues。
- `render_report_markdown`：逐行模板；「- 包校验状态: **UNVERIFIED**」逐字断言
  存在 / VERIFIED 不出现（honesty 测试）。
- `DeliveryService.build`：先目录后报告（报告入包，zip 才带 QA）；verify_package
  可关；container=zip→zip_package_dir；reports 经 os_replace_atomic。
- C++：不移植（编排+报告层）。

## paleo_workbench/interchange/dependency_audit.py（263 行）

- `DependencyStatus` 五态 valid/missing/changed/unknown/relink_candidate；
  `RelinkCandidate(path,size,sha256,basis: "size+hash"|"size")`；
  `DependencyRecord` to_dict 键序 version_id,asset,managed,path,status,
  observed_size,observed_mtime,expected_size,expected_sha256,relink_candidates,detail。
- 审计规则：文件缺→MISSING；非 managed 且无 hash→UNKNOWN（link_external 只存在性）；
  size 变→CHANGED；无 hash→UNKNOWN；预算内（默认 4GiB，累计）哈希→VALID/CHANGED；
  超预算→UNKNOWN「超过哈希预算：未验证内容」。`ok`=全部 ∈ {VALID,UNKNOWN}。
- relink 阶梯：MISSING 才找；无 size 且无 hash→拒绝猜（空）；逐 root 排序
  rglob，size 相等才候选，≤预算且已知 hash→sha256+size+hash；候选截 20；
  hash 命中优先排序 `(sha≠expected, path)`；attach 后有候选→RELINK_CANDIDATE。
- `apply_relink`：hash 冲突拒绝；size-only 须显式 confirm_unverified；
  经 catalog.link_external 注册**新**外部版本（metadata.relinked_from/relink_basis）。
- C++：不移植（catalog 依赖）。

## paleo_workbench/interchange/__init__.py（71 行）

- 对外词汇表 + 设计契约指针（decisions.md 的五段式）；
  catalog 是唯一生命周期权威；adapter 包装既有 parser 不重解析；
  不能真服务的格式 declared capability-unavailable，绝不伪装。
- C++ 侧 `pwb::interchange` 命名空间沿用同一词汇（UnsafePathError、
  manifest、preflight issue code 集全部照搬，不造新词）。

---

## 对照文件

### `paleo_workbench/resources/exporters.py`（259 行）
- `atomic_output(output_path)`：同目录 mkstemp（`.{name}.` 前缀 + 原后缀）→
  成功 `Path.replace`、失败删临时并上抛 —— 全链原子写基元。
- `las_to_csv/las_to_xlsx/las_to_json_summary/table_to_json/table_to_xlsx/
  image_to_png/text_to_txt/geojson_normalize/seismic_to_summary_json`：
  全部包 ExportError（「{链} 失败: {exc}」）；json 系 ensure_ascii=False。
- `_CONVERTERS` 注册表 + `get_available_formats`（label 首现去重）+
  `extension_for_label`（io_registry.CONVERT_LABEL_EXT）。
- 与 interchange 关系：adapters 的 export_data 全部经 atomic_output；
  manifest.write_manifest 亦复用。C++：原子写语义在 manifest 内核以 temp+rename
  等价实现（不移植 mkstemp 细节）。

### `paleo_workbench/resources/export_service.py`（530 行）
- 视图导出能力面（well_log/cross_well/paleo_map/unified_map/native_factor_map/
  generic 六类 surface；PNG/SVG/PDF；空画布拒绝矢量导出防白图 #381 类）。
- `export_asset_to_path`：converter 失败→失败结果（不注册）；成功经
  `record_export` 咽喉点登记 ExportArtifact + catalog OUTPUT（relativize 路径）。
- `export_project_inventory`：资源+导出物 JSON 清单（同咽喉点）。
- 与 interchange 关系：浅层旧导出面；interchange 是深层统一层，二者共享
  atomic_output 与 provenance 咽喉点语义（不双轨登记）。C++：不涉及。

### `paleo_workbench/catalog/checksum.py`（59 行）
- `sha256_file`（1MiB 块 + 可选 cancel，取消**绝不**给部分摘要）、
  `sha256_file_or_none`、`sha256_text`（行尾归一 LF）。
- C++：`pwb::domain::Sha256::of_file` 已是等价实现（mapping_kernel/data 线在用）；
  本切片 manifest 内核不哈希（哈希由 builder 写入 manifest 字符串），无新依赖。

---

## docs/development/interchange-delivery-v5/（4 文件，约束抄录）

- **baseline.md**：I0 能力矩阵（LAS/CSV/SEG-Y/…/Project package 全 N→本分支补齐）；
  interchange 必须建在 catalog/service、storage、checksum、port、
  project.artifacts.record_export、providers、resources 既有层之上，不复制实现。
- **decisions.md**（对本切片硬约束）：
  - D7：路径安全统一入口 —— NFC 归一、拒绝对路径/`..`/symlink 逃逸/Windows
    保留名/casefold 碰撞/超长；**fail-closed：拒绝而非跳过**。
  - D11：嗅探三级置信；high+扩展名冲突→硬错误；medium/low→仅 warning。
  - D12：包完整性口径 —— manifest 自身受校验：NFC/casefold 重复拒绝；
    total_size_bytes 与逐条合计一致；schema_version 严格 JSON 整数；
    zip 条目不得是目录；目录包解包前 symlink 全树拒绝。
  - D5：manifest schema_version=2，kind="paleo-package"。
  - D4：包=目录树为主，zip 仅传输容器；解包 fail-closed。
- **target-state.md**：I17 验收清单即本切片的 Python 侧事实清单（traversal/
  绝对路径/symlink/NFC/casefold/保留名/超长 全部 fail-closed）。
- **verification.md**：三轮 review 的历史缺陷清单（尾点空格绕过、目录条目、
  total_size 谎报、串行批量取消语义等）——每条都已凝为现行代码分支，
  C++ 移植必须原样保留这些分支，不得「简化掉」。

## tests/（13 文件全文阅读）

- `test_path_safety.py`（167 行）：17 拒绝案例（含 `con.txt`/`ctrl\x01char.txt`）、
  `a/./b.txt` 归一接受、NFD `cafe\u0301.txt` 拒绝、300/400 组件超长、Unicode 接受、
  保留助手、zip 六案例（traversal 不落盘、绝对、casefold 碰撞、保留名、
  symlink external_attr、干净包 2 文件）、within-root 三案例（symlink 不可用 skip）、
  sanitize 五断言。→ **oracle 主案例来源**。
- `test_import_preflight.py`（157 行）：LAS happy path（adapter/recommendation/
  estimated/sniff 证据/inspection.metadata.well_name）、unknown 不可猜、
  missing-file code、LAS 伪 .tif 走 extension-mismatch **warning** 且 ok
  （sniff high + adapter=las 命中后走 4.3 分支）、fail-closed 零资产、
  plan 可序列化含 managed_copy、executor 登记受管版本、超大 segy link_external、
  两个取消案例。→ preflight 决策表的分支命名来源。
- `test_interchange_contract.py`（137 行）：registry 重复/空 id、默认 13 适配器
  集合 + 能力诚实性（dlis import False、vtk read False、segy export False）、
  内容嗅探不认扩展名、unknown 空判定、ImportPlan 往返、UNVERIFIED 不混淆。
- `test_interchange_las.py`（98 行）：LAS 诊断断言集（units/well_name/row_count/
  depth_direction、重复助记、非单调、malformed、非 UTF-8、截断仍报 format、
  missing 失败、CSV/JSON 往返 verify、拒 .las writer）。
- `test_interchange_tabular.py`（146 行）：分隔符嗅探三例、列/映射、TSV 制表、
  重复表头、缺井名、GBK、preset 无路径、归一化导入、TSV 导出 verify、Excel 双表。
- `test_interchange_geodata.py`（227 行）：GeoJSON 计数/CRS/bounds/混合几何/
  截断失败/往返 verify/计数篡改 FAILED/拒 .shp 目标/入库；raster 四例
  （importorskip rasterio）；GDAL vector 五例（sidecar/prj/bundle/gpkg）。
- `test_interchange_segy_model.py`（178 行）：segy 头事实/截断/指纹/诚实导出/
  小体受管/大体外链；模型写读 verify（detail「预期 36，实际 36」逐字）/
  缺维度/悬空引用/编号不连续/异己文件/导入 unsupported/unavailable 三件套。
- `test_dependency_audit_and_batch.py`（256 行）：valid+missing 分类、CHANGED
  翻转、候选需内容匹配（不同名同内容必须识别、同名著不同尺寸绝不候选）、
  basename-only 永不候选、apply_relink 新版本+size-only 需确认；batch 五例
  （隔离/命名后缀/取消/估算/1000 文件 FD 断言）。
- `test_delivery_profiles.py`（115 行）：≥5 profile、序列化往返、无机构名、
  internal-archive=KEEP、reviewer=outputs_only、未知 KeyError、
  VERIFIED 包复核 ok、markdown 含 VERIFIED 与 EPSG:4326、UNVERIFIED 逐字诚实。
- `test_project_package.py`（219 行）：build+manifest（相对、无 `..`、文件在）、
  provenance run_count、checksum-mismatch、missing+unknown、schema 999、
  新根 reopen、zip 容器往返、三外部策略、非工程 ValueError、重复 build FileExists。
- `test_interchange_crash_consistency.py`（279 行）：ENOSPC 半途无版本、
  transform 中途 staging 清理、导出半写无残骸、取消保旧输出、包构建中途崩溃
  无半包且可重建、全故障后 reopen 一致、batch 邻项不腐蚀。
- `test_interchange_ui_models.py`（101 行）：Qt model 层（错误优先、状态中文标签
  打包/外部引用/缺失、真实 build 的 plan 行数）——C++ 无涉（UI 层 M10）。
- `interchange_fixtures.py`（260 行）：全部程序化小 fixture 生成器（LAS/CSV/
  GeoJSON/GeoTIFF/shp/segy/f3grid），无提交二进制 —— oracle 生成器沿用此风格。

## 测试缺口汇总（→ oracle 补齐）

1. path_safety 全部错误**消息文本**（Python 测试只查异常类型）。
2. manifest `dumps()` 字节级与 `from_dict` 类型错误文案。
3. preflight 决策树全分支的 report dict（含中文消息、estimated 口径、
   sniff 三字段序列化形状）。
4. NFC/casefold 的 Unicode 16.0.0 表驱动案例（中文、组合字符、德语 ß、希腊 σ）。
5. ensure_within_root 的决策语义（inside/symlink/escape）机器无关冻结。

---

## 审核修正附记（三轮审核后回写）

以下事实在实现期被审核纠正，供后续切片直接引用：

1. **NFC 组合阻断规则**（UAX #15）：被组合消费的字符**不得**更新 last_cc——
   阻断判定看的是「输出中残留的最后一个字符」的 CCC。首版把 last_cc=cc 放在
   循环末尾，导致 `U+1F31 U+0300` 类序列组合失败（fail-open，C++ 接受
   Python 拒绝的 non-NFC 路径）。starter+starter 表组合（泰米尔 U+0BC6+U+0BBE、
   孟加拉 U+09C7+U+09D7）与 Hangul L+V/LV+T 同样只在**相邻 starter**（last_cc==0
   且 cc==0）时尝试。fuzz_nfc 299 例钉死。
2. **Python str.strip() 空白集是全 Unicode**：含 U+0085、U+00A0、U+1680、
   U+2000-200A、U+2028/9、U+202F、U+205F、U+3000 与 C0 的 U+001C-001F。
   ASCII 子集实现是 fail-open。
3. **Python repr 的可打印性转义**：Cc（<0x20、DEL）、C1 区间 0x80-0xA0 →
   `\xHH`；Zs/Zl/Zp 分隔符 → `\uXXXX`/`\UXXXXXXXX`；其余（含 Cf/Co/Cn，
   oracle 池不含）按原样直通为有界声明。
4. **manifest from_dict 的强转语义**：Python `str()/int()` 接受数字/布尔/
   数字字符串（bool→1/0、float 截断、"5"→5），kind=None → "None"；
   int() 失败消息 `invalid literal for int() with base 10: 'abc'`、
   int(None) 抛 TypeError。C++ py_str/py_llong 逐字复刻并冻结。
5. **weakly_canonical 陷阱**：libstdc++ 对 symlink 目标不存在时静默回退到
   词法路径（ensure_within_root 会误判 inside）。oracle 的 dirlink 场景
   由两侧运行时各自构造真实拓扑重放，可暴露此类差异；root="/" 是一个
   额外前缀特例（C++ 已单列处理，Python parents 语义天然含之）。
6. **pre-flight estimated 口径陷阱**：import-unavailable 分支即使 inspection
   ok 也照报 `estimated = size_bytes`（777/55/4096 冻结在案）——
   移植时不得「顺手修正」。
