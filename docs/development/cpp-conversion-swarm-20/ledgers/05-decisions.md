# 05 — Decisions: Haiyou constrained-IDW 数值核移植

每个非显然选择及其理由。歧义按「对用户流程更诚实、更少抽象」裁定。

## D1 — 移植 seam = 引擎级 `generate_constrained_idw`，而非 adapter 级 `run_constrained_idw`

`run_constrained_idw` 的 hull 合成依赖 shapely/GEOS 的 `convex_hull().buffer()`，
其缓冲几何（圆弧离散、mitre 参数）无法跨语言 bit 复现；CRS 判断依赖 pyproj；
CV R²/anchored fidelity 是宿主评估指标。这些是**胶水**（§7.1）。C++ 核镜像
引擎契约：`(wells, boundaries, barriers, directions, config) → grid`。oracle
生成器用 **spy 包装** `engine["generate_constrained_idw"]` 捕获 adapter 真实
传入的 wells/boundaries/barriers/directions/config（dataclass asdict 原样冻结，
零镜像推导），C++ 测试吃同一输入 → 逐格对账 grid_z。adapter 契约键
（n_points/min/max/mean/search_radius/…）由生成器同时冻结，C++ 测试从自己
的网格重算统计量对账。

## D2 — 等值线提取/后处理整链不移植（诚实 skip）

`extract_contours=True` 时引擎在返回 grid_z **之后**才构建提取面
（`prepare_contour_extraction_surface` 起的全部 MS/贴边/消交/绕行只写
`result.contours` 与 `surface_*`，不再修改 `grid_z`——引擎 1332–1707 行顺序
证明）。本切片用户流程验收 = "C++ 网格与 Python run_constrained_idw 逐格
对账"（§4），故等值线链不进核。C++ 头注释如实声明 skip 范围；`levels` 参数
被引擎表面路径忽略，C++ API 不收 levels（少一个无效果形参）。scipy 的
`binary_erosion/label/maximum_filter` 全在该链上，随之不需要。

## D3 — `extract_contours=False` 早退分支保留为 C++ 行为

引擎在提取前有 `if not extract_contours: return` 早退（显示网格已含 blank
NaN 语义）。C++ 核按 extract_contours 语义返回同一网格——实际上两种取值下
C++ 返回相同 grid_z（Python 亦然，adapter 注释声明 "grid is bit-identical
to the surface-only pass (verified by tests)"）。C++ API 因此不暴露该开关，
但在 fixture 中冻结一个 extract_contours=False 的引擎直调案例作为证据
（generate 直调场景，diagnostics 含 `contour_extraction_skipped=1`）。

## D4 — scipy `distance_transform_edt` 用精确 EDT 复现（bit 级）

scipy 返回每个前景格到最近背景格的**精确**欧氏距离（整数平方距离开方，
IEEE sqrt 正确舍入 → 确定）。C++ 实现 Felzenszwalb/Huttenlocher 两趟
（行 1D → 列 1D，整数运算），平方距离与 scipy 完全一致 → sqrt 后 bit 相同。
两处消费：`refine_domain_boundary_transition`（EDT(domain_mask)）与
`build_bfs_reach_mask`（EDT(~seeds)）。全真输入（无背景）时 scipy 返回
`inf`（整数下包络无解）——C++ 同样返回 inf，refine 的 `dist≤feather` 与
reach 的 `dist≤cells` 判定自然为 False，与 Python 一致（fixture 中无此退化，
语义记录在头注释）。

## D5 — 对照容差：NaN 图案精确 + finite 差 ≤ 1e-8(abs) & 1e-9(rel)

上游自身的 parity 测试承认 `np.hypot` vs `math.hypot` 1 ULP 漂移
（engine_parity anchor 用 rtol=1e-12），本移植 std::hypot vs numpy libm hypot
同理；其余路径（EDT、pairwise sum、稳定排序、逐元素算式）全部 bit 级复现。
逐格断言：NaN/finite 位置逐一相等，finite 差 ≤ max(1e-8, 1e-9·|want|)，并
输出 worst diff 作证据。grid_x/grid_y（linspace）要求 ≤1e-12。diagnostics
整型计数要求精确相等。统计量 min/max ≤1e-9、mean 相对 ≤1e-9（np.mean 的
pairwise 求和树在 C++ 侧以相同算法复现，实际为 bit 级，容差只防 JSON 往返）。

## D6 — numpy RNG 不可跨语言：`estimate_mean_well_spacing` n>400 不子采样

上游对 >400 井用 `np.random.default_rng(0).choice` 子采样 400（PCG64 bit 流
无法在 C++ 复现）。C++ 对 n>400 直接全点计算并在头注释声明偏差；n≤400
（所有 fixture 与产品常态）逐 bit 一致。fixture 全部 n≤400。

## D7 — `np.argsort`（quicksort）在 along-track profiles 的并列 s

`build_along_track_well_profiles` 用默认 quicksort 排 (s,z) 样本；s 精确并列
时顺序未定义。两个 s 并列 ⇒ 两井投影到同一弧长（测度零事件）。C++ 用稳定
排序；fixture 井位为无理坐标组合，不产生 s 并列。decisions 记录该已知边界。

## D8 — 归因进 C++ 头注释

`ATTRIBUTION.md` 要求保留出处：上游 repo/SHA `5b8f8f98`、host 修复三类
（#370 走廊 NaN、#382 LOS 恒点路径、#924 hull 存在性）、#933 batch 核。
`constrained_idw.hpp` 头注释携带全部出处与本切片 skip 清单。

## D9 — CMake 只追加 `BEGIN/END CONV-05` 块

- 根 CMakeLists：`option(PWB_BUILD_CONV_05 …)`，ON 时置
  `PWB_BUILD_MAPPING_KERNEL ON`（普通变量，位于其 if() 之前）。
- `libs/mapping_kernel/CMakeLists.txt`：`target_sources(pwb_mapping_kernel
  PRIVATE src/constrained_idw.cpp)`（不重写 add_library 行）。
- `mapping_kernel_tests/CMakeLists.txt`：新增可执行 `mapping_kernel.constrained_idw`
  + `add_test` + fixture 路径宏。不触碰其他 CONV-* 块。

## D10 — batch 与逐点核只实现一份（逐点参考语义）

上游 #933 batch 核与其逐点循环 bitwise 相等（上游 parity 测试锁定，且
`generate` 无断层+无方向时走 batch、有断层时 batch 与逐点在同输入下同值）。
C++ 实现逐点参考语义（同一 radius-pass 松弛、同一稳定 top-k、同一
`np.sum` 配对求和顺序），单份代码覆盖两条路径，避免双实现漂移。
`np.sum`（k≤12）按 numpy pairwise 求和算法（n<8 顺序；8..128 八累加器树）
复现，保 ULP 一致。

## D11 — diagnostics 冻结为数值对账的副证据

引擎 diagnostics（region_count、有效/无效格数、blocked_well_grid_relations、
well_anchor_* 等）随 fixture 冻结，C++ 逐一比对——用极低成本锁住分支选择
（label 门控、LOS 计数、锚定路径）是否走对。

## D12 — 错误分支用真实 Python 异常文案冻结

引擎 `<3 井` → `"有效井点不足，至少需要 3 个，当前 N 个"`；`无边界` →
`"当前图层模式需要至少 1 个边界面"`；axes 空顶点 → `"边界面缺少有效顶点"`。
adapter 级 `<3 有效样本` 文案（含全角括号）同样冻结（C++ API 引擎层，用
引擎文案；adapter 文案留在 Python——fixture 记录两者，C++ 只断言引擎层）。
C++ 抛 `std::invalid_argument`（what() 与 Python str(exc) 逐字相同）。

## D13 — oracle fixture 直接提交 JSON（沿用既有模式）

前序切片（contouring/interpolator/polygonization/…）把生成器放
`tools/oracle/generate_*_fixtures.py`、冻结 JSON 放
`libs/mapping_kernel/mapping_kernel_tests/fixtures/*_oracle.json`。本切片沿用：
`tools/oracle/generate_constrained_idw_fixtures.py`（import 真实
paleo_workbench adapter + vendored 引擎，spy 捕获）→
`fixtures/constrained_idw_oracle.json`。JSON float 用 repr 短格式（round-trip
精确）。

## D14 — C++ 公开面最小化

`pwb::mapping::constrained_idw` 命名空间只导出：输入结构（Well/Boundary/
Barrier/Direction/Config）、`Result`（grid_x/grid_y/grid_z/diagnostics）、
`generate_constrained_idw(...)`。几何/掩膜/插值/锚定等全部实现细节留在 .cpp
匿名命名空间。没有 spec 之外的配置点（Karpathy §2）。

## D15 — oracle 的捕获 seam 必须锁定"第一次引擎调用"

`run_constrained_idw` 在返回前会用同一 `generate` 引用（即 spy）为空间
4 折交叉验证重入引擎 4 次（训练子集 + `extract_contours=False`）。spy 若每次
覆盖捕获，会把最后一折的 7 井/小 config 当成引擎输入，而期望网格来自全量
表面 pass——fixture 内在不一致（wells=7 vs n_points=9）。spy 现按
`first_call` 门只捕获表面 pass；这是生成器最关键的一条不变式。

## D16 — 数值对齐中抓到并修复的三个移植 bug（审核与阶段对拍记录）

1. 精确 EDT 的提取循环边算边覆写同一缓冲，后续位置查询到已覆写值——
   改为分离输出缓冲（暴力对拍 200 随机掩膜 worst=0）。
2. `build_bfs_reach_mask` 误把 seeds 当 EDT 输入；scipy 语义是
   `distance_transform_edt(~seeds)`（取补）——已修。
3. 锚定第二阶段非各向异性支路的局部均值窗口 `sample_r` 按 Python
   `ceil(1.6*step/step)=2`（5×5），首版误写 1（3×3）——已修。
   另：`int(round())` 全部改 banker's（`nearbyint`）并对 int 转换前钳制；
   `blocked_indices` 用集合语义（标记向量）去重；空 hull 栅格仍按"已物化"
   清空 domain；`block_mode`/`extend_mode` 走 `.strip().lower()`。
