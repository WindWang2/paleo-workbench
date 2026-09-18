# 08-findings — 因子插值任务宿主（fingerprint / evaluation / plan）

> 逐文件全文阅读后按公开符号整理。输入 / 输出 / NaN・空・并列 / 与已有 C++ 核的
> 关系 / 测试缺口。基线 `origin/main` @ `35987e13`。

## paleo_workbench/workflow/interpolation_fingerprint.py（667 行，全文已读）

### `FINGERPRINT_SCHEMA_VERSION = 1`
- 常量，进每个组件 payload 的 `"schema"` 键与 result 组合 payload。
- C++ 侧同名常量，必须冻结在 oracle（改 schema 版本会让所有历史指纹失效）。
- 与 mapping_kernel 无交集；属本库独立常量。

### `DEFAULT_GENERATOR_VERSION = "factor-interp-v1"`
- 与 `factor_interpolation.GENERATOR_VERSION` 同值双源（注释明示 keep in sync）。
- 进 algorithm payload 的 `generator_version` 键（`str()` 包裹）。
- oracle 冻结含非默认值（"v9-test"）的案例防手滑硬编码。

### `METHOD_TO_BACKEND`（dict）
- 11 个键：克里金 / 克里金(MVP·线性) → kriging；IDW/idw/mock → idw；样条 → cubic；
  方向趋势 → directional；约束IDW → CONSTRAINED_IDW_ENGINE_LABEL（= "constrained_idw"，
  来自 constrained_idw_adapter，本次已实读确认值）；kriging/directional/constrained_idw 原样。
- 未命中 → "idw"（resolve_backend 默认）。键是中文/混合字符串 → C++ 用 UTF-8 字面量。
- oracle 覆盖每个键 + 未命中分支。

### `class FactorDirtyState(str, Enum)`
- 7 值：CLEAN / DIRTY_VALUES / DIRTY_GEOMETRY / DIRTY_ALGORITHM / DIRTY_CONSTRAINTS /
  MISSING_OUTPUT / UNKNOWN。`.value` 即持久化字符串。
- C++：enum class + to_string(value)。classify 的所有 7 个分支都要有 oracle 案例
  （UNKNOWN 有两条到达路径：force、无存储指纹且有 complete 输出）。

### `@dataclass FactorFingerprints` + `to_dict()`
- 5 个哈希字段 + schema_version + backend（默认 "idw"）。
- `to_dict()` 键名带 `_fingerprint` 后缀：schema_version / geometry_fingerprint / … / backend。
- stamp_fingerprints_on_task 用它写 params；C++ 端 to_dict 供宿主持久化与 oracle 对比。

### `stable_sha256(payload) -> str`
- SHA-256 of `json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",",":"), default=str).encode("utf-8")`。
- **关键坑**：float 编码走 Python `repr`（最短往返）；-0.0 → "-0.0"（上层负责归一）；
  NaN/Infinity 合法输出 "NaN"/"Infinity"（q/b_i 未经 _finite_float！）；int 原样无小数点；
  键排序按码点（ASCII 键 = 字节序）；ensure_ascii=False → 非 ASCII 原样 UTF-8。
- C++ 需要自写 canonical 编码器（nlohmann dump 的 float 格式与 Python 不同、也不做
  sort_keys 的码点序保证）；`pwb::domain::Sha256` 可直接复用（字节一致已由 data 核验证）。
- oracle 同时冻结**编码后的字节串**与哈希，编码差异可在测试内定位。
- 测试缺口：现有 pytest 只测确定性/顺序敏感，没冻字节；oracle 补齐。

### `_finite_float(value) -> float | None`
- float() 转换失败（TypeError/ValueError）→ None；非有限 → None；
  `number + 0.0` 把 -0.0 归一为 0.0（sign-of-zero 不翻指纹）。
- C++ 输入是 Json：number → double；bool 会被 Python float(True)=1.0 接受——
  C++ 端如实镜像（bool → 1.0/0.0）；string 数字可转；object/array → None。
- 注意 Python float(str) 接受 "inf"/"nan" 字面量 → isfinite 过滤为 None。

### `extract_sample_records(sample_points) -> list[dict]`
- 顺序保留（算法依赖样本序处理并列/重复）。x/y 优先 `x`/`y`，否则 `lng`/`lat`；
  都没有 → 跳过；z 从 `value`/`z`/`v`（get 链：value 存在但为 None 时 **不会**回退
  到 z——`pt.get("value", ...)` 只在键缺失时回退，值为 None 则 _finite_float(None)=None
  → 整点跳过）。
- q/b_i 顺带（非 None 即 float，可 inf/nan！）；qc_flag → str。
- 非 dict 元素跳过；try 包裹防类型爆炸。
- C++ 端以 Json 数组进出，record 键序 x,y,z,q,b_i,qc_flag（插入序，与 Python dict 一致，
  canonical 编码时反正 sort_keys）。

### `resolve_backend / backend_uses_breaks / backend_uses_directions / backend_uses_power / backend_uses_anisotropy`
- 纯查表/集合判断：breaks = {idw, constrained_idw}；directions = {directional, constrained_idw}；
  power = {idw, constrained_idw}；anisotropy = {directional}（仅纯 directional！）。
- constrained_idw 用方向但**不用** anisotropy 三参——这决定 algorithm payload 形状。
- oracle 全组合覆盖。

### `_normalize_polylines(polylines)`
- 每点 [float(x), float(y)]；坏点跳过（IndexError/TypeError/ValueError → continue，即
  短折线点被静默丢）；点数 ≥2 才保留。顶点/折线顺序不动。
- C++：Json 数组 → vector<vector<array<double,2>>>。

### `_normalize_direction_params(params)`
- dict 才收；coordinates 同上规则且 ≥2 点；entry = {id: str(raw.id or ""), coordinates, + 可选
  semi_major/semi_minor/azimuth_deg（非 None 才进，float 失败静默不进）}。
- id 为 None/空 → ""。键插入序 id, coordinates, 然后 semi_major/semi_minor/azimuth_deg
  （canonical 编码会 sort，顺序无谓，但 to_dict 风格输出需一致）。

### `build_factor_fingerprints(...) -> FactorFingerprints`（核心叶子）
- 输入 13 个 kwargs；先 resolve_backend → extract_sample_records → xy/zz 拆列。
- breaks 仅当 backend_uses_breaks，dirs 仅当 backend_uses_directions，否则空表
  （即 directional 的断层不进 geometry payload！IDW 的方向线不进 constraints payload）。
- geometry payload：{schema, xy, grid_n: int(grid_n), breaks, target_horizon: (t or "").strip()}。
  **grid_n 是 int 强转**（50.0 → 50 → 编码 "50"）；horizon strip 后空串仍在 payload。
- values payload：{schema, z}；backend == "directional" 时追加 q/b_i/qc_flag 三列
  （`s.get("q")` 缺失为 None → 编码 null；H11：QC 权重变化必须翻指纹）。
- algorithm payload：{schema, method: str(method), backend, generator_version} +
  duplicate_policy（仅当非 None）+ power（仅 backend_uses_power）+ azimuth/semi_major/semi_minor
  （仅 anisotropy）。
- constraints payload：{schema, directions, constrained: backend == constrained_idw}（bool）。
- result = sha256({schema, geometry, values, algorithm, constraints, crs: crs or ""})。
- oracle 冻结：四个组件哈希 + result + backend，多方法 × 多参数 × q/b_i/qc_flag ×
  duplicate_policy × crs × -0.0 × 非法点过滤。

### `_fingerprint_memo_key(...)` / `fingerprints_for_task(...)` / `_fingerprints_for_task_uncached(...)`
- 请求内 memo（task id + method/grid_n/power/breaks/generator_version/horizon/
  (点数, sha1 点摘要) 元组）。DEF-D2-05：sha1 摘要 `f"{x}:{y}:{v};"` 逐点更新，
  防 in-place 改值假命中（tests/test_round2_review_fixes.py::test_interpolation_fingerprint_memo_key_detects_point_mutation）。
- uncached 路径耦合 normalize_factor_samples + constraint_layers_for_project +
  resolve_anisotropy_params（geoviz）+ project.coordinate——**project/task 胶水**。
- C++ 切片决策：memo key 的纯成分（sha1 点摘要）不移植——它只是性能缓存键，
  不是科学输出；`fingerprints_for_task` 的 project 解析留 Python/宿主层。
  C++ 提供 build_factor_fingerprints + normalize 后样本即可复现同指纹
  （V8 M3 契约：指纹覆盖 NORMALIZED 集合；C++ 已有 pwb::mapping::normalize_factor_samples）。

### `stored_fingerprints_from_task(task)`
- 从 params / grid_metadata / algorithm_parameters 三层找 5 个指纹键（字符串非空才算）；
  result 回退 input_snapshot_hash；组件不齐 → None（legacy 一次性哈希）。
- backend 回退 params.interp_backend → "idw"。
- C++：接受纯数据 `FactorTaskView`（params/meta JSON + 三个标量字段）。

### `task_has_numerical_output(task)`
- live cache（fga，进程内会话缓存）→ True；grid_artifact_path 存在文件 → True
  （OSError → False）；否则 params.grid_z 非 None。
- C++ 切片：live-cache 恒 false（无宿主会话），文件存在用 std::filesystem::exists，
  grid_z 判 null/缺失。oracle 冻结非文件分支；文件分支 C++ 单测本地自建临时文件。

### `classify_factor_recompute(task, current, force=False)`（决策叶子）
- 硬规则顺序：force → UNKNOWN；无输出 → MISSING_OUTPUT（三段子判断：非 complete
  且无 grid_z → MISSING_OUTPUT；有 artifact 路径但无文件 → MISSING_OUTPUT；
  非 complete → MISSING_OUTPUT；complete 且无路径无输出 → 落到存储比对）。
- 无存储指纹：旧 monolithic 哈希 == current.result 且有输出 → CLEAN（极罕见）；
  有输出且 complete → UNKNOWN；否则 MISSING_OUTPUT。
- 有存储：result 相等且有输出 → CLEAN；否则按 geometry → values → algorithm →
  constraints 顺序返回最具体 DIRTY；只剩 CRS/schema 漂移 → DIRTY_ALGORITHM。
- 偏好假 DIRTY 而非假 CLEAN（模块 docstring 明示）。
- oracle 冻结每条分支（含「result 不等但四组件全等」→ DIRTY_ALGORITHM）。

### `stamp_fingerprints_on_task(task, fps)`
- params 写 to_dict 全键 + input_snapshot_hash=result；grid_metadata 写 5 个指纹键。
- 宿主胶水；C++ 端由 to_dict + 宿主持久化承担，不单独移植。

### `plan_cache_get / put / clear / stats`（会话 LRU）
- OrderedDict + RLock，max 32，get 命中 move_to_end，put 超限 popitem(last=False)。
- stats = {entries, max_entries}。
- C++：`std::unordered_map + list` LRU + mutex，存 `std::shared_ptr<InterpolationPlan>`。
- 纯会话行为，无 Python 数值；C++ 单测覆盖命中/逐出/统计（无需 Python oracle——
  Python 侧也无该缓存的数值 oracle，行为由 pytest#848 缓存清理间接覆盖）。

## paleo_workbench/workflow/interpolation_evaluation.py（825 行，全文已读）

### `DEFAULT_CV_FOLDS = 4`
- 常量，k 默认值。

### `bilinear_sample_grid(grid_z, grid_x, grid_y, px, py) -> float | None`
- gx/gy 取首尾当轴（假设均匀）；fi=(px-x0)/(x1-x0)*(nx-1)（nx==1 → 0.0）；
  非有限 → None；越界（fi<0 或 >nx-1）→ None（#1275：网格外不算技术）；
  i/j clamp 到 [0, n-2]；双线性 z[j,i]…（行=y）；结果非有限 → None。
- C++：grid_z 行主 (ny×nx)，返回 std::optional<double>。
- oracle：中点、精确角点、NaN 窗、网格外、单点轴（nx=1）。

### `signed_r_squared(observed, predicted) -> float`
- 1 - ss_res/ss_tot；ss_tot < 1e-12 → **1.0**（#844 约定，常量场不clamp负值——
  注意是 ss_tot 小直接给 1.0，不比较预测）。
- C++ 端 ss_tot 的 mean 是 numpy mean（成对求和 vs 朴素循环可能有 ulp 差）——
  oracle 冻结具体数值，C++ 用朴素累积在冻结案例上对齐（案例覆盖到能暴露差异）。

### `EvaluationMetrics` + `from_arrays` + `to_dict`
- 字段 rmse/mae/bias/r_squared（可 None）+ n_samples/n_skipped。
- from_arrays：shape 不等 → ValueError "observed/predicted shape mismatch: {a} vs {b}"
  （numpy shape 文本如 `(3,)` vs `(4,)`）；valid = 双方 isfinite；全跳过 → 全 None + n_samples=0。
- to_dict：非有限值（不可能出现，防御性）→ None。
- oracle：精确值（sqrt(8/3)、4/3、-3.0）、跳过计数、空对、shape 报错文案。

### `spatial_fold_assignment(x, y, k) -> list[np.ndarray]`
- k<2 → ValueError "k must be >= 2, got {k}"；长度不等 → "x/y size mismatch"；空 → []。
- angle = arctan2(y-ȳ, x-x̄)；`np.argsort(angle, kind="stable")` 稳定升序（并列保原序）；
  rank % k 轮转分折。折内顺序 = 角度序（非原序）。
- C++：std::stable_sort + atan2（libm 与 numpy 在常规值上逐位一致，冻结案例含并列角）。

### `CrossValidationReport` + `to_dict`
- method/scheme("kfold_surface"|"loo_exact"|"unavailable")/k/metrics/folds/residuals/engine/detail。

### `leave_one_well_out_folds(points)`
- key = str(well_id or name or "").strip()；空 → `__anonymous_{index}`（**枚举序号**，
  不是组内序）；fold 顺序 = 首见组序（dict 插入序）。
- oracle：分组、匿名、name 回退。

### `cross_validate_surface(points, run_fold, k, method_label, engine, cancellation_token)`
- 可评分过滤：非有限 x/y/z 丢（计数）；**精确重复坐标去重**（首个保留，计数）；
  `len(scorable) < k+2` → None。
- 折循环：train = 非 test；held = 按 test_set 排序；len(train)<2 或空 held → fold 记录
  {fold, status: "skipped", n_skipped: len(held)}；run_fold 异常 → unavailable 报告
  （detail = f"fold {i} failed: {type}: {msg}"）。
- 每 held 点 bilinear 采样，None → fold_skipped++；否则进 obs/pred/residuals。
- 全局 metrics；`n_samples < attempted` → n_skipped = attempted - n_samples。
- detail = "scorable={n}" + 可选 "; non_finite_dropped={n}" + "; duplicates_merged={n}"。
- C++：run_fold 用 std::function，异常经 `FoldEngineError(type, msg)` 传 Python 风格
  类型名（冻结案例的 detail 才能逐字节对齐）。
- oracle：生成器内置确定性 numpy-IDW fold 闭包（与 workbench 测试同一数学），
  冻结 folds 记录/residuals/metrics/detail；太少的点 → None；重复合并 → detail 文案。

### `surface_residuals(points, gx, gy, gz)`
- in-sample 锚定保真（明示不是 CV 精度）。逐点采样，None 跳过；
  records 键 x/y/value/predicted/residual。
- oracle 冻结 records + metrics。

### `residual_features(residuals)`
- GeoJSON 点要素：id=f"residual_{i}"，coordinates=[x,y]，properties 三键。

### `_validate_recommendation_context(unit, crs) -> (warnings, gate)`
- unit None/空 → ("", "unit_unknown")；strip+lower 后不在 known_units（m,米,ft,feet,英尺,%,
  percent,ratio,dimensionless,v/v,g/cm3,api,us/cm,md,1）→ warning + unit_unknown；
  crs 非空 → pyproj 解析失败 → "crs_invalid"（pyproj 缺失也 → crs_invalid：fail-closed）。
- C++ 决策：CRS 校验通过注入 `CrsValidator`（std::function<bool(const std::string&)>）；
  测试内用映射核同款规则（EPSG:xxxx 接受、其他拒绝）实现，保证冻结案例一致；
  默认 validator = 仅接受空（fail-closed，宿主可注入 pyproj 等价物）。

### `adjudicate_recommendation(entries, gate, unknown_constraints, scheme_caveat)`
- gate 文案表（unit_unknown/crs_invalid）+ unknown_constraints 文案（!r 格式 =
  Python repr 列表：`['unicorn_barrier']`）。
- eligible = metrics 非 None 且无 ":unsupported:" 警告；best = min RMSE（None → inf）；
  条目 mutation：gate → 全 False+gate 文案；unsupported → 取消资格文案；
  best → recommended+RMSE 文案（可拼 caveat）；否则 higher RMSE 文案（含 {best!r}）。
- recommended_method：gate 非空 → None，否则首个 recommended 的 method。
- entries 直接以 JSON 数组进出（dict 键序保持 Python 侧输入序，C++ ordered_json 一致）。
- oracle：gate 关 / 未知约束 / best 选择 / 全不可评 / caveat 拼接。

### `recommend_interpolation_methods(...)`
- 依赖 constraint_capabilities（ConstraintKind/evaluate_request）——**不在 §5 清单**，
  且 V6/V8 的门禁+能力矩阵是宿主编排语义。C++ 切片：不移植（findings/decisions 记录）；
  其可移植纯叶子（validate/adjudicate）已单独移植。

### `kriging_leave_one_out / kriging_diagnostics / _points_to_arrays`
- 直接 import geoviz（apply_anisotropy_transform/leave_one_out_predictions/
  empirical_variogram/fit_variogram）——这就是「geoviz 引擎」本体，任务明令不跑。
- mapping_kernel 已有 numpy-grid-OLS Ordinary Kriging 核（不同估计器，M6 已冻结）。
- C++ 切片：不移植；np.unique 词法序去重 + mean z 的语义记入 findings，
  留给后续 kriging LOO 切片（届时可基于 mapping_kernel 核复刻 Dubrule 1983）。

## paleo_workbench/workflow/interpolation_plan.py（676 行，全文已读）

### `_orientation / _on_segment / _segments_intersect( tolerance=1e-12)`
- 传统 4-orientation 相交 + 端点/共线 bbox 容差分支。apply 路径私有，本切片不移植
  （属于引擎 apply，见 scope 决策）；strict 变体同。

### `xy_signature(x, y) -> str[:24]`
- sha256(uint64 LE size + x float64 LE bytes + y float64 LE bytes).hexdigest()[:24]。
- **顺序保留**；np.ascontiguousarray(float64) 保证字节布局。
- C++：静态断言小端（或按字节序处理）；digest[:24]。
- oracle：空数组、单点、含 -0.0、大坐标、乱序 vs 排序不同签名。

### `_ELEMENT_BUDGET = 4_194_304` / `_chunk_cells_for_budget`
- max(1, budget // max(1, n_src))。纯算术；随 apply 路径留 Python（不移植时冻结
  数值进 oracle 无消费者——**不移植也不冻结**，findings 记录）。

### `_fault_segments / _fault_blocked_mask / _plan_fault_mask`
- LOS 屏障掩码（#926 strict interior、#118 不整行切断）。值无关、几何相关，
  但消费者只有 apply 引擎路径。C++ 切片：不移植（apply 不在本切片）；
  掩码语义已在 tests/test_interpolation_plan_batch.py 钉死，后续 apply 切片照搬。

### `_grid_axes_from_samples(x, y, grid_n)`
- n = max(2, grid_n)；空样本 → linspace(0,1,n)²；否则 5% span padding（min 1e-6）
  后 linspace。**np.linspace 语义**：step=(stop-start)/(n-1)，y[i]=start+step*i，
  末点强制 = stop（endpoint）。C++ 需同公式（末点覆盖）才能逐位对齐。
- oracle 冻结轴值全精度（repr 往返），C++ 逐位比较。

### `PlanKey` + `digest()`
- 字段 method/xy_sig/grid_n/power/fault_sig/azimuth_deg/semi_major/semi_minor。
- digest = sha256(f"{method}|{xy_sig}|{grid_n}|{power:.12g}|{fault_sig}|{az:.12g}|"
  f"{major:.12g}|{minor:.12g}").hexdigest()[:32]。`%.12g` 与 C printf 一致；
  int 直接十进制。
- oracle：多组参数含 0.1/1e16/.12g 精度边界。

### `_fault_signature(polylines)`
- 空 → "none"；每点 f"{x:.9g}:{y:.9g}" 逗号连，折线 "|" 连，sha256[:16]。
- oracle：空、单折线、多折线、共点。

### `plan_key_from_arrays(...)` / `InterpolationPlan` + `__post_init__`
- build 时数组冻结为 C 序只读；geometry_id 空则 = f"{xy_sig}:{grid_n}"。
- C++：struct { PlanKey key; vector<double> source_x/y, grid_x/y;
  vector<vector<array<double,2>>> fault_polylines（可空）; string geometry_id; }。

### `build_idw_plan(sample_points, grid_n=50, power=2.0, fault_polylines=None)`
- geoviz extract_xy_values（x/y 或 lng/lat；value/z/v；非有限跳过）→ len(z)<2 →
  ValueError "插值至少需要 2 个有效采样点"（中文文案冻结）。
- breaks = [[(float,float)...]] 仅当 fault_polylines 非空。
- key.method 恒 "idw"（**不是**传入 method——build_idw_plan 只有 IDW 版）。
- C++：内置本地 `extract_xy_values`（geoviz 同名函数 20 行等价移植，decisions 记录）。

### `_idw_multi_chunked / apply_idw_plan / apply_idw_plan_multi`
- 值相关 IDW 引擎路径（#934 单因子快路径、#844 populated=totals>0、断层 NaN parity）。
- 本切片只做「plan 数据结构」，apply 留 Python（宿主路径经 geoviz/plan）。
  mapping_kernel interpolator 已有单因子 IDW（kNN/全邻域）核可服务后续接线。
- decisions 记录 + findings 引擎语义摘要（populated 规则、NaN 语义、快路径 parity）。

### `extract_values_aligned(sample_points, plan)`
- 重跑 extract_xy_values；shape 或 allclose（默认 rtol 1e-5 atol 1e-8）不符 →
  ValueError "sample geometry does not match interpolation plan"。
- C++：实现 allclose；错误文案冻结。

### `_contact_strictly_between / _segments_intersect_strict / _orientation_value`
- #926 strict 语义参考实现（geoviz #118 同款）。同 apply 路径，不移植。

## paleo_workbench/workflow/factor_interpolation.py（1488 行，全文已读）

### 常量：`GENERATOR_VERSION="factor-interp-v1"`、`DEFAULT_FACTOR_TYPES`、`DEFAULT_GRID_N=50`、`MAX_LOO_SAMPLES=64`
- 与 fingerprint 模块双源同值；C++ 常量放 factor_host 头文件。

### `METHOD_LABEL_TO_ENGINE` + `resolve_engine_method(method)`
- 11 键映射（克里金→kriging、样条/spline/cubic→样条、方向加权→directional…）。
- 未注册且不在已知引擎集合 → ValueError "unknown interpolation method {method!r}; supported: "
  + sorted(标签) 逗号连。**sorted 是码点序**（中文在 ASCII 后，UTF-8 字节序一致）。
- `!r` 对 str 是单引号 repr（Python str repr 的转义规则——冻结案例只用无转义字符）。
- oracle：每键 + unknown 报错文案 + "spline"→"样条"（tests/test_review_convergence.py 钉过）。

### `_snapshot_hash(payload)`
- json.dumps(sort_keys, ensure_ascii=False)（**无** compact separators、无 default=str）
  → 与 stable_sha256 不同编码。仅 legacy 回退用；随宿主胶水不移植。

### `interpolation_params_from_task(task) -> (method, grid_n, power)`
- method = params.method or task.method or "IDW"；grid_n = max(8, int(params.grid_n or 50))
  （TypeError/ValueError → 50）；power = float(params.power or 2.0)（异常 → 2.0）。
- Python 真值语义：0/""/None/空容器 → 回退默认。int(str) 只接受整数字面量
  （"24.7" → ValueError → 50；int(24.9)（JSON number）→ 24 截断）。
- C++ 签名：`interp_params_from_task(const Json& params, const std::string& task_method)`。
- oracle：#919 案例 + 真值回退 + 字符串数字 + 负数。

### `variogram_settings_from_params(params)`
- 5 个源键 → 3 个引擎键映射（range_m→variogram_range、nugget→variogram_nugget），
  非None 才进；返回 dict（插入序 = 映射序）。CV 与生产共此单源。
- oracle：全键/部分键/None 值/空 params。

### 其余（`apply_interpolation_to_task`、`batch_prepare_factor_maps`、`_attach_result_to_task`、`_task_plan_group_key`、`cross_validate_factor_task`、`evaluate_methods_for_task`、`attach_*`、`_requested_constraint_kinds`、`_engine_run_fold_for_task`、`_declared_unit_for_task`、`_legacy_params_from_grid_result`、`_none_encode_grid`、`_apply_interpolation_isolated`、`_normalized_points_for`、执行计数器）
- 全部耦合 FactorMapTask / ProjectDocument / live cache / catalog / geoviz 引擎——
  宿主编排层，本切片不移植（见 decisions D-3）。其中与指纹相关的语义要点：
  - 指纹消费 NORMALIZED 样本集 + normalize report.duplicates_present 时才把
    policy 写进 algorithm payload（V8 M3：无重复任务字节级 CLEAN）；
  - prepare 覆盖参数（method/grid_n/power）优先于任务存储参数；
  - plan cache key = f"{geometry}:{algorithm}"（power 变化必须换 plan，audit C1）。
  这些语义由 build_factor_fingerprints 的调用方（宿主）保证，C++ 叶子已可支撑。

## paleo_workbench/workflow/factor_prepare_scheduler.py（769 行，全文已读）

### `prepare_worker_count()`
- env PALEO_PREPARE_WORKERS clamp 1..4 再过 ResourceGovernor——纯运行时胶水。
### `FactorPrepareProgress / FactorPrepareTaskResult / FactorPrepareBatchResult / FactorPrepareSnapshot`
- 冻结 dataclass DTO（含 #834 grid 随行、#1168 cancelled≠failed、#1159 late defaults、
  C3 scheduled grid_n/power 语义）。纯数据形状 + 编排，无数值叶子。
### `build_prepare_snapshot / materialize_execution_project / classify_snapshot_tasks / run_factor_prepare_schedule / commit_prepare_batch_result / _task_failure`
- 快照深拷贝 / 线程池 / 提交守卫。**无数学**；classify 内部就是 fingerprints_for_task
  + classify_factor_recompute（两叶已在 fingerprint 模块覆盖）。
- C++ 切片：不移植（依赖 ProjectDocument/线程宿主，属 M10 前后的宿主层）。
- 测试语义摘要：全 clean 零执行、单 dirty 只重算该因子、stale generation/input 丢弃、
  cancel 计数独立、fingerprint 每任务一次（memo）、commit guard 用 scheduled 覆盖值。

## paleo_workbench/workflow/sample_normalization.py（231 行，全文已读；C++ 已有）

### `DUPLICATE_POLICIES / DEFAULT_DUPLICATE_POLICY / SampleNormalizationReport / _valid_record / normalize_factor_samples / duplicate_policy_from_params`
- M7 已落 `pwb::mapping::sample_normalization`（normalize_factor_samples /
  duplicate_policy_from_params，oracle generate_sample_norm_fixtures.py 14 案例）。
- 本次对接：fingerprints 的「normalized 集合」输入由它提供；`_valid_record` 与
  extract_sample_records 的有效性规则同源（模块 docstring 明示 both authorities agree）。
- 差异点（重要）：normalize 的数值 extras 要 isfinite 过滤，fingerprint 的
  extract_sample_records **不**过滤 q/b_i 的 inf/nan——两模块不是同一个函数，
  C++ 侧不得「统一」它们。
- 本切片只读对接，不改其实现。

## docs/development/geological-interpretation-v9/（因子产品章等，已读 02/06/08）

- 02：FactorProduct 身份 = task.id；算法注册表（ADR-5）canonical id / 别名表 /
  supported_constraints；staleness 锚点 = 约束 pins + 输入指纹 + 声明单位——
  即本切片 fingerprint 叶子的产品层消费方。C++ 的 to_dict 键名必须与 Python 一致，
  否则 descriptor 迁移会漂。
- 06：统一 verdict 词汇（CURRENT|STALE_CONTENT|…|UNKNOWN）；「UNKNOWN 是问题态，
  无证据绝不猜 CURRENT」——与 fingerprint classify 的「偏好假 DIRTY」同哲学。
- 08：factor grid LRU 64 项/256MiB——plan cache max 32 与之同族（会话缓存有界）。

## 审核轮修正记录（2026-09-18，两轮外部审核 + 修复）

第一轮对抗性正确性审核（82 组两侧对比实验）+ 第一轮 Karpathy 审核发现并已修复：

1. **P1 bilinear 退化网格越界读**：nx==1/ny==1 时 Python 的 int 索引 i=-1 靠
   numpy 负索引回绕到合法单元，C++ size_t 下溢造成越界读（Release 下被零系数
   掩盖、硬化构建下即 abort）。已改为带符号索引 + 与 Python 相同的环绕语义
   （a = fi - i 在环绕前计算），新增 single_cell / single_col_far_x /
   single_row_far_y 冻结案例。
2. **P2 grid_z "is not None" 误作真值**：task_has_numerical_output 里 []/0
   也算「有输出」（Python `params.get("grid_z") is not None`）；classify 的
   inline-grid 分支才用真值。已修正，新增 clean_grid_z_empty_list /
   clean_grid_z_zero / unknown_legacy_empty_grid_z 案例。
3. **P2 direction id 缺 `or ""` 回退**：id=0/false/[] 在 Python 里回退为
   ""，此前 C++ 产出 "0"/"False"——constraints 指纹互不相认。已修正，新增
   constrained_falsy_ids 案例。
4. **P2 折线/方向坐标被误归一化**：Python 仅对样本 x/y/z 做 -0.0 归一与非有
   限过滤；折线/方向坐标用裸 float()（-0.0/inf/nan 全保留）。此前 C++ 用
   finite_double 导致 geometry/constraints 哈希分歧。已改为 raw_float，新增
   idw_fault_negzero_inf 案例。
5. **P2 字符串 float 超集**：strtod 接受 "0x1p3"/"nan(1)" 而 Python 拒绝，
   会改变样本有效性。已实现严格 Python float 字面量校验（十六进制/下划线/
   全角数字/nan(payload) 全拒），新增 idw_hexfloat_string_dropped 案例。
6. **P2 method 数字/布尔崩溃**：params.method=5 时 Python str(5)="5"，C++
   曾直接 get<string> 抛异常。已改 python_str_scalar，新增 method_number /
   method_bool 案例。
7. **P2 Unicode 空白 strip**：str.strip() 剥全部 Unicode 空白（NBSP/U+3000
   等），此前只剥 ASCII。已实现 UTF-8 感知的 python_strip，新增
   idw_unicode_horizon（U+3000）/unit_nbsp 案例；Python float()/int() 的
   strip 同源。
8. **P2（决策-代码不符）cross_validate 通用异常**：Python `except Exception`
   把任意 fold 异常转 unavailable 报告；D-6 已写明 C++ 用 FoldEngineError 携
   带 Python 异常类型名、其余 std::exception 以 "error" 兜底——代码此前只有
   FoldEngineError 分支，已补齐。
9. P3 批次：NaN 角度 stable_sort 比较器违反严格弱序（numpy 把 NaN 排最后，
   已复刻）；require_number 接受数字字符串/布尔；stored backend 非 string 时
   str() 化；repr 引号切换（'…' → "…"）；死代码清理（nx/ny 未用变量、
   kGeneratorVersion 双源常量、(void) 残留、expected_to_dict 未消费字段）；
   python 真值/strip 逻辑收敛到内部 src/semantics.hpp。

### 已如实记录的剩余分歧（宿主边界保证不触发，故意不复刻 Python 的崩溃）

- Python 折线点为 dict/3 元组时未捕获崩溃（KeyError/ValueError）；C++ 静默
  跳过或按 Polyline 边界收前两分量。宿主样本集保证 [x, y] 数组。
- qc_flag/容器字段的 str() 文本：Python 用容器 repr，C++ 用 JSON dump——
  仅显示用途。
- metrics 大数组的求和顺序（numpy 成对求和 vs 朴素累积）：1e-9 相对容差内，
  非逐位。
- python_float/int 的下划线分隔与全角数字：Python 接受，C++ 拒绝（回落默认
  或丢弃）。fixture 无此形态；真实宿主文档由 pydantic 模型保证为数字。

### 修正后的设施事实

- task_has_numerical_output 的文件分支用 `std::filesystem::is_regular_file`
  （等价 Python Path.is_file()）。
- PlanCache 是 vector + 线性扫（32 项上限，头文件注明「最简正确」），不是
  unordered_map+list。
- fixture 现为 179 案例（新增 17 个审核分支案例），3370 断言全绿。

## 测试缺口总表（oracle 需补——CONV-08 已全部补齐）

1. stable_sha256 的**编码字节**从未被冻结（pytest 只测行为确定性）。
2. build_factor_fingerprints 无任何跨实现数值冻结（现有断言全是「相等/不等」关系）。
3. classify_factor_recompute 的 7 态没有完整分支矩阵（存量只测 UNKNOWN-legacy 与集成路径）。
4. bilinear/signed_r2/metrics/folds 只有少量手算值；无固定数据集的完整指标冻结。
5. xy_signature/PlanKey.digest/_fault_signature 完全没有直接单测（只经集成路径间接覆盖）。
6. build_idw_plan 的轴计算、geometry_id、错误文案无直接单测。
7. resolve_engine_method 只有 2 个断言（unknown 报错 + spline）；METHOD_LABEL_TO_ENGINE
   全表无对照。

（以上 1–7 已由 generate_factor_host_fixtures.py 冻结解决：编码字节经哈希逐字节
钉死、fingerprint 25+ 案例含组件哈希、classify 17 态矩阵、evaluation 全指标
冻结、plan 签名/键/轴/文案冻结、interop 全表对照。）
