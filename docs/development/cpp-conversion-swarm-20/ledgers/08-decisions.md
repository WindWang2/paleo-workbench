# 08-decisions — 因子插值任务宿主

> 「对用户流程更诚实、更少抽象」原则下每个非显然选择的记录。目标切片：
> fingerprint 字节一致、evaluation 指标在冻结网格上一致、plan 数据结构 round-trip。

## D-1 新库 `libs/factor_host/`，不进 mapping_kernel
- §6 允许两种落点；选独立库：mapping_kernel 全绿测试已在门禁里跑，往里加文件
  会让 CONV-08 与 M6/M7 的语义边界（哪些叶子属于哪次转换）在 git 历史里不可分。
- 命名空间 `pwb::factor_host`；Qt-free、Python-free、numpy-free；
  仅依赖 `Pwb::Domain`（nlohmann ordered_json + Sha256）。

## D-2 canonical JSON 编码自写，不用 nlohmann dump
- Python `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",",":"),
  default=str)` 的 float 走 repr（最短往返）、-0.0 保留符号（上层已归一）、
  NaN/Infinity 输出为 `NaN`/`Infinity`、键排序为码点序。nlohmann dump 的 float
  格式与键序行为都不同。
- 实现一个只覆盖 payload 出现类型的编码器（null/bool/int/double/string/array/
  object），double 用最短往返算法 + Python repr 的格式规则（-4 ≤ exp < 16 定点，
  否则科学计数 e±XX 至少两位指数）。oracle 同时冻结**编码串与哈希**，失配可定位。
- q/b_i 的 NaN/Infinity 路径如实保留（Python 侧本来就会编码 NaN）。

## D-3 范围：三个模块的纯叶子 + plan 数据结构；引擎与编排层不移植
- fingerprint：stable_sha256、_finite_float、extract_sample_records、resolve_backend、
  backend_uses_*、_normalize_polylines、_normalize_direction_params、
  build_factor_fingerprints、FactorFingerprints(to_dict)、FactorDirtyState、
  stored_fingerprints_from_task、task_has_numerical_output、classify_factor_recompute、
  plan_cache（LRU）。
- evaluation：bilinear_sample_grid、signed_r_squared、EvaluationMetrics、
  spatial_fold_assignment、leave_one_well_out_folds、cross_validate_surface、
  surface_residuals、residual_features、_validate_recommendation_context（CRS 校验
  注入化）、adjudicate_recommendation。
- plan：xy_signature、_fault_signature、PlanKey(+digest)、_grid_axes_from_samples、
  InterpolationPlan、build_idw_plan、extract_values_aligned、plan JSON round-trip。
- **不移植**：fingerprints_for_task（project 约束解析 + memo 胶水）、
  recommend_interpolation_methods（依赖 constraint_capabilities，不在 §5）、
  kriging_leave_one_out / kriging_diagnostics（直接调 geoviz——任务明令不跑引擎；
  后续切片可基于 mapping_kernel kriging 核复刻 Dubrule LOO）、
  _idw_multi_chunked / apply_idw_plan*（值相关引擎路径；本切片是 plan 数据结构，
  且 mapping_kernel 已有 IDW 核）、factor_prepare_scheduler 全部（编排胶水）。
- 依赖语义保留在宿主层：指纹消费 NORMALIZED 样本集（pwb::mapping::
  normalize_factor_samples 提供同款核）、duplicates_present 才写 policy。

## D-4 `fingerprints_for_task` 的 memo 不移植
- memo key 含 sha1 点摘要，是同一请求内的性能缓存，不是科学输出；C++ 宿主按
  build_factor_fingerprints 直接重算即可得到相同指纹。移植它会引入无消费者的
  抽象（Karpathy：不做投机的灵活性）。

## D-5 CRS 校验注入化
- Python `_validate_recommendation_context` 的 crs 分支依赖 pyproj（缺失时
  fail-closed → crs_invalid）。C++ 无 pyproj：签名带 `CrsValidator`
  （std::function<bool(const std::string&)>），默认 fail-closed（非空即无效）；
  oracle 用「EPSG:xxxx 接受、其余拒绝」的映射核同款规则冻结两侧一致案例。
- 这比硬编码半个 CRS 库诚实：能力边界由宿主声明，而不是假装内置。

## D-6 `cross_validate_surface` 的 fold 失败文案
- Python detail = f"fold {i} failed: {type(exc).__name__}: {exc}"。C++ 定义
  `FoldEngineError(exc_type, message)`，run_fold 抛它则 detail 逐字节对齐；
  其他 std::exception 以 type 名 "error" 兜底（该路径无冻结案例，文档注明）。

## D-7 plan JSON round-trip 是 C++ 侧新增契约
- Python InterpolationPlan 没有序列化。§7 步骤 4 要求 round-trip：实现
  `plan_to_json` / `plan_from_json`（键名与 FactorFingerprints.to_dict 同风格、
  数组为普通 JSON 数字列表），恒等断言进 C++ 测试；Python oracle 冻结
  build_idw_plan 产物（轴/源坐标/签名/geometry_id）供 from_json→数值对账。

## D-8 `build_idw_plan` 内置本地 `extract_xy_values`
- Python 版来自 geoviz facade（geoviz_plots.factor.interpolation，纯 numpy）。
  20 行等价移植进 factor_host（x/y 或 lng/lat；value/z/v；非有限跳过），
  避免为 20 行依赖拉 geoviz 包。oracle 由生成器 bootstrap 后调真实 Python
  函数冻结（见 D-9）。

## D-9 oracle 生成器的 geoviz bootstrap
- 本机无 PySide6，`import geoviz` / `geoviz_plots` 包级 `__init__` 都会挂。
- 生成器用 importlib 按文件路径加载**真实** `geoviz_plots/factor/{directional,
  interpolation}.py`（互相引用用最小包壳解析），以 `sys.modules["geoviz"]` 注入
  同一批真实函数对象，再 import 真实的 paleo_workbench.workflow.
  interpolation_{fingerprint,evaluation,plan} 与 factor_interpolation。
- 没有手写期望值：所有期望值来自真实模块在真实解释器里的运行结果。

## D-10 文件存在性分支的冻结边界
- task_has_numerical_output 的 Path.is_file 分支依赖文件系统状态，冻结进 JSON
  无法在 C++ 端复现同一路径。oracle 只冻结非文件分支（无路径/缺失路径/grid_z）；
  文件分支由 C++ 测试在临时目录自建文件断言（positive 与 OSError 等价：不存在）。
  classify 的 artifact-missing 分支用确定不存在的路径冻结。

## D-11 测试目标名 `factor_host.fingerprint`
- §8.4 硬要求。单二进制覆盖 fingerprint + evaluation + plan 三组冻结案例
  （fixture 一份），避免三个目标里只有一个被 Oracle 提名而其余失修。

## D-12 CMake 追加块
- 根 CMakeLists 追加 `BEGIN CONV-08` / `END CONV-08`：option
  `PWB_BUILD_CONV_08`（默认 OFF），开启时 add_subdirectory(libs/factor_host)。
  需要 PWB_BUILD_DATA=ON（Pwb::Domain）；不依赖 mapping_kernel，
  两者可独立开关（门禁命令同时开两者以复核 §8.5）。

## D-13 中文错误文案逐字保留
- 「插值至少需要 2 个有效采样点」「sample geometry does not match interpolation plan」
  「k must be >= 2, got {k}」「observed/predicted shape mismatch: …」
  「unknown interpolation method …」等按 Python 原文冻结（pytest 以 match= 钉过）。
  shape mismatch 的 numpy shape 文本在 C++ 端按 (n,) 格式复刻。

## D-14 numpy 语义的 C++ 复刻点
- np.linspace：y[i]=start+step*i（step=(stop-start)/div），末点强制 stop。
- np.argsort(kind="stable")：std::stable_sort（角度并列保原序）；NaN 角按
  numpy 规则排最后（比较器显式处理，避免严格弱序 UB）。
- np.allclose：|a-b| <= atol + rtol*|b|，NaN 不等（extract_values_aligned 场景
  输入已保证有限，但按 numpy 语义实现）。
- dict 插入序：ordered_json / vector<pair> 保序。
- 浮点最短往返：to_chars 科学位取数字 + Python repr 格式规则重排。

## D-15 审核轮修正（第一轮对抗性正确性 + 第一轮 Karpathy，全部采纳）
- bilinear 退化网格（nx==1/ny==1）按 Python int 负索引语义复刻（wrap + 环绕
  前的小数位计算），消除 size_t 下溢越界读。
- task_has_numerical_output 的 grid_z 判定是 `is not None`（[]/0 算有输出）；
  只有 classify 的 inline-grid 分支用真值——两个语义并存，分别复刻。
- 折线/方向坐标走 raw_float（保留 -0.0/inf/nan），与样本 x/y/z 的
  finite_double 严格区分——Python 只归一化后者。
- direction id 走 `str(raw.get("id") or "")` 的真值回退。
- python_float_from_string 实现严格 Python 字面量文法（拒绝 hex float、
  nan(payload)、下划线、全角数字），float()/int() 的 strip 与 str.strip()
  同用 Unicode 空白集（内部 src/semantics.hpp 单源）。
- cross_validate 捕获所有 std::exception（D-6 的 "error" 兜底落地）；
  FoldEngineError 仍携带 Python 异常类型名用于逐字节 detail。
- 存储的 backend / 非字符串 method 走 python_str_scalar（Python str() 语义）。
- repr 引号切换（含 ' 不含 " 时用双引号）用于错误/警告/rationale 文案。
- 明确不复刻的 Python 崩溃行为（折线点为 dict/3 元组等）记录在 findings
  的「剩余分歧」节，宿主边界保证不触发。
