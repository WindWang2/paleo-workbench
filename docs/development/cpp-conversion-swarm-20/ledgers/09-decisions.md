# CONV-09 decisions — DTW 测井曲线匹配核

每个非显然选择一条。原则：对用户流程更诚实、更少抽象（Karpathy 最小码）。

## D1 忠实移植，而非包装
仓库内（libs/、native/）与 well-log-engine submodule（f845e7ab）均无 native
DTW（findings 有 grep 证据）。按 §7 步骤 1：无则移植。不引入第二套算法，
不"顺便"实现带状/多线程变体（bounded_dtw_band 属引擎 seam，非本核）。

## D2 形态：`libs/well_science` 自由函数，非 DTWLogMatcher 类
Python 是无状态类（全部 staticmethod / 不读 self）。C++ 侧按 mapping_kernel
先例（`pwb::mapping::grid_statistics` 等）用命名空间自由函数：
`pwb::well_science::{normalized, min_max_downsample, match_curves,
transfer_top_index}` + `kMaxCostCells` 常量。省一个无状态类壳。
目录约定：`libs/well_science/include/pwb/well_science/`、`src/`、
`well_science_tests/`；后续 CONV-1x 测井核（formation_top_correlator、
well_section_datum 等 M8 叶子）继续落此目录，新增 .hpp/.cpp 即可，不改
本任务的 CMake 块之外的任何东西。

## D3 位级对账策略：复刻 numpy pairwise summation
回溯器用 `min_val == cost_matrix[i-1,j-1]` 精确比较破平局（斜>上>左的
elif 顺序），路径全等（验收硬条件）要求两侧 DP 矩阵**位级一致** ⇒ 归一化
曲线必须位级一致 ⇒ mean/std 必须复刻 numpy 的 pairwise summation（n<8
顺序；n≤128 八累加器树形合并 + 余项；n>128 二分对齐 8 倍数）。已在
numpy 2.5.2（本仓 venv）用纯 Python 复刻验证 1500+ 数组位级全等。
这是本核与 mapping_kernel「顺序求和 + 1e-12 容差」**有意不同**的精度
策略；不改 mapping_kernel 已绿实现。

## D4 oracle 解释器 = main/.venv/bin/python
系统 python3（3.14）无 PySide6，`paleo_workbench.viz.__init__` 链会拉起
Qt → 导入失败。项目 venv（3.12.13，numpy 2.5.2）可导入真实模块。
生成器 shebang 仍写 python3，运行时显式用 venv 解释器执行（不改动任何
Python 产品行为）。生成器 import `paleo_workbench.viz.dtw_log_matcher`
真实模块，期望值零手写。

## D5 非有限值在 JSON 里编码为带标签字符串
本核 cost 只出现有限值或 +inf（无 NaN 代价：归一化保证有限 dist；±1e308
溢出案例的 inf 也归并到该约定）。JSON 无 NaN/Infinity 字面量，生成器把
非有限值冻结为 "inf"/"-inf"/"nan" 字符串（subagent 审核后从 null 约定
收紧：null 无法区分三种非有限，会掩盖 -inf/NaN 的产出错误）；C++ 侧
`same_finite` 按标签精确核对（含符号），有限值照旧 `==` 位级判等。路径
为空列表是失败分支的第二个信号，两信号同时冻结。

## D6 argmin/argmax 复刻 numpy 的 NaN-优先 + 首下标语义
`_min_max_downsample` 主路径输入已归一化（无 NaN），但它是公开符号，忠实
移植保留 NaN 语义：chunk 内有 NaN ⇒ argmin/argmax 取第一个 NaN 下标；
否则取首个极值。成本 2 行，oracle 冻结 1 个单元案例证明（非投机代码，
是 Python 语义面的一部分）。

## D7 oracle 冻结全输入（含 20000 点长曲线）
长曲线输入若由 C++ 侧程序化重建（linspace/sin），std::sin 与 numpy sin
可能差 1 ulp，破坏 D3 位级前提 → 全部输入以 JSON 冻结双精度 repr 往返
（json.dumps 最短表示可精确往返）。fixture 约 1.4 MB，nlohmann 解析
毫秒级，可接受。

## D8 测试目标名单一 `well_science.dtw`
四个公开符号 + 失败分支放同一个可执行（case kind 分派：normalized/
downsample/match/transfer），对应 §8 的 ctest 正则；不拆四个 target
（构建/CI 成本 > 收益，Karpathy 最小）。链接 Pwb::Domain 仅在测试里
（JSON 解析），库本体 Qt-free 依赖-free。

## D9 CMake 仅追加 BEGIN CONV-09 块
根 CMakeLists 在 PWB_BUILD_MAPPING_KERNEL 块后追加独立块；option 名
`PWB_BUILD_CONV_09`；不改其他 CONV 块、不整理根文件。well_science 库
target `pwb_well_science`（alias Pwb::WellScience），无 QGIS/Qt 链接。

## D10 不移植 formation_top_correlator 的深度轴逻辑
#888/#420/#846 的深度网格推导（median(diff)、降轴镜像、0.5 回退）是
消费层契约，属 M8 后续切片；本切片验收 = 两条合成曲线的 DTW 代价与
路径对账（§4）。findings 已记录其语义防止后续切片走样。

## D11 stride 计算用 int64 乘法
`n_ref*n_target` Python 是任意精度整数；C++ 用 int64 乘法（n≤3e9 时无
溢出，本核设计域 1e5 级采样距溢出 4 个数量级），乘积 ≤2^53 时与 Python
bigint→double 的转换精确一致；`ceil(scale*2.0)` 与 `max(2, …)` 逐一对应。
不引入大整数。

## D12 窗口拒绝分支保留在降采样之后
Python 顺序是"先降采样、后判 |d_n_ref-d_n_target|>window"——拒绝结果
依赖降采样后的长度。保持同序（先降采样后判定），并在 oracle 冻结
"窗口恰好等于长度差"（通过）与"小于"（拒绝）两个边界案例。
