# 18 — Findings: FactorGridResult 持久化信封(JSON 契约)

BASE = `origin/main` @ `35987e13`。每个 §5 列出文件按文件名索引;每个公开符号
5–20 行:输入、输出、NaN/空/并列、与已有 C++ 核的关系、测试缺口。

---

## paleo_workbench/workflow/factor_grid_result.py(全文 673 行,已读)

模块目的:单一因子插值结果的**唯一**类型化契约(`FactorGridResult`),给原生渲染器/
图层模型消费。只依赖 numpy + stdlib,不拉 PySide6——这就是它可以被 C++ 忠实移植的
原因。四条设计规则(移植时必须保持):
1. 数据与样式分离(descriptor 里没有任何颜色/透明度/等值线样式);
2. 规范 nodata = NaN(引擎的 `None` 与适配器的 `NaN` 双编码都归一到 NaN);
3. CRS 显式,绝不猜测(`crs=None` = "源 XY,无声明 CRS");
4. 不发明数据(`variance_grid` 只有 Kriging 才有)。

### `NODATA`(模块常量)
- `float("nan")`,grid_z/variance_grid 中的规范 nodata 标记。C++ 对应
  `std::numeric_limits<float>::quiet_NaN()`(注意 Python 里是 float64 NaN,但存进
  float32 数组后就是 float32 NaN;C++ 核数组本来就是 `std::vector<float>`)。
- 与 C++ 的关系:`libs/mapping_kernel` interpolator 核已经用 NaN = nodata 同一约定,
  `grid_statistics` 跳过非 finite。语义完全对齐,无需转换层。

### `GridStatistics`(frozen dataclass,slots)
- 字段:`min, max, mean, std: float; valid_count, total_count: int`。
- 语义:对 grid 的 **finite 格元**做 float64 汇总。全 nodata 时 min/max/mean/std =
  NaN、valid_count=0、total_count=size。`std` 是 numpy `ndarray.std()` 即 **ddof=0**
  (总体标准差)。
- **已在 C++ 落地**:`pwb::mapping::grid_statistics(std::vector<float>)`
  (libs/mapping_kernel/src/interpolator.cpp:878,由 `mapping_kernel.grid_stats`
  对 8 个冻结案例对账全绿)。本任务 **复用,不重写**(红线:不改已绿数值核)。
- 测试缺口:C++ `GridStatistics` 结构体没有 JSON 序列化;`to_dict` 的 None 化
  (non-finite → JSON null)在 C++ 侧尚无对应物 → 本任务要补。

### `GridStatistics.from_grid(grid_z) -> GridStatistics`
- 输入:任意形状 ndarray;`total = int(grid_z.size)`,`finite = np.isfinite(...)`。
- valid==0 → NaN min/max/mean/std。valid>0 → `values.astype(float64)` 的
  min/max/mean/std(ddof=0)。
- 空数组:total=0、valid=0 → 全 NaN、计数 0(C++ grid_statistics 已冻结该行为)。
- 并列/重复值:无特殊分支,数值语义。
- C++:复用 `grid_statistics`。测试缺口:无(oracle 已 8 案例)。

### `GridStatistics.to_dict() -> dict[str, Any]`
- 输出键序(严格):`min, max, mean, std, valid_count, total_count`。
- `json_number(value)`:finite → 原值,**non-finite → None**(strict JSON 没有 NaN
  字面量;内存对象里保留 NaN,持久化描述符里是 null)。valid_count/total_count 是
  **int**(JSON 整数;`json_semantic_diff` 里 int vs float 是类型差异,C++ 必须写
  整数不能写 3.0)。
- C++:新增 `grid_statistics_to_json(const GridStatistics&) -> Json`(ordered_json
  按同序插入)。测试缺口:全 nodata 案例的 `to_dict` 四个 null 尚无 C++ 对账
  (grid_stats oracle 的 `_stats` 已带 `to_dict` 字段但 C++ 测试没消费它!)→ 本任务
  补上。

### `_to_float32_grid(raw, *, height, width) -> np.ndarray`(模块私有,行为是契约)
- 多分支输入归一:① sealed 只读 float32 C-contiguous 且形状吻合 → 原样返回;
  ② 可写 float32 同形 → 拷贝 + 非finite→NaN;③ object ndarray → 逐元素
  None/非finite→NaN,非法转换也→NaN(不抛);④ 其他(nested list 含 None,
  float64 数组等)→ `np.asarray(dtype=float32)` 失败则逐元素列表推导,
  `float(v)` 非 finite → NaN。
- 形状不符时:尝试 `reshape(height,width)`(容忍平坦 list),失败抛
  `ValueError("grid_z shape {arr.shape} does not match expected ({height}, {width})")`
  ——**报错文案是契约**(f-string 的 shape 用 tuple repr,如 `(2, 2)`)。
- 关键语义:inf/-inf、NaN、None 全部归一为 NaN;**有限值经 float32 舍入**
  (float64 输入 0.1 → float32 0.1 → 读回 widen 后 0.10000000149011612)。
- C++:codec 的输入已是类型化数组(float vector),不需要 ①③④ 的运行时多态;
  但「值 → float32 舍入 + 非 finite → NaN」必须在 C++ 侧逐格实现
  (`static_cast<float>` 的舍入与 numpy same-RT RINT 一致,IEEE 754 默认舍入)。

### `_coerce_xy(values, *, name) -> np.ndarray`(私有,行为是契约)
- 输出:contiguous float64 1-D。空 → `ValueError("{name} must not be empty")`;
  任何非 finite(NaN/inf)→ `ValueError("{name} must contain only finite coordinates")`;
  非 1-D → `ValueError("{name} must be a 1-D coordinate vector, got shape {shape}")`。
- **报错文案是契约**(测试 `test_all_nodata_descriptor_is_strict_json_and_axes_must_be_finite`
  用 `pytest.raises(ValueError, match="finite coordinates")` 钉住)。
- C++:从 Json 数组读入时做同文案校验。axis 里的 int(如 `[0, 1]`)在 Python 里
  `np.asarray(..., dtype=float64)` 转 0.0/1.0 —— C++ 读 Json 数字(int 或 float)都
  接受并转 double。

### `encode_legacy_grid_lists(grid_z) -> list[list[float | None]]`
- 逐行逐格:`None if not math.isfinite(float(v)) else float(v)`。
- 输入 `np.asarray(grid_z)` —— float32 数组每格 widen 成 Python float(double)。
- NaN/±inf → None;有限值 → double(如 float32 0.1 → 0.10000000149011612)。
- **注意**:1-D 输入会得到 list[float|None](外层不套),但本契约所有生产者都是
  2-D;C++ 只实现 2-D(row-major vector<float> + h*w)。
- C++:新增 `encode_legacy_grid_lists(grid_z, h, w) -> Json`(二维数组)。

### `encode_legacy_axis_list(axis) -> list[float]`
- `float64` 化后逐元素 `float(v)` → JSON 数字数组(有序)。
- C++:`encode_legacy_axis_list(const std::vector<double>&) -> Json`。

### `_json_safe(value)`(私有,行为是契约)
- 递归:`np.generic → .item()`;`float` 非 finite → None;dict → **键 str() 化**
  (C++ Json 键本来就是 string);list/tuple → list 递归;其他原样。
- C++:`json_safe(Json)` —— number_float 非 finite → null,递归 array/object。
  Json 里 int 不会非 finite;bool/string 原样。

### `FactorGridResult`(dataclass,slots;非 frozen)
字段(声明序 = 构造序):grid_z, grid_x, grid_y, factor_name, algorithm_id,
algorithm_parameters(dict,默认 {}), crs(None 可), unit, generator_version,
source_refs(list,默认 []), run_ref, created_at,variance_grid(None 可),
boundary(list[tuple[float,float]] 或 None), contours(dict 或 None),
statistics(init=False,`__post_init__ → _finalise` 计算)。
- C++ 信封结构体镜像这些字段;algorithm_parameters 用 `pwb::domain::Json`(对象),
  contours 用 `Json`(对象:level 字符串 → 三层嵌套数组)或 optional。

### 属性(只读推导)
- `width/height/shape`:grid_z 形状。
- `extent`: `(min(xs), min(ys), max(xs), max(ys))` —— 轴是 finite 校验过的,
  无空轴分支。to_descriptor 里 `list(self.extent)` → 4 个 float 的数组。
- `crs_is_known`: `crs is not None`(**空字符串也算 known**——诚实保留)。
- `dx/dy`: `(max-min)/max(1, n-1)`,n≤1 → 0.0。to_descriptor 不用 dx/dy,本切片
  不需要(不做多余 API)。
- `input_points/input_version_ids/run_id` 是别名 property,纯内存层,不属于
  JSON 契约 → 不移植(决策 18-decisions)。

### `__post_init__/_finalise`(构造即验证+归一,报错文案是契约)
顺序:① grid_z.ndim != 2 → `ValueError("grid_z must be 2-D, got shape {shape}")`;
② h,w = grid_z.shape;grid_x.shape != (w,) →
`ValueError("grid_x length {shape} must match grid_z width {w}")`(shape 是 tuple
repr 如 `(3,)`);grid_y 同理(height);③ grid_z→float32 归一;grid_x/grid_y→
_coerce_xy 校验;④ variance_grid 非 None → 同 ③ 归一;⑤ boundary 非 None →
逐点 float 化,任一非 finite → `ValueError("boundary must contain only finite
coordinates")`;⑥ `statistics = GridStatistics.from_grid(grid_z)`。
- from_legacy 路径里 grid_z 已先经 `_to_float32_grid`(带 width/height),所以
  ②的 grid_x/grid_y 形状错在 _coerce_xy(空/NaN)或 _to_float32_grid(shape mismatch
  reshape 失败)就会先抛。**分支到报错的映射必须逐一对账**(见 oracle 错误案例)。

### `copied()` — 深拷贝工具,内存层,无 JSON 输出 → 不移植(决策)。

### `from_engine_dict(data, *, factor_name, crs, unit, algorithm_id, ...)`
- 引擎 dict(`interpolate_factor_grid` 输出,None 编码)→ 结果。
- `algorithm_id` 缺省 = `str(data.get("backend", ""))`;params 固定先放
  `r_squared/grid_label(=data["grid"])/n_points`,再视 `grid_var` 非 None 加
  variance_grid + variance_min/max,再 passthrough power/azimuth_deg/semi_major/
  semi_minor(非 None 才放)。
- **tests/test_factor_grid_result.py 的 legacy round-trip 测试用 from_engine_dict
  读 to_legacy_dict 输出**——C++ 反向验收需要等价读入;from_legacy_task_parameters
  与 from_engine_dict 对 legacy dict 形状是同构的(见决策:统一到 from_legacy)。

### `from_constrained_idw_dict(...)` — 适配器 dict(NaN 编码、boundary、contours、
V6 §12 passthrough)。属于 constrained-IDW 适配切片,不是本切片的
from_legacy/encode_legacy;不移植(决策记录)。NaN→nodata 的行为由 _to_float32_grid
语义覆盖(oracle 案例里含 NaN 编码的 grid_z 走 from_legacy 同路径)。

### `from_legacy_task_parameters(parameters, *, factor_name, crs, unit, metadata)`
**本切片核心读路径**(老工程 `FactorMapTask.parameters` 内联 grid_x/grid_y/grid_z)。
逐行:
1. `descriptor = dict(metadata or {})`。
2. `backend = str(parameters.get("interp_backend") or parameters.get("backend") or "")`
   —— Python `or` 短路:falsy(空串/None)才往后;两个键可同时存在,interp_backend
   优先。**注意 str() 包裹**:backend 非 str(如 int)会被 str() 化;oracle 避免构造
   此类病态输入,但 C++ 行为要定:数字键 → 字符串化(与 Python 一致,低成本)。
3. `algorithm_id = str(descriptor.get("algorithm_id") or backend or "unknown")`
   —— descriptor 优先,然后 backend,最后字面量 "unknown"。
4. `grid_x = _coerce_xy(parameters["grid_x"], name="grid_x")` —— **KeyError 当键
   缺失**(报错文案 `'grid_x'`);grid_y/grid_z 同。
5. `grid_z = _to_float32_grid(..., height=grid_y.size, width=grid_x.size)`。
6. `params = dict(descriptor.get("algorithm_parameters") or {})` 然后固定 update
   (键序:update 里已有的键保持原位,新键按 update 字面量顺序追加):
   - `r_squared: params.get("r_squared")` —— **键必出现**,值可能是 None;
   - `grid_label: parameters.get("grid", params.get("grid_label"))` —— parameters
     有 "grid" 键就用它(**值可为 None**,.get 两参形式键存在即取值);否则 params
     的 grid_label;否则 None(键必出现);
   - `n_points: len(parameters.get("sample_points") or []) or params.get("n_points")`
     —— sample_points 非空 → int 个数;否则 params 的 n_points(可能 None);
     **注意 `0 or x` → x**,sample_points 为空列表时落到 params;
   - `power: parameters.get("power", params.get("power"))` —— 同 grid_label 模式;
     parameters["power"]=None 时 → None(键在,值为 None);键必出现;
   - `n_break_lines: parameters.get("n_break_lines", params.get("n_break_lines", 0))`
     —— 键必出现,永不 None:两层默认后兜底 0。
7. `grid_var` 非 None → variance_grid 归一 + `variance_min/variance_max` 进 params
   (值可能 None)。
8. `azimuth_deg` 非 None → params["azimuth_deg"]=该值,params["semi_major"]/
   params["semi_minor"] = parameters.get(...)(可能 None)。
9. `grid_boundary` truthy(非空列表)→ boundary 逐点 float 化;空列表/None → None。
10. 构造:crs = 显式 crs(非 None)否则 descriptor["crs"];unit 同;generator_version/
    source_refs(空 list 兜底)/run_ref/created_at 来自 descriptor;→ `_finalise`。
- C++ 签名:`from_legacy_task_parameters(const Json& parameters,
  const std::string& factor_name, const std::optional<std::string>& crs,
  const std::optional<std::string>& unit, const Json& metadata /*或 nullptr*/)`,
  异常用 `std::invalid_argument`(ValueError 分支)/`std::out_of_range` 或自定义,
  **文案与 Python str(exc) 对齐**,由 oracle 冻结。

### `to_descriptor() -> dict`(本切片核心写路径 1)
键序(fixed):factor_name, algorithm_id, algorithm_parameters, crs, crs_is_known,
unit, width, height, extent, generator_version, source_refs, input_version_ids,
run_ref, run_id, created_at, has_variance_grid, has_boundary, statistics,
[contours 当且仅当 truthy]。最后 `_json_safe` 整体过一遍。
- **无任何 grid 数组**(大数据走 artifact);input_version_ids/run_id 是 source_refs/
  run_ref 的**重复别名键**(向后兼容,C++ 也要写两份)。
- extent = [xmin, ymin, xmax, ymax];statistics = stats.to_dict()(键序固定)。
- crs/unit/generator_version/run_ref/run_id/created_at 键**恒存在**,值可 null。
- contours:`if self.contours:` —— None 或空 dict 都不写键。

### `to_legacy_dict() -> dict`(核心写路径 2)
键序:grid_x, grid_y, grid_z(嵌套 list,None 编码), backend(=algorithm_id),
min, max, mean(stats 的,None 化), r_squared(params.get),
[grid_var, variance_min, variance_max 当 variance_grid 非 None],
[boundary 当非 None,[[x,y],...]]。**没有 std、没有 statistics、没有 crs**。
- 反向读回:`FactorGridResult.from_engine_dict(to_legacy_dict(...))` 无损
  (有限值精确相等;`test_legacy_round_trip_is_lossless_for_finite_values`)。
- 注意 grid_var 分支的 variance_min/max 从 **algorithm_parameters** 取(不是重算)。

---

## paleo_workbench/project/factor_grid_artifacts.py(全文 641 行,已读)

本文件是**工程生命周期桥**(live LRU 缓存 + artifact 外置),大部分与 JSON 信封
无关。逐公开符号:

### `GRID_ARRAY_PARAMETER_KEYS = frozenset({"grid_x","grid_y","grid_z","grid_var"})`
- 保存时从 task.parameters 剥离的大载荷键(READ OLD / WRITE NEW)。
- 对 C++ 的意义:证明**保存后的 task.parameters 不再含 grid 数组**,即 Python
  产品"写出的 factor grid JSON"= artifact 里的 descriptor(严格 JSON)。

### `_env_int/_env_bytes`、`_LIVE_FACTOR_GRIDS*`、`next/current_factor_prepare_generation`、
`reset_artifact_load_counter`、`factor_grid_payload_bytes`、`_freeze_array`、
`intern_grid_axes`、`_seal_result_arrays`、`_evict_until_fit`、
`store_live_factor_grid`、`clear_live_factor_grid`、`peek_live_factor_grid`、
`has_live_factor_grid`、`grid_result_fingerprint`、`clear_live_factor_grid_if_fingerprint`、
`clear_session_caches`、`live_factor_grid_cache_stats`、`_shell_from_live`
- 全部是**进程内缓存/LRU/指纹管理**,不产生 JSON/NPZ 字节,不进入本切片
  (C++ 侧 live cache 属于 UI/会话层,后续切片)。
- 与本切片唯一交集:`factor_grid_result_for_task` 的解析顺序(artifact → live →
  legacy inline)证明 from_legacy_task_parameters 是"读老工程"的最终兜底。

### `factor_grid_result_for_task(task, *, crs, copy)`
- artifact 路径存在且 identity 命中缓存 → shell;未命中 → `read_grid_artifact`
  物理加载;无 artifact → live;都无 → `from_legacy_task_parameters(dict(task.parameters or {}), factor_name=task.factor_type or task.name, crs=crs, metadata=dict(task.grid_metadata or {}))`。
- artifact 丢失 + 无 live + 无 inline → 重抛 FileNotFoundError(自愈语义见 H11/#918,
  全部是文件层,不属于 JSON 信封)。

### `persist_factor_grid_artifacts(project, project_path)`
- 写 artifact(`write_grid_artifact`)、剥 `GRID_ARRAY_PARAMETER_KEYS`、
  "complete 但无载荷"→ 降级 pending + `quality_metrics["payload_missing"]`。
  全是工程/目录层 → 本切片不做(无 catalog、无工程文件 I/O)。

**结论**:该文件不产生本切片要对账的 JSON 字节;`18-decisions.md` 记录"工程桥
不移植,只移植 from_legacy 读路径"。

---

## paleo_workbench/catalog/grid_artifact.py(全文 213 行,已读)

### `FACTOR_GRID_ARTIFACT_VERSION = 2`、`GRID_ARTIFACT_SUFFIX = ".factor_grid.npz"`
- 写 V2(未压缩 savez),读兼容 V1/V2。NPZ 容器(zip + .npy 成员)是**二进制
  契约**,本切片不做(§7 步骤只含 JSON;决策记录)。但 **`__descriptor__` 成员 =
  `json.dumps(result.to_descriptor() + artifact_version + boundary_ring,
  ensure_ascii=False, allow_nan=False)` 是 JSON 契约** —— C++ 的 to_descriptor
  必须与之语义等价,这是"Python 写、C++ 读"的真实载体。

### `artifact_file_identity(path) -> (resolved_path, mtime_ns, size)`
- 纯文件系统身份,与 JSON 无关 → 不移植。

### `write_grid_artifact(result, dest_dir, name) -> Path`
- descriptor = to_descriptor();+`artifact_version=2`;boundary 非 None →
  +`boundary_ring=[[float(x),float(y)],...]`(**在 _json_safe 之后追加**,ring 本身
  已是 float,strict)。
- `np.savez` 成员:grid_z(f32 C-contig)、grid_x(f64)、grid_y(f64)、
  `__descriptor__`(0-d str 数组)、可选 variance_grid(f32)。
- 原子写(mkstemp + os.replace + fsync)。**"boundary" 字段在 artifact 描述符里
  叫 `boundary_ring`**,而 to_legacy_dict 里叫 `boundary` —— 两个名字都是契约。
- 本切片:C++ 不写 NPZ;`boundary_ring`/`artifact_version` 的追加规则记入
  decisions,供后续 NPZ 切片使用;C++ 的 to_descriptor 本身**不含**这两个键
  (Python 也是在 write_grid_artifact 里才加的)。

### `_stats_from_descriptor(descriptor, grid_z) -> GridStatistics | None`
- 读回侧"信任写方统计":descriptor["statistics"] 是 dict 且 total_count ==
  grid_z.size 且 valid_count 可取 → 构造;min/max/mean/std 为 null → NaN。
- **这是"C++ 读 Python 写的 JSON 后 statistics 一致"验收的直接对应物**:
  C++ 读 descriptor 时同样可以信任 embedded stats;但本切片的 C++ 读路径是
  legacy dict(带 grid 数组),读入后**重算** stats 与 Python 冻结值对账,更严。

### `read_grid_artifact(path) -> FactorGridResult`
- `np.load(allow_pickle=False)`;逐数组拷贝;descriptor = json.loads;
  boundary_ring → boundary;构造 FactorGridResult(含 contours=
  descriptor.get("contours") or None);**artifact_version>=2 且
  _stats_from_descriptor 命中 → 用 trusted stats 覆盖**(跳过 O(grid) 扫描)。
- 本切片:C++ 不做 NPZ I/O;构造参数键集(factor_name/algorithm_id/.../contours)
  已在 findings 覆盖,后续 NPZ 切片直接引用本文件。

---

## tests/test_factor_grid_result.py(全文 269 行,已读)→ C++ oracle 案例表

| pytest 案例 | 断言要点 | → conv-18 oracle |
|---|---|---|
| test_engine_dict_normalises_none_to_nan | None 格 → NaN;mask;shape(2,2) | from_legacy 输入含 null 格 |
| test_constrained_dict_normalises_nan_passthrough | NaN 格 → NaN;algorithm_id=constrained_idw;boundary 长度;params n_direction_lines=2/n_break_lines=1 | NaN 编码格案例 |
| test_both_encodings_produce_identical_grid | 1x1 None 与 NaN 收敛同一 mask | 两个编码各一案例,断言 NaN 格 |
| test_statistics_skip_nodata | valid=3/total=4;min=1.0;max=4.0;mean≈7/3 | stats 冻结值 |
| test_statistics_all_nodata_grid | 全 NaN:valid=0,min NaN | to_dict 四 null |
| test_all_nodata_descriptor_is_strict_json_... | to_descriptor()["statistics"]["min"] is None;json.dumps(allow_nan=False) 通过;NaN 轴 → ValueError "finite coordinates" | strict dump 断言 + 错误案例 |
| test_kriging_variance_grid_preserved | variance 形状/params min/max/algorithm_id | grid_var+variance_min/max 案例 |
| test_extent_and_axes | width/height/extent==(0,10,1,11);轴 tolist | descriptor extent 冻结 |
| test_crs_is_explicit_and_never_guessed | crs None→known False;"EPSG:32650"→True | crs=null 与 crs=str 案例的 descriptor |
| test_shape_mismatch_grid_x_raises | grid_x 长度 3 vs 宽 2 → ValueError | 错误案例(经 _to_float32_grid reshape 失败路径) |
| test_shape_mismatch_grid_y_raises | grid_y 长度 1 vs 高 2 → ValueError | 错误案例 |
| test_descriptor_has_no_grid_arrays_... | 无 grid_z/grid_x/grid_y 键;width/height/extent/statistics;json round-trip | descriptor 结构断言 |
| test_legacy_round_trip_is_lossless_... | legacy["grid_z"][1][0] is None;from_engine_dict 读回有限值精确相等;valid_count 相等 | Python round-trip stats 冻结 → C++ 复演 |
| test_legacy_task_parameters_adapter | interp_backend→"idw";crs;n_points=2;power=2.0;None 格→NaN | from_legacy 主案例(与 pytest 输入同源) |
| test_grid_statistics_to_dict_round_trip | from_grid→to_dict;valid=4;min/max;json round-trip | stats to_dict |

**测试缺口(oracle 要补的)**:错误分支的具体报错文案(pytest 只 match 片段);
`interp_backend` 与 `backend` 双键优先级;`algorithm_id` 落 "unknown" 分支;
metadata descriptor 提供 crs/unit/algorithm_parameters/source_refs/run_ref/
created_at/generator_version 的完整透传;`grid` vs `grid_label` 两参 get 语义;
`sample_points` 空列表 vs 非空;`azimuth_deg` 分支(semi_major/minor 可 None);
`grid_boundary` 空/非空;variance 分支 params 键序;全 nodata to_legacy_dict 的
min/max/mean 三 null;contours 只在 truthy 时出现在 descriptor(经 read 路径,
from_legacy 恒无 contours → descriptor 无该键)。

---

## C++ 侧已有定义(§5 第 5 项)

### `pwb::mapping::GridStatistics` / `FactorGrid`(libs/mapping_kernel/include/pwb/mapping/interpolator.hpp:57/66)
- 已有 `GridStatistics` 字段名与 Python 一致(double×4 + int×2);`grid_statistics`
  实现与 `GridStatistics.from_grid` 逐语义对应(float64 累加、ddof=0、全 NaN),
  已被 `mapping_kernel.grid_stats` 8 案例冻结。**复用**。
- 已有 `FactorGrid` 是 **geological_pipeline 插值核的输出**(method/model/variogram
  等字段),**不是** workflow 的 FactorGridResult 信封(factor_name/algorithm_parameters/
  crs/unit/provenance/contours)。两者并存:信封是新结构体
  (`FactorGridEnvelope`→命名见 decisions),不碰 FactorGrid。

### `libs/domain` JSON 语义相等(json.hpp + src/support.cpp,已读)
- `Json = nlohmann::ordered_json`(键序保持)。`json_semantic_diff`:对象键序无关但
  **键集合必须完全一致**;数组有序;**int vs float 是类型差异**(1 != 1.0);
  null/缺键是不同状态。→ C++ 输出的每个数字的 int/float 身份必须与 Python 一致
  (valid_count 用 int、extent 用 double、grid 值 widen 成 double)。
- `dump_json_python_compatible`(indent=2、ensure_ascii=false)可用于调试输出;
  对账走 `json_semantic_diff`(语义级,§4 允许)。
- 注意:nlohmann 把 NaN float dump 成 null,但 `json_semantic_diff` 里
  number_float(NaN) vs null 是 type differs → C++ 输出前必须显式归一(不依赖
  dump 行为)。

### 测试/构建基建(已读)
- 测试模式:`mapping_kernel_tests/` 每核一个可执行 + fixture 宏 +
  `add_test`;新目标名 `mapping_kernel.grid_envelope`。
- oracle 生成器模式:`tools/oracle/generate_*_fixtures.py`,
  `REPO_ROOT = Path(__file__).resolve().parents[2]` → fixture 写
  `mapping_kernel_tests/fixtures/*_oracle.json`;生成器 import 真实 Python 模块
  (红线:不得手写期望值)。运行环境:conv11 venv
  (`/home/kevin/project/oracle-venvs/conv11/bin/python`,numpy 2.5.3);
  **必须从非主工作区 cwd 运行**(否则 sys.path 的 `''` 用主工作区遮蔽 worktree)。
- CMake:根 CMakeLists 尚无 CONV 块;按 §3 追加 `BEGIN CONV-18` 块
  (option `PWB_BUILD_CONV_18`);`libs/mapping_kernel/CMakeLists.txt` 与
  `mapping_kernel_tests/CMakeLists.txt` 追加同名块。
