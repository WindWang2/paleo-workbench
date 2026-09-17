# 11 — findings：测井曲线解释纯核（curve_operations / well_science）

基线 `origin/main @ 35987e13`。分支 `feat/cpp-conv-11-curve-ops`，worktree
`/home/kevin/project/worktrees/cpp-conv-11-curve-ops`。

每个公开符号按「输入 / 输出 / NaN·空·并列 / 与已有 C++ 核的关系 / 测试缺口」记录。
语义验证全部用真实 Python（oracle venv：numpy 2.5.3 / scipy 1.18.1）跑过，见
`tools/oracle/generate_curve_ops_fixtures.py` 的冻结结果。

## paleo_workbench/workflow/curve_operations.py（482 行，13 个公开符号）

### moving_average(values, window=5)
- 输入：float 数组 + 窗口样本数（不是米，调用方换算）。输出：等长 float 数组。
- 语义：居中滑动平均 = `np.convolve(filled, ones(w), 'same') / np.convolve(finite, ones(w), 'same')`。
  NaN 位恒 NaN（绝不邻域填充）；窗口内只平均有限样本。
- 边界：n==0 → 空拷贝；`w = min(max(1,int(window)), n)`（窗口宽于曲线 → 整条曲线平均，
  且 'same' 输出长度不变）；w==1 → 原样拷贝；全 NaN → 原样拷贝。
- 'same' 偏移已实测：偶数窗 trailing 偏（w=2 → 窗 [i-1, i]；通式 start=i-⌈(w-1)/2⌉,
  end=i+⌊(w-1)/2⌋，窗口越界按 0 贡献——sums/counts 同时 convolve，越界不影响分母）。
- 测试缺口：无 inf 输入案例（inf 会进 sums 且 isfinite=False → out[i]=NaN，位置恒 NaN）。
  oracle 补了一条 inf 案例。

### median_filter_curve(values, window=5)
- 语义：`w = max(1, int(window) | 1)`（强制奇数，负窗 → 1）；NaN 位先填**全局有限中位数**，
  scipy `median_filter(size=w, mode='reflect')` 后恢复 NaN。
- 已实测：scipy 'reflect' == `np.pad(mode='symmetric')`（边缘样点镜像重复），
  **不是** np.pad 'reflect'。C++ 用对称延拓 + 窗口拷贝全排序取中位数。
- NaN/空：size==0 或全 NaN → 原样拷贝；NaN 位置输出恒 NaN。
- 测试缺口：Python 测试只测 w=3 一例 + NaN 位保持；oracle 需要偶数窗、宽窗、
  全 NaN、边缘尖峰等案例。

### normalize_curve(values, method="zscore")
- zscore：有限样本 mean/std(ddof=0)；std ≤ 1e-12（常量曲线）→ 全 0（不造方差）。
  minmax：span ≤ 1e-12 → 全 0.5。NaN 位 NaN；全 NaN → 全 NaN 数组。
- 失败分支：未知 method → `ValueError: unknown normalization method 'magic' (zscore|minmax)`。
- 测试缺口：单有限样本（std=0 → 0）；常量曲线 minmax（→0.5）。

### clip_outliers(values, lower=None, upper=None, percentile=None)
- percentile p ∈ (0,50)：`np.percentile(finite, p)` / `(finite, 100-p)`（linear 插值，实测
  0..99 的 p=5 → 4.95）。lower/upper 可单独给（None 侧不裁）。NaN 原样。
- 失败分支：p 出界 → `percentile must be in (0, 50), got {p}`；完全没给裁剪参数 →
  `clip_outliers needs lower/upper bounds or a percentile`。全 NaN → 原样拷贝（在
  参数校验**之前**返回——空曲线不报参数错，这是忠实移植点）。
- 并列：p=0/p=50 拒绝（开区间）。

### normalize_unit_name(unit)
- 别名表 `_UNIT_ALIASES`：m/ft 系（含 LAS "F"）、g/cc 系（g/cm³、G/CC 大小写不敏感）、
  kg/m3、us/m、us/ft、mm/in、mv/v、ohmm 四写法、%/pct/v/v、api。`str.strip().lower()`
  后查表；未命中/None → None。纯表函数。

### conversion_factor(from, to)
- 身份对（同 canonical）→ 1.0；白名单对 → 精确因子（FT_TO_M=0.3048）；
- 失败分支：未知单位 → `unrecognized unit ('blorts' -> 'm'); supported: [...]`
  （sorted set 别名表）；未知对 → `no whitelisted conversion 'api' -> 'm';
  supported pairs: [...]`（sorted keys）。报错文案必须逐字冻结。

### convert_values(values, from, to)
- factor 乘在**有限**样本上（先 conversion_factor 再乘；NaN 位保持 NaN）。
  注意：因子校验先于数据 —— 坏单位即使数组为空也抛错。

### resample_axis(depth, step)
- `count = floor((stop-start)/step + 1e-9) + 1`，轴 = start + arange(count)*step；
  尾部不足一步的区间**丢弃不进位**。
- 失败分支：size<2 → 原样拷贝（不校验 step！）；step 非有限或 ≤0 →
  `resample step must be positive, got {step}`；下降轴 →
  `resample needs a non-descending depth axis (got 2000.0 → 1980.0); reverse the axis explicitly first`。

### interp_nan_aware(new_x, x, y)【已废弃语义，仅显示连续性】
- 丢弃 NaN 样本 → argsort 升序 → `np.unique(return_index=True)` 去重（**保首个**，
  实测 stable mergesort）→ `np.interp`（端点钳制）→ 超出有限样本 hull 的位 → NaN。
- **内部 NaN 空洞被线性桥接**（V6 §4 认定的 fabrication）；科学路径必须用
  interp_gap_preserving。两者都要移植：显示桥接语义被 UI 消费。
- NaN/空：无有限样本 → 全 NaN。

### interp_gap_preserving(new_x, x, y)【V6 §4 科学语义】
- 有限样本按索引连续段（idx diff >1 断开）分段；每段内 `np.interp`（段内去重保首个），
  段 hull 之外 NaN —— 内部空洞**绝不桥接**。
- 失败分支：x 的有限部分下降 → `interp_gap_preserving needs a non-descending depth
  axis; reverse the axis explicitly first`（注意：只检查 finite x，且在"无有限样本"时
  不检查直接返回全 NaN）。
- 并列：重复深度保首个；new_x 精确等于段端点 → 端点值（闭区间 [x[s], x[e]]）。

### MissingIntervalReport / missing_interval_report(depth, values)
- `total = v.size`（含 NaN）；`missing = count(~isfinite(v))`（**不含** d 非有限的贡献）；
  intervals 只在 `finite.any() and total > 2` 时，从首个有限索引到最后一个有限索引之间
  扫描，坏段记 `(d[run_start], d[i-1])`（首坏深度 → 末坏深度）。边缘缺失不是 gap。
- 派生：`missing_fraction = missing/total`（total==0 → 0.0）；`largest_gap = max(b-a)`
  （空 intervals → 0.0）。
- 测试缺口：depth 含 NaN 的案例（finite 掩码含 d）；total≤2 的边界。

### evaluate_curve_expression(expr, variables)【受限 AST 白名单，绝不 eval】
- 语法：数字、曲线名、一元 ±、二元 `+ - * / ** % //`、链式比较（> < >= <= == !=）、
  `and`/`or`（数组按位 &/|）、白名单函数 `abs min max log log10 log2 exp sqrt sin cos tan
  where clip`（仅位置参数）。NumPy 语义：
  - `%` = 除数取号（-1 % 3 = 2）；`//` = floor；`**` 负底分数幂 → NaN；
    除零 → ±inf/NaN（原生 IEEE）。
  - 布尔化：`!= 0.0`（NaN → True，实测）。
  - `min/max` = np.minimum/np.maximum（元素级两参，NaN 传播）。
  - `where(cond, a, b)`、`clip(a, lo, hi)`。
- 失败分支（文案逐字冻结）：空表达式 `empty expression`；无变量
  `expression needs at least one curve variable`；语法错误 `invalid expression: ...`；
  非数字常量 `constant 'x' not allowed (numbers only)`（bool 也拒）；未知名
  `unknown curve name 'DT'; available: ['GR']`（sorted）；未知函数
  `function 'open' not allowed; supported: [...]`；关键字参数 `keyword arguments are
  not allowed`；其它 AST 节点 `expression element {NodeType} is not allowed`；
  形状不齐 `expression did not produce a sample-aligned result`（0-d 标量例外 → 广播
  到首变量形状；dict 插入序决定"首"变量）。
- 同秩不同形状的算术由 numpy 抛 broadcast ValueError（内部文案，C++ 侧复刻格式，
  见 decisions）。
- 运算符优先级（Python）：or < and < 比较 < + - < * / // % < 一元 ± < **（右结合，
  一元在左底数外侧：`-2**2 = -4`；指数侧可带一元：`2**-1`）。
- 测试缺口：Python 测试无幂/模/整除/链式比较/scalar 广播案例；oracle 全补。

## paleo_workbench/workflow/well_science.py（181 行，6 个公开符号 + 3 常量）

### FT_TOKENS / M_TOKENS / UnknownDepthUnitError
- FT: {FT,F,FEET,FOOT}；M: {M,METER,METERS,MTR,MTRS,METRE,METRES}（upper 匹配）。
- 异常文案：`operation '{op}' depends on the depth unit, which is {detail};
  refusing instead of assuming meters`，detail = declared ? `declared as '{raw}' but
  unrecognized` : `not declared by the file`。异常携带 info + operation（C++ 侧用
  异常类型 + what() 文案承载）。

### DepthUnitInfo（unit: m|ft|None, declared: bool, raw: str；known = unit∈{m,ft}）
### classify_depth_unit(token)
- None/""→(None, declared=False)；token strip 后 upper 查两个 token 集；
  未命中 → (None, declared=True, raw 原样保留)。"FURLONGS" 是金案例。

### require_depth_unit(unit, operation)
- 接受原始 token 或已分类 info；known → 返回 "m"/"ft"；否则抛 UnknownDepthUnitError。
  所有单位依赖运算的统一闸门。

### depth_unit_of(data)
- 读文档的 `depth_unit` 属性；无属性/None → (None, declared=False)。这是 duck-type
  契约——C++ 侧没有动态属性，由调用方传入 optional<string>（见 decisions）。

### INFERRED_NULL_SENTINELS=(-999.25,-999.0,-9999.0,-99999.0) / DERIVED_NULL_SENTINEL=-999.25 / NULL_MATCH_ABS_TOL=1e-6
### NullPolicy(source, sentinel, inferred_sentinels)
- source ∈ declared|inferred|derived_injected|none；`declared` 属性 = source=="declared"。
- `matches(values)`：`np.isclose(rtol=0, atol=1e-6)` 对 active sentinel + 全部
  inferred sentinels 的布尔掩码（注意 NaN 与 sentinel 的 isclose 为 False）。
- `as_dict()`：source 恒在；sentinel/inferred_sentinels 缺省省略（provenance JSON 契约）。

### null_policy_from_declared(declared)
- None/""→none；可转 float → declared；TypeError/ValueError → none。**不猜**。

## paleo_workbench/workflow/curve_interpretation.py（397 行）

### depth_shift(depths, delta_m, axis_unit="m")【纯】
- require_depth_unit 闸门；ft 轴 → delta × 1/0.3048（米定义的位移换算成轴单位）；
  unknown → UnknownDepthUnitError。输出 = depths + delta_axis（NaN ride along）。

### despike(values, threshold_sigma=3.0, window=3)【纯】
- 滚动中位数基线（w 奇数化 `max(1,int(window)|1)`，NaN 用 nanmedian 填充后 medfilt
  reflect）→ residual；MAD 尺度 `1.4826*median(|r - median(r)|)`，下限
  `max(floor, 1e-9)`，floor = 有限样本 >1 时 `0.01*ptp(finite)` 否则 1.0；
  `|residual| > threshold*spread` 的位替换为基线值（含 NaN 位——NaN residual 是
  spike 也会被替换为基线！注意 NaN 输入位在 finite=False，residual=NaN-基线=NaN，
  |NaN|>t 恒 False → **NaN 位不被替换**，保持 NaN。实测确认）。
- 空数组/全 NaN → 原样返回。
- 测试缺口：Python 测试只测单尖峰；oracle 补 NaN 共存、平台噪声、MAD=0 下限路径。

### baseline_shift(values, delta)【纯】= values + delta。

### CURVE_OPERATIONS / OPERATION_SCOPE（数据表）
- 11 个 operation id → (kernel, required 参数名)；scope ∈ depth_axis|curve|file|derive。
  移植为纯数据（scope + required 参数表），kernel 函数指针不搬（C++ 签名异构，
  dispatch 留给后续接线层）。

### apply_curve_operation / CurveInterpretationResult / _ensure_writable_well_header
- catalog（DataCatalogService）+ lasio 读写 + provenance 落库 = 工程对象，**本切片不移植**。
  其数值行为已由核级 oracle 覆盖（resample 保 gap、depth_shift 单位语义、
  null policy 记录）。

## paleo_workbench/workflow/well_qc.py（124 行）
- `from geoviz import compute_sand_ratio, median_absolute_deviation, modified_z_scores`
  —— 公式本体在 geo-viz-engine `packages/geoviz_plots/geoviz_plots/analytics/well_qc.py`
  （已读，纯 numpy）：
  - `median_absolute_deviation`：有限样本 median(|x - median|)；空 → NaN。
  - `modified_z_scores`：0.6745*(x-med)/MAD；MAD<1e-15 → 等于中位数记 0、
    偏差 ≥1e-15 记 ±inf（copysign）；非有限位 NaN。
  - `compute_sand_ratio(hs, ht)`：None → (None,"ok")；非有限/ht≤0/hs<0/hs>ht →
    (None,"invalid_ratio")；否则 (hs/ht,"ok")。
- well_qc 自己的规则（apply_sand_ratio_qc / apply_mad_outlier_qc / run_well_table_qc /
  qc_summary）作用在 WellTable 行模型（project.models）上：invalid_ratio 不动 z；
  MAD 只打所选列（无跨维度 fallback，#1151）；outlier → b_i=min(b_i,0.1)；
  missing → b_i=0；qc_summary 对未知 flag 归 "ok"。
- **结论**：属井表 QC 流（不是 LAS 曲线解释流），且公式归属 geoviz（另一引擎契约），
  本切片只读 findings、不移植（decisions #4）。已有 C++ mapping_kernel extract 的
  sand_ratio 是系数族派生量（factor_layer_products），与此不同核、不冲突。

## paleo_workbench/viz/well_log_api.py（31 行）
- `minmax_downsample` / `fast_las_parse_data`：native_backend 门面，C++ 已存在
  （pybind 扩展 well_log_core + 纯 Python fallback 的 SymmetricParityContract，
  tests/test_well_log_core_hardening.py 双路径对账）。再往 libs/well_science 移植 =
  第三份实现。**不移植**；渲染降采样属 viz 域。

## paleo_workbench/viz/well_log_load.py（423 行）
- 工程对象为主：WellLogCache（线程安全 LRU，16/2 容量）、geoviz loader 接线、
  取消检查点、日志。纯规则仅：PREVIEW_MAX_SAMPLES=100_000、
  FULL_RESOLUTION_MAX_SAMPLES=1<<27、decimation stride=`max(1,ceil(original/max))`、
  WellLogDecimationInfo 记录、detect_depth_unit_info（LAS 头 → classify_depth_unit，
  XML → undeclared）。文件 IO 耦合 → 本切片不移植；单位分类已被
  classify_depth_unit 覆盖（同一函数）。
- 消费契约（供后续切片）：known 单位才包 WellLogDataWithDepthUnit 信封（m 也包，
  review R2-P0）；undeclared 裸载。correlation_overlay/well_tie_host/canvas cursor
  都用 require_depth_unit 失败关闭。

## paleo_workbench/viz/well_log_track_layout.py（172 行）
- CurveTrackLayout（可见性/分组，≤3 曲线/道，merge 拖入者命名在前、unmerge 拆单）、
  default_curve_track_layout（前 6 可见，GR 保证可见——挤掉末位）、
  reconcile（schema 不匹配 → 重建默认）。纯规则但显示域，且
  build_configured_well_log_tracks 耦合 geoviz CurveTrack。**归 M8 viz 切片**，
  本切片不移植。

## well-log-engine / geo-viz-engine 公共 API（复用核查）
- well-log-engine（C++，submodule @f845e7ab）：渲染引擎（QPainter tracks、LAS/XML
  preview loader、DatumTransformer）。其公共头**没有**移动平均/中位数/归一化/单位
  换算/重采样/插值核（explore 报告确认）——与 curve_operations 无重叠，无 wrap 可做。
- geo-viz analytics/well_qc.py 的三个纯函数见上节（well_qc 结论）。
- libs/mapping_kernel 已绿核（contouring/interpolator/polygonization/extract/
  class_grid/crs_policy/grid_stats/sample_norm）：与曲线核无函数级重叠；
  GridStatistics/linear 插值语义不同（前者格元统计/PIP，这里深度轴插值）——
  不复用、不重写，本库自包含。

## docs/development/scientific-interpretation-v6/（约束抄录）
- 01/02：unknown ≠ meters（typed 拒绝）；gap 用 NaN 表达且 resample 不桥接；
  NullPolicy 四态、derived 注入必须记 provenance；m/ft 只经白名单换算。
- 11-decisions：unknown/默认值纪律（「one authority per fact」——单位分类的唯一
  权威是 well_science.classify_depth_unit，C++ 侧同构单一实现）。
- 13：LAS 预览的 -999.25 推断白名单是**已记录的**假设（loader 域，不在本核）。

## 测试清单 → oracle 案例映射（已全文阅读的测试）
- tests/test_well_science.py、test_curve_operations_toolbox.py、
  test_curve_interpretation.py、test_depth_unit_consumers.py、
  test_curve_operation_dialog.py、test_well_table.py、test_well_log_api.py、
  test_well_log_core_hardening.py、test_well_log_track_settings.py、
  test_well_log_load_fast.py、test_well_load_cancel_honesty.py、
  test_well_log_load_full_resolution.py、test_well_log_cache_threading.py、
  test_las_parser_provider.py、test_multi_well_unit_gate.py（全文）；
  adapter/UI 域命中（engine_adapter/audit_viz/stratigraphic/visualization_*/
prediction_helpers/issue842/well_tie_host）按命中行核对：均为信封/加载层消费者，
无新增纯核断言。
- Python 断言全部转成 C++ oracle 案例（见 fixtures JSON 的 `python_test_suite` 组）。
