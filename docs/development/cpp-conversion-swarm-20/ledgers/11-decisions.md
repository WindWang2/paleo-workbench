# 11 — decisions：测井曲线解释纯核

每个非显然选择记录在这里。日期 2026-09-17。

## D1 — prompt 内路径失效，按真实仓库执行
prompt 写的 `/home/kevin/projects/paleo_project/main`、`/home/kevin/.grok/skills/goal-loop/SKILL.md`、
`.agents/skills/karpathy-guidelines` 在本机不存在。真实仓库是
`/home/kevin/project/paleo-workbench`（origin = WindWang2/paleo-workbench，main @ 35987e13
与 prompt 声明的基线一致）。worktree 按同级约定建在
`/home/kevin/project/worktrees/cpp-conv-11-curve-ops`。goal-loop 契约按 prompt §0 内嵌
条款执行（账本 `.goal-loop-ledger.md` 每轮一行、§8 完成条件、subagent ≤3、不等 CI）。

## D2 — oracle Python 环境用 venv（系统 python3 无 numpy/scipy）
系统 python3 是 3.14.6、无 pip/numpy/scipy，跑不了被测模块。建了专用 venv
`/home/kevin/project/oracle-venvs/conv11`（numpy 2.5.3 / scipy 1.18.1，仓库外）。
生成器只 import 真实生产模块，不手写期望值。

## D3 — geoviz QC 模块按文件路径直接加载
`geo-viz-engine` 的 `geoviz`/`geoviz_plots` 包 `__init__` 硬依赖 PySide6（本机未装）。
well_qc 引用的三个纯函数的真实生产文件
`packages/geoviz_plots/geoviz_plots/analytics/well_qc.py` 只依赖 numpy，生成器用
importlib 按路径加载**同一文件**（shim 里 `("geoviz_plots","compute_sand_ratio")`
最终解析到的就是它）。不装 PySide6、不复制代码。

## D4 — 移植范围：curve_operations 全部 + well_science 全部 + curve_interpretation 纯核
- 移植：moving_average、median_filter_curve、normalize_curve、clip_outliers、
  normalize_unit_name、conversion_factor、convert_values、resample_axis、
  interp_nan_aware、interp_gap_preserving、missing_interval_report(+Report)、
  evaluate_curve_expression、classify_depth_unit、require_depth_unit(+错误)、
  DepthUnitInfo、NullPolicy、null_policy_from_declared、depth_shift、despike、
  baseline_shift、CURVE_OPERATIONS/OPERATION_SCOPE 元数据表。
- 不移植（findings 已分类）：apply_curve_operation/_ensure_writable_well_header
  （catalog+lasio 工程对象）、well_qc 行规则（井表流，公式归属 geoviz 契约，
  §7.3 不复制另一引擎公式；且非"LAS 曲线"用户流）、viz 三文件的工程对象
  （native_backend/minmax_downsample 已有 C++ 双路径实现；layout 归 M8）。

## D5 — 库名/文件名与 09 错开
09 未合并（远端只有 main + 两个无关分支）。`libs/well_science` 由本任务创建，
curve 核文件名 `curve_ops.hpp/.cpp`（09 的 DTW 按约定叫 `dtw.cpp`，不冲突）。
evaluate_curve_expression 的解析器与求值器放 `curve_expr.hpp/.cpp`（规模原因分文件，
仍属本库）。CMake option `PWB_BUILD_CONV_11`，根 CMake 只追加 BEGIN/END CONV-11 块。

## D6 — 表达式求值器：手写递归下降，值域 = 标量或首变量形状的数组
Python 走 ast 白名单 visitor；C++ 无 ast，改为对**同一受限文法**的递归下降解析
（文法覆盖 Python 运算符优先级：or<and<比较<+−<* / // %<一元<**右结合，链式比较，
n 元 and/or）。语义复刻 NumPy：
- 值模型：`double`（标量）或 `vector<double>`（数组，长度=首变量 n）。
- 布尔 = `v != 0`（NaN→true，实测 numpy 行为）；比较结果 0/1。
- `%`/`//` 用 Python 语义（除数取号 / floor）；负底分数幂 `std::pow`→NaN 与 numpy 一致；
  min/max=元素级 + NaN 传播；where/clip 同。
- 广播：标量与数组运算提升为数组；数组-数组长度不等 → 抛错。0-d 结果在终局广播到
  首变量形状（对应 numpy 0-d→broadcast_to）；长度不齐 → "expression did not produce a
  sample-aligned result"。数组-数组长度不等在 Python 里由 numpy 抛
  `operands could not be broadcast together with shapes (n,) (m,)`——C++ 复刻该文案格式
  （numpy 1.x/2.x 文案稳定；这是 numpy 内部文案而非模块契约，格式以本仓安装的
  numpy 2.5.3 为准并在测试中冻结）。

## D7 — 中位数滤波的边界延拓
实测 scipy `median_filter(mode='reflect')` == `np.pad(mode='symmetric')`（边缘样点
镜像重复）。C++ 用对称延拓索引映射 + 窗口拷贝全排序取中位数（numpy_median，行为等价）；NaN 位先填全局
有限中位数再恢复 NaN（与 Python 一致——填充影响窗口邻居的中位数，这是忠实语义不是 bug）。

## D8 — moving_average 的卷积偏移
`np.convolve(..., 'same')` 偏移已实测：窗口 [i−⌈(w−1)/2⌉, i+⌊(w−1)/2⌋]（偶数窗 trailing
偏一格），越界贡献 0；sums/counts 同时卷积。C++ 直接双前缀和/滑窗复刻，w>0 校验、
w = min(max(1,window), n)。

## D9 — depth_unit_of 的 duck-type 契约在 C++ 中的形状
Python 读任意对象的 `depth_unit` 属性；C++ 核没有鸭子类型。核 API 收
`std::optional<std::string>`（文档的信封值或 nullopt），信封判断留给调用方
（与 viz/well_log_load 的 Python 侧行为一一对应，语义不变）。

## D10 — 错误模型
数值核的错误分支（单位不识别/白名单缺对/下降轴/坏参数/表达式拒绝）按 Python 文案
逐字冻结（`{}` 内插值格式一致），C++ 用 `pwb::well_science::CurveOpError`（std::runtime_error
子类）+ 异常类型字段承载 UnknownDepthUnitError 的 info/operation。测试断言 what() 全文。

## D11 — 库依赖零外部（Qt-free、QGIS-free、无 numpy 等价物）
只用 C++20 标准库（vector/string/math/cmath）。JSON 读取用仓库已 vendored 的
nlohmann 单头（mapping_kernel 测试同款先例）——测试目标依赖，库本身不依赖。

## D12 — well-log-engine 不 wrap
explore 盘点（配额 1/3）确认引擎公共 API 无平滑/中位数/归一化/单位换算/通用重采样/
NaN 感知插值核（table_projection 明文拒绝 auto-interpolation；唯一单位换算在 lis.cpp
内部不导出）。§7.3 的"复用优先"无对象可复用，本库自包含；引擎缓冲/QC 模型留待
后续接线切片。

## D13 — oracle 冻结容差
曲线数组逐元素 `abs diff ≤ 1e-12`（relative 1e-9 兜底）；中位数/百分位类 1e-12；
despike MAD 路径 1e-9（median 级联放大）。表达式/单位/报告为精确值或位模式。
失败分支冻结 what() 全文 + 是否抛出；`invalid expression:` 类语法错误用 prefix 匹配
（CPython SyntaxError 文案不是模块契约）。

## D14 — geoviz QC 的 oracle 组从冻结文件中移除
生成器最初也冻结了 geo-viz analytics（well_qc 数学）20 案例；D4 决定不移植后，
这些案例在 C++ 侧没有被测对象，保留只会诱使测试复刻公式（第二实现，反模式）。
已从 `curve_ops_oracle.json` 移除（287 案例），行为分析保留在 findings。

## D15 — oracle 生成器自身的缺陷在首轮跑测中暴露并修复
（a）`missing_interval_report` 的 intervals 含 NaN 时 json.dumps 写出裸 `NaN` 字面量
（非严格 JSON）→ 一律经 jval 编码；（b）`require_depth_unit` 案例最初没记录输入
token（info 对象序列化丢失）→ 增加 `token_kind` 字段；（c）`pytest:basic` 案例漏了
`expect_fraction/expect_largest` 字段 → const ordered_json 缺键访问返回垃圾值
（dump 为空、get 抛 302），案例字段必须完备。

## D16 — scipy reflect 边界公式与求和语义的实测教训
（a）`median_filter(mode="reflect")` 的对称镜像索引是 `p<0 → -p-1`、`p≥n → 2n-1-p`
（首版写成 2n-2-p，被 `nan_gap_neighbors_medians` 案例抓住）；早期人工验证直接用了
np.pad 结果、没验证公式本身——教训：验证必须覆盖"公式"而不是"公式来源"。
（b）`moving_average` 的卷积和必须把非有限样本当 0 贡献（Python 的
`filled = where(finite, arr, 0.0)`），首版直接累加原值导致 inf×传播。
（c）`conversion_factor` 报错文案的 `!r`：字符串带引号、None 不带
（`unrecognized unit (None -> 'm')`）。

## D17 — numpy 内部错误文案不冻结，行为冻结为抛出
对抗审核确认：clip 单边界/where 参数数/min-max 错参数数在 Python 里抛的是 numpy 的
TypeError（模块未转译）。这不是 curve_operations 的契约文案，跨 numpy 版本不稳。
C++ 侧冻结行为（抛 CurveOpError）与稳定语义，文案用本库固定文本，由
audit_regression 组的 7 条直接断言钉住（不进 JSON oracle）。

## D18 — 长度失配与非有限 span 的防护
Python 在 x/y 长度失配时以 IndexError/广播错失败；C++ 首版静默截断（错误行为）。
现改为显式抛 CurveOpError("... needs ... of equal length")；resample_axis 的
(stop-start)/step 非有限时 Python 抛 OverflowError/ValueError，C++ 抛
CurveOpError 防 UB 转换。均为 misuse 分支，文案为本库契约。

## D19 — 未修的 P2（如实记录）
(a) `!r` 的转义：冻结文案只涉及简单 token，未实现 Python repr 转义器（单引号直包）；
含引号/反斜杠的单位名不受支持（可接受：LAS 单位头不会出现）。
(b) 数字字面量 0x10 / 1_000 / 1j：Python ast 接受，C++ 解析器报语法错误
（两侧行为都安全，测井表达式不会出现）。
(c) where/min/max 错参数数的具体文案两侧不同（均抛出，非契约分支）。
