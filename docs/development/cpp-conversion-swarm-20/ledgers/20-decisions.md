# CONV-20 Decisions — mapping_kernel pybind 门面

每个非显然选择一条；引用 findings 的章节号。

- **D1 模块名 `pwb_mapping_kernel`、门面模块 `paleo_workbench/mapping/geological_pipeline/native_bind.py`。**
  顶层 import 名照任务 §7；门面是**新文件**，不改 `interpolator.py`/`pipeline.py`/`well_prediction_surface.py`
  的任何一行（§6 禁止改算法语义）。现有调用方继续走纯 Python；加速是显式 opt-in 的同名门面函数 +
  `geological_pipeline.HAS_CPP` 再导出（§6 明确允许 __init__ 增加 HAS_CPP 探测）。

- **D2 构建 = 仓库根 CMake `BEGIN CONV-20` 开关 + `libs/mapping_bind/`，不走 setup.py 包。**
  核已在 `libs/mapping_kernel`（CMake 静态库），复用它避免把已绿数值核再编译一遍；CPP_EXTENSION.md 的
  setup.py 路线针对"源在子模块"的 map_edit_core，不适用。`option(PWB_BUILD_CONV_20 … OFF)` 默认关，
  不进 integrated gate；configure 时 fail-closed 要求 `PWB_BUILD_MAPPING_KERNEL=ON`（ON 即真存在，照既有
  B/C/D/E 开关惯例）。

- **D3 pybind11 v3.1.0 头树 vendor 进 `libs/mapping_bind/_vendor/pybind11/`（include/** + LICENSE + README）。**
  本机 PyPI 不通（pip 无网络），github 偶发可达；仓库先例是 vendor sqlite amalgamation + nlohmann 单头。
  55 头 1.2MB、BSD-3，README 注明 tag 与上游出处。CMake 不用 `find_package(pybind11)`，直接
  include 该目录 + `find_package(Python3 … Development.Module)` + `Python3_add_library(… MODULE WITH_SOABI)`。

- **D4 绑定层 numpy-free。** 传 `std::vector<double>/float` → Python list，numpy 数组化由门面做
  （`np.array(..., dtype=float32).reshape`）。不引 pybind11/numpy.h：构建免 numpy 头，运行时 import 模块
  不触发 numpy 依赖（ctest 冒烟可在最小解释器跑）。grid 50×50=2500 float 的 list 开销可忽略。

- **D5 records 经递归 py→Json 转换器进出，不走 json 字符串。** `json.dumps` 会把 NaN 打成 `NaN` 字面量，
  nlohmann 严格解析直接失败；递归转换器把 int→int64、float→double（保留 1 vs 1.0 类型差异与 NaN/inf）、
  bool 先于 int 判、未知对象存 repr 字符串（C++ 与 Python 都会把它当不可解析值跳过，行为一致）。
  出向 json→py 同样递归（ordered_json → dict 保序，测试用 dict 相等不受影响）。

- **D6 绑定层不做输入清洗/防御。** 消息逐字的 std::invalid_argument（→ValueError）是核的冻结契约；
  tie/radius 边界的 "unique-distance neighbour sets" 限制照核注释如实传到门面文档，不假装更宽。

- **D7 kriging 分流规则：geoviz 可 import 且未请求邻域参数时门面留在纯 Python，其余走 C++。**
  C++ 核 = numpy-grid-OLS fallback 的忠实移植（findings §4）；geoviz WLS 引擎是**不同估计器**，C++ 无对应。
  分流条件与 Python 端 estimator 选择一一对应：geoviz 缺席（ImportError fallback）或邻域参数使
  Python 必走 numpy 路径（interpolator.py D3 决策）→ C++ 与 Python 同估计器，可安全加速；
  geoviz 在且无邻域 → 引擎 WLS，不可替代。IDW/class_grid/extract 无此问题，恒可加速。

- **D8 选项 dict 由门面从 `InterpolationOptions` dataclass 显式生成，C++ struct 默认值永不生效。**
  Python 默认 method="kriging" vs C++ "idw" 的分歧（findings §4）由此免疫；门面行为与纯路径逐字段一致。

- **D9 门面补发 Python 侧可观察的混族 warning**（logger 名与消息与 pipeline.py 一致），因为 C++ 核不接
  logging；geographic-CRS 升级 warning 由门面统一调用 Python `resolve_distance_policy` 自然带上（D10），
  其余逐记录 warning 不复刻（无测试钉死，Karpathy 最小代码）。

- **D10 distance_policy/annotation 以 Python `resolve_distance_policy` 结果覆盖 C++ 字段。**
  C++ builtin 表无 pyproj：非 builtin id（如 EPSG:32650）在装 pyproj 的环境里两面的 annotation 文本会分叉
  （findings §4 crs_policy）；policy 解析是纯字符串逻辑（非数值核），让 Python 权威面保持逐字一致，
  数值网格不受影响。lru_cache 语义原样保留。

- **D11 门面 `algorithm_parameters` = C++ FactorGrid 字段映射到纯路径键名 + sample_points + domain + policy；
  不复刻 degraded/neighborhood 披露块。** 披露块的措辞绑定"numpy 路径"叙事，C++ 路径硬抄会撒谎；
  数值面（grid/variance/axes/statistics/algorithm_id）是 parity 契约（任务 §7.4 max-abs）。
  门面是新入口，无既有消费者，零回归风险。

- **D12 门面 extract 返回重建的 `GeologicalFactorDataset`（真 dataclass），非 dict。**
  与纯路径返回类型相同才是 drop-in；inf 坐标两面都在 `GeologicalFactor.__post_init__` 抛 ValueError
  （findings §9），无额外守卫。

- **D13 `mapping_bind.smoke` ctest = Python 脚本经 ctest 运行**（PYTHONPATH 指向 build 内模块目录），
  载入冻结 oracle JSON 逐案例对账 + 错误文案断言。比 C++ 二进制更强：它测的是**真正过桥后的模块**。
  fixture 生成器 `libs/mapping_bind/oracle/generate_fixtures.py` 只 import 真实 Python 模块（§2.5 红线），
  NaN→null、ensure_ascii=False、float repr 往返，与 tools/oracle 家族约定一致；产物
  `libs/mapping_bind/mapping_bind_tests/fixtures/bind_oracle.json` 入库。

- **D14 pytest `tests/test_mapping_kernel_bind.py`：module 级 `skipif(not HAS_CPP)`**（照
  test_map_edit_core_cpp.py 范式）； parity = 门面 vs 纯 Python 在同 dataset 同 options 下
  grid max-abs（IDW ≤1e-6、kriging ≤1e-4，与 mapping_kernel_tests 容差一致）、axes ≤1e-12、
  variance 同容差、错误文案全等、extract 逐字段相等、class_grid 精确 0；另用 monkeypatch 把
  `_kernel=None` 验证"缺失时保持纯 Python"的分派逻辑。扩展缺失时整个模块 skip（§4 未编扩展场景）。

- **D15 PIC：`set_property(TARGET pwb_mapping_kernel PROPERTY POSITION_INDEPENDENT_CODE ON)`。**
  模块 .so 链接静态核要求核对象 PIC；这是构建属性，不触碰任何数值源文件（红线的"重写数值核"不涉及），
  记录于此作为对 mapping_kernel 目标的唯一改动。

- **D16 `.so` 不入 git、不落仓库根**（.gitignore 已 ignore；影子 .so 是本仓踩过的坑，findings §3）。
  用户流程=构建后 `PYTHONPATH=build/conv-20` 运行，或把模块拷入环境 site-packages；
  PR 里给出一行拷贝命令。

## 审核轮追加（2026-09-18）

- **D17（审核1 P1-3，记档不修）字符串坐标解析差异是冻结核契约。** C++ extract 的 `py_float`=
  strip 后 strtod 全串消费；`"0x10"`→16.0（Python float() 会跳过该记录）、`"1_000"`/bytes 被 C++ 拒收
  （Python float() 收）。改核触碰已绿 mapping_kernel 红线；差异已写入门面 docstring 的
  frozen-contract limits。M6 extract oracle（22 案例）冻的就是 strtod 语义。
- **D18（审核1/2，记档不修）IDW kNN tie 语义。** C++ tie-break=(dist, idx)，scipy=cKDTree 树序；
  冻结契约只对 unique-distance 邻域集成立（interpolator.hpp 头注释）。合成 tie 数据集上两者可差
  ~0.86（审核2 实测）——门面 docstring 明示；不构造 tie 的 parity 测试假装相等。
- **D19（审核1 P1-1，已修）geoviz 探针改为 `from geoviz import fit_variogram, kriging_grid,
  leave_one_out_predictions` + 仅捕 ImportError**，与纯路径探针逐字对应；非 ImportError 失败两面都传播。
- **D20（审核1 P1-2，已修）C++ kriging 补披露元数据**：`degraded=True`/`degraded_reason`（如实写明
  "mapping_kernel C++ kernel … numpy-grid-OLS estimator, geoviz WLS engine bypassed"）/`r_squared=None`；
  常量场+邻域时补 "constant field: every estimate is the sample mean" note（与 numpy 路径同构）。
- **D21（审核2，已修）fixture id≠内容三处**：`krige_wells8_sph`→`krige_wells8_gau`（实冻 gaussian）；
  `extract_nested_attributes`→`extract_nested_value` 并新增 `extract_nested_factor_name`（子字典 factor_name
  分支）；`class_clip_inclusive` 环坐标改 2.5/7.5 使格点恰落环边，真正钉死 inclusive-on-edge。
- **D22（环境事实修正）conv12 venv 有 geoviz**（早前误判为缺）。后果：(a) fixture 生成器本就以
  `sys.modules["geoviz"]=None` 钉 numpy-grid-OLS，冻结不受影响；(b) pytest 新增 `no_geoviz` fixture
  （同样 sys.modules pin，黄金基线技法）让 parity 真正走 C++ kriging vs Python numpy 路径；另加
  estimator-gate 测试证明 geoviz 在场时普通 kriging 留纯 Python（引擎 WLS）、邻域 kriging 走 C++。
- **D23（审核1 P1-4，已修）巨大 int 不再炸整次 extract**：to_json 的 int64 溢出回退
  `cast<double>`（10**30→1e30；超 double 范围仍抛 OverflowError，与 Python float() 一致）。
- **D24（审核2 P1 覆盖缺口，已修）pytest 补齐**：常量场（全局+邻域）/重复点合并/未知变差模型/
  qc+NaN 过滤/kNN 路径 exact hit/power=1/grid_n 钳制/masked==0 边界域/extract 七组分支
  （子字典 factor_name、嵌套别名、val-None 跳过、float(val) 失败、派生守卫 H_t≤0 与 base≤top、
  空与非 dict 记录、target_horizon 形参）；统计容差与网格容差对齐（1e-6/1e-4）。
- **记档不修（P2 家族，均为桥的固有有损语义或病态输入）**：非字符串 dict 键经 Json 往返字符串化；
  NaN/inf 作 str 值经 nlohmann dump 成 "null"；容器值的 str() 是 JSON 文本而非 Python repr；
  truthy 非字典 properties 不复刻 Python 的异常路径；cyclic 输入在 C++ 递归转换器中无界
  （Python 侧浅拷贝存活）；extent 长度错误 TypeError vs ValueError。json→py 的 unsigned 先于
  signed 检查与 bool 先于 int 顺序已核审无误。
