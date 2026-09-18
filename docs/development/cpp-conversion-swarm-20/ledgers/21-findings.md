# CONV-21 Findings — prediction 契约核（逐公开符号）

任务：把 `paleo_workbench/prediction/` 中仍属纯数据契约的叶子移植到
`libs/prediction`（conv-13 已建的 Qt-free 库）。本文件按文件逐符号列出
公开面、语义要点与边界；决策见 21-decisions.md。

## 范围文件（§5）

| 文件 | 行 | 性质 |
|---|---|---|
| `paleo_workbench/prediction/postprocess.py` | 262 | 纯函数 + 一个文件读取边界 |
| `paleo_workbench/prediction/spatial_result.py` | 224 | 纯校验/检测 |
| `paleo_workbench/prediction/input_contract.py` | 366 | 纯 schema 归一化 + service 半 |
| `paleo_workbench/prediction/model_package.py` | 365 | 纯 manifest 契约 + catalog 注册半 |
| `paleo_workbench/prediction/providers.py` | 700 | 只取常量 PROVIDER_DEMO/LOCAL_ASSET |
| `paleo_workbench/catalog/model_gates.py` | ~60 | 只取 NON_PROMOTABLE 两个 frozenset |
| `paleo_workbench/resources/well_tops_parser.py` | 43 | 已由 conv-19 移植（libs/ingest） |
| `tests/test_prediction_postprocess.py` | 115 | 既有行为锚点（合并/边界/解析） |
| `tests/test_prediction_production.py` | 710 | 集成层（service），不作 oracle 源 |

## postprocess.py

- `postprocess_prediction_regions(regions, *, formation_boundaries=None)`
  -> `(records, summary)`。
  - 输入过滤：`isinstance(region, dict) and _bounds(region) is not None`；
    `_bounds` = top/bottom 经 `_finite_number` 且 `bottom - top > 1e-6`。
  - 按 `(_bounds(item) or (inf, inf))` 元组升序排序（稳定）。
  - 每条 region 经 `_split_bounds` 按 boundary depth 切分（切点条件
    `top + 1e-6 < depth < bottom - 1e-6`），分段 `top/bottom` 写回
    `round(v, 6)`（Python round-half-even 十进制语义）。
  - 有 boundaries 时每段写入 `stratigraphic_unit`（`_stratum_at` 中点定位；
    无匹配段用 "未标定层位"）；无 boundaries 则不写该键。
  - 合并：同 facies（strip 后相等且非空）+ 同 `_display_probability`
    + 同 layer_index + `_touches`（|left.bottom-right.top| <= 1e-6）→
    前条扩 bottom、`probability` 覆盖为 display 值、
    `merged_sample_count` 累加（缺省按 1）。
  - 输出 `region_id = f"inference_api_post_{i}"`（1 起）。
  - summary 固定键序：applied=True, confidence_display_precision="1%",
    raw_region_count, split_region_count, postprocessed_region_count,
    formation_boundary_count。
- `resolve_formation_boundaries(well_name, *, well_log=None, inputs=None)`
  -> `(boundaries, diagnostics)`。
  - `inputs` 值里 `asset_type == "well_stratification"` 的条目：path 非
    is_file -> `"井分层文件不可读取: {name or path.name}"`；可读 ->
    `parse_well_tops(path)`，异常 -> `"井分层解析失败 {name}: {Class}"`
    （tolerant parser 下实际不可达）；行内 `well_key(row.well_name) ==
    well_key(well_name)` 的进入候选，source="well_stratification"。
  - `well_log.intervals.formation`（可空链）：`top` 经 `_finite_number`
    非空进入候选，name 缺省 "未标定层位"，source="las_formation"。
  - 汇流经 `_normalize_boundaries`：非 dict/非有限 depth 丢弃；
    name 空 strip 后回退 "未标定层位"；按 `(round(depth,6), name)` 去重
    （setdefault 保首次），再按 `(depth, name)` 排序后按 depth 去重
    （setdefault 保 sort 序首个）。
- `_display_probability(v)`：非数 -> 0.0；clamp [0,1]；
  `int(f"{v:.0%}"[:-1]) / 100.0` —— Python %.0f 半偶十进制定点，
  等价 `nearbyint(v*100)`（同 double、同 half-even）。
- `_finite_number(v)`：float(v) 失败/非有限 -> None。JSON 侧映射：
  number->v；bool->1.0/0.0（float(True)）；string->float(text)
  （PEP515/inf/nan 语义）；其余->None。
- `_well_key(v)`：`Path(str(v)).stem.casefold()` +
  `re.sub(r"[^\w]", "", name, UNICODE)`。`\w` = L* ∪ N* ∪ '_'
  （CPython SRE_UNI_IS_WORD_CHAR = ISALNUM|'_'）。
- `_split_bounds` / `_stratum_at` / `_touches` / `_bounds`：全部
  1e-6 epsilon 比较，行为如上。

## spatial_result.py

- 常量：SPATIAL_VECTOR_POLYGONS/WELL_INTERVALS/CLASSIFIED_RASTER/NONE
  （定义在 model_package）；KNOWN_SPATIAL 另含 ""。
- `spatial_type_of(payload)`：依次扫 payload、result_summary、
  output_schema、summary.spatial 的 `spatial_output_type`（非 dict 跳过，
  `or` 空串回退、strip）；再查 summary.spatial|payload.spatial 的
  type/spatial_output_type；再以 features|polygons ->
  VECTOR_POLYGONS、intervals|well_intervals -> WELL_INTERVALS、
  grid is not None|classes is not None -> CLASSIFIED_RASTER 推断；
  否则 NONE。全程 Python `or` falsy 语义（空 dict/list/0/"" 皆 falsy）。
- `extract_polygon_features(payload)`：spatial =
  summary.spatial|payload.spatial|{}；features|polygons 非 list -> []；
  feat 非 dict / geometry 非 dict / type 非 Polygon|MultiPolygon /
  coordinates 空 -> 跳过；返回命中 feat 原文。
- `validate_spatial_result(payload, *, expected_type=None,
  require_scientific=False)` -> errors:list[str]。
  - stype 未知 -> `unknown spatial_output_type: {stype!r}`（repr 单引号）
    并提前返回。
  - require_scientific 且 summary.final_scientific_prediction 非真 ->
    "result is not marked final_scientific_prediction"。
  - ""/NONE -> 返回；VECTOR_POLYGONS：无 feature ->
    "VECTOR_POLYGONS result has no valid polygon features"；有则逐 feature
    `_has_finite_ring` -> "feature[i] has non-finite or empty coordinates"、
    `_looks_like_demo_square` -> "feature[i] matches demo fixed-square
    geometry (114/22.5)"；crs falsy -> "VECTOR_POLYGONS missing crs"。
  - WELL_INTERVALS：intervals|well_intervals 空且无带 top|bottom 键的
    predicted_regions -> "WELL_INTERVALS result has no intervals"。
  - CLASSIFIED_RASTER：grid None 且无 artifact_path ->
    "CLASSIFIED_RASTER missing grid or artifact_path"；无 crs ->
    "CLASSIFIED_RASTER missing crs"；无 artifact_path 且 geotransform
    非 6 元 list/tuple ->
    "CLASSIFIED_RASTER missing 6-element geotransform or artifact_path"。
- `bounded_result_summary(payload)`：浅拷 summary；spatial.grid
  非 None 时 grid_shape（numpy shape 或 list 的 [len, len0]）+
  grid_omitted=True；其余原样。
- `is_map_compilable(payload)`：payload 空 -> False；stype 非
  VECTOR_POLYGONS -> False；无 features -> False；任一 feature 命中
  demo square -> False。
- `_has_finite_ring(coords)`：coords 空 -> False；ring=coords[0]；
  `ring[0][0]` 为 list/tuple 时 ring 再降一层（MultiPolygon）；
  len(ring)<4 -> False；每点 float(pt[0])/float(pt[1]) 非有限 -> False；
  转换异常 -> False。
- `_looks_like_demo_square(coords)`：同降层取 ring；xs/ys 的最小值与
  极差经 `math.isclose(..., abs_tol=1e-6)`（rel_tol 缺省 1e-9 并存）
  命中 (114.0, 22.5, span 0.04) -> True；异常 -> False。

## input_contract.py（纯半）

- `parse_input_schema(schema)` -> 归一化 dict：
  required_asset_types <- required_asset_types|asset_types|[]；
  optional_asset_types <- optional_asset_types|[]；
  required_curves <- required_curves|curves|[]；三者的 str 值按单元素
  列表处理，逐元素 `str(t).strip()` 且滤空；
  四个 require_* = `bool(schema.get(k, False))`（Python truthiness，
  字符串 "false" 也是 True！）；min_wells = `int(schema.get("min_wells")
  or 0)`（或值 falsy -> 0；int() 可收 str/float/bool，TypeError/ValueError
  传播）；raw = 原 schema dict 原样。
- 不迁：`resolve_model_inputs`（service/inference_service/lifecycle）、
  `_enforce_required_curves` / `_resolved_well_curve_names` /
  `_curve_names_from_resource_path`（geoviz 文件检查）、
  `_asset_type_for_version`（service）、`_RECOGNIZED_SCHEMA_KEYS` 仅服务
  于不迁函数的未知键拒绝分支——仍导出常量以便对账。

## model_package.py（纯半）

- 常量 KNOWN_SPATIAL_TYPES = {VECTOR_POLYGONS, WELL_INTERVALS,
  CLASSIFIED_RASTER, NONE, ""}。
- `ModelPackageManifest`：17 字段 dataclass，to_dict 固定键序
  （input_schema/output_schema/provenance/metadata 浅拷）。
- `load_manifest_dict(source)`：dict -> `dict(source)`；路径 ->
  `is_file` 否则 `ModelPackageError("Manifest not found: {path}")`；
  `read_text(utf-8)`+`json.loads` 的 OSError/JSONDecodeError ->
  `ModelPackageError("Invalid manifest JSON: {exc}")`（UnicodeDecodeError
  不被捕获、原样传播）；非 dict 根 ->
  `ModelPackageError("Manifest root must be a JSON object")`。
- `_strict_bool(raw, key, default)`：bool 原值；"true"/"false"
  （strip+lower）；其余 -> `ModelPackageError("{key} must be a boolean,
  got {value!r}")`（repr）。
- `parse_model_package_manifest(source, *, base_dir=None)`：
  - model_id 必填（strip 空 -> "model_id is required"）；model_version
    <- model_version|version|"1"；model_name <- model_name|name|model_id；
    capability/provider 必填。顺序：id->name->capability->provider。
  - model_type <- model_type|"ml" 再 strip 空回退 "ml"；demo_only/
    scientific/deterministic 经 _strict_bool（scientific 缺省 not
    demo_only）。
  - spatial <- spatial_output_type|VECTOR_POLYGONS strip；不在
    KNOWN_SPATIAL_TYPES -> "Unknown spatial_output_type: {spatial!r}"。
  - artifact <- artifact|artifact_uri|"" strip；非空且 base_dir 非空时
    相对路径按 `(base_dir/art).resolve()` 展开（Python resolve(strict=False)
    ≈ fs::weakly_canonical）。
  - checksum 非 None -> strip 空 -> None。
  - input_schema/output_schema 非 dict -> "input_schema and
    output_schema must be objects"；metadata/provenance 同理。
  - output_schema 缺 spatial_output_type 且 spatial 非空 -> 注入。
- `validate_model_package(manifest, *, require_artifact=True,
  allow_non_scientific=False)` -> errors:list[str]，顺序：
  provider ∈ NON_PROMOTABLE_PROVIDERS（精确匹配 "demo"/"local_asset"）
  -> "provider {p!r} cannot be registered as a production package"；
  model_type ∈ {"demo","heuristic"} -> "model_type {t!r} cannot be a
  production package"；demo_only -> "demo_only packages cannot be
  registered as production"；scientific is False ->
  "scientific=false packages cannot be registered as production"；
  require_artifact：artifact 空 -> "artifact path is required for
  production packages"；文件不存在 -> "artifact file missing: {path}"；
  sha256 不一致 -> "checksum mismatch: manifest={m} file={digest}"；
  无 checksum -> 回填 manifest.checksum=digest（可观察的副作用）；
  input_schema 空且非 allow -> "input_schema is required for
  production packages"。
- 不迁：`register_model_package`（catalog service 注册/promote/冲突
  检查）、`_sha256_file` 本身由 Pwb::Domain `Sha256::of_file` 等价承担。

## 边界与语义注记

- JSON 空值协议沿用 swarm 惯例：NaN/Inf 不入 JSON（_finite_number 已滤）。
- `_display_probability` 的半偶舍入：f"{v:.0%}" 对 double v*100 的精确
  十进制 half-even == nearbyint(v*100)（FE_TONEAREST）。
- `round(v,6)`：Python 为精确十进制 half-even；C++ 等价 = snprintf
  "%.6f" + strtod 往返（结果 = 最接近该十进制的 double）。
- `math.isclose(a,b,abs_tol=1e-6)`：默认 rel_tol=1e-9 并存，
  abs(a-b) <= max(rel*max(|a|,|b|), abs_tol)。
- Python `or`/`not` falsy 语义贯穿 spatial_result 全文；str(x) 在
  bool/数字/None/容器上的文本形态需要 py_str/py_repr 支撑。
- `resolve_formation_boundaries` 的文件读取在 Python 用
  `read_text(errors="replace")` —— C++ 经 ingest::decode_utf8(strict=false)
  等价后喂 `ingest::parse_well_tops_text`；`is_file` ≈
  fs::is_regular_file。`parse_well_tops` 的异常分支（"解析失败 {cls}"）
  在 tolerant parser 下实际不可达，C++ 侧如实不实现该路径并在
  decisions 记档。
