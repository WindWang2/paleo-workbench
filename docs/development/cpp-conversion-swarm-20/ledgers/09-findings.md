# CONV-09 findings — DTW 测井曲线匹配核（viz/dtw_log_matcher.py → C++）

全部 §5 文件均由父代理全文阅读（Read，非 grep 摘要）。本文按文件名索引；
`dtw_log_matcher.py` 的**每个公开符号**单独成条（输入/输出/NaN·空·并列语义/
与已有 C++ 核关系/测试缺口）。

## paleo_workbench/viz/dtw_log_matcher.py（217 行，移植对象）

模块级常量 `_MAX_COST_CELLS = 1_000_000`：代价矩阵格子数上限；超过即对两条
曲线做 min-max 降采样。C++ 侧冻结为 `kMaxCostCells`（测试断言值不变）。

### AlignmentResult（dataclass）
- 输入：无（值对象）。字段 `cost: float`、`path_ref: list[int]`、
  `path_target: list[int]`。
- 语义：`cost` 为 DTW 总平方差代价（有限或 +inf）；两条路径**等长**、
  单调不减、起点 (0,0)、终点 (n_ref-1, n_target-1)；索引是**降采样映射回
  原始空间后**的索引（stride=1 时即原始索引）。
- 失败约定：空曲线 / 窗口带不可达 ⇒ `cost=+inf`、两路径空列表。
- NaN/并列：cost 不产生 NaN（归一化保证有限值）；inf 只来自上述两分支或
  数值溢出（±1e308 级输入的平方溢出）。
- 与已有 C++ 核关系：无对应物，是 `libs/well_science` 首个类型。
- 测试缺口：无直接构造测试；经 match_curves 间接覆盖（等长断言、空路径
  断言）。oracle 冻结 cost + 全路径。

### DTWLogMatcher._normalized(curve)（staticmethod，移植为自由函数）
- 输入：任意 1-D 序列（np.asarray 强转 float64 后拉平）；输出同长 float64。
- 语义（顺序敏感）：
  1. `finite = values[isfinite(values)]`（NaN 与 ±inf 都算非有限）；
  2. `fill = finite.mean()`，finite 为空 ⇒ `fill = 0.0`；
  3. `values = where(isfinite, values, fill)`（插补后全有限）；
  4. `std = np.std(values)`（总体 std，ddof=0；两遍算法：先插补后均值）；
  5. `std` 非有限或 ≤ 0 ⇒ `std = 1.0`；
  6. 返回 `(values - np.mean(values)) / std`（均值是**插补后**重算的）。
- 空数组：原样返回（不进第 2 步之后的分支——`size == 0` 提前返回）。
- 并列/溢出：常数曲线 → std=0 → 1.0 → 全 0；1e308 级输入 → 平方溢出
  → std=inf → 1.0，均值仍有限（±1e308 相加为 0）。
- **对账关键**：np.mean/np.std 用 numpy pairwise summation（n<8 顺序；
  n≤128 八累加器 + 树形合并 + 余项顺序累加；n>128 二分对齐 8 倍数）。
  已在本机 numpy 2.5.2 用纯 Python 复刻该算法，对 1500+ 随机数组
  （n=0..65537）np.mean/np.std **位级全等**（账本第 4 轮）。C++ 复刻同一
  标量算法即可保证归一化输出与 Python 位级一致，进而 DP 矩阵与回溯
  `==` 平局判定完全一致。
- 与已有 C++ 核关系：mapping_kernel/interpolator.cpp 的 `mean_of` 是顺序
  求和 + 1e-12 容差；本核因回溯 `==` 需要位级一致，不复用、不改动它。
- 测试缺口：Python 无 _normalized 单测（经 E3 NaN 测试间接覆盖）；oracle
  补空数组/全 NaN/±inf/单点/常数/溢出/带洞曲线 8 案例。

### DTWLogMatcher._min_max_downsample(curve, bin_size)（staticmethod）
- 输入：1-D float64 曲线 + 正整数 bin；输出 `(values, indices)`，indices
  严格递增 int64，指向输入曲线原始位置。
- 语义：`n == 0 or bin_size <= 1` ⇒ 恒等返回 `(curve, arange(n))`。否则每
  bin（末 bin 可短）取 argmin 与 argmax 两个代表样本，按**原始索引升序**
  输出（min_idx<max_idx → 先 min 后 max；反之先 max 后 min；相等 → 单点）。
- argmin/argmax 并列语义：numpy 返回**首个**极值下标；**NaN 优先**——
  chunk 内只要有 NaN，argmin/argmax 都返回第一个 NaN 的下标（值随
  NaN 带出）。match_curves 主路径中输入已归一化（全有限），NaN 分支为
  死代码，但作为忠实移植保留并冻结 1 个单元案例。
- 输出规模 ≤ 2·ceil(n/bin_size)（#1054 薄层尖峰存活契约）。
- 与已有 C++ 核关系：`well_log_api.minmax_downsample`（native_backend 渲染
  LOD，target_pixels 语义）与 well-log-engine 的渲染降采样是**不同契约**，
  不复用不混淆。
- 测试缺口：test_issue1054 全覆盖（尖峰存活、极值窗、≤2/bin、恒等旁路）；
  NaN/并列首下标无 Python 测试 → oracle 补。

### DTWLogMatcher.match_curves(curve_ref, curve_target, window=None)
- 输入：两条可含 NaN/±inf 的曲线；`window`（Sakoe-Chiba 半宽，None=满带）。
- 流程（顺序敏感，全部复刻）：
  1. 双侧 `_normalized`；任一空 ⇒ `{+inf, [], []}`；
  2. `n_ref*n_target > 1e6` ⇒ `scale=sqrt(n_ref*n_target/1e6)`，
     `stride=max(2, ceil(scale*2.0))`（Python 大整数乘法，C++ 用 int64
     乘——本核设计域 1e5 级采样距 int64 溢出 4 个数量级，乘积 ≤2^53 时与
     Python 精确一致）；
  3. stride>1 ⇒ 双侧 min-max 降采样后**再次 _normalized**（降采样重分布
     统计量）；索引数组保留；
  4. `window is not None and abs(d_n_ref-d_n_target) > window` ⇒
     `{+inf, [], []}`（#897：老回溯器穿 inf 伪造单调路径，现改为拒绝；
     判定发生在**降采样之后**）；
  5. DP：(d_n_ref+1)×(d_n_target+1) 全 inf，[0][0]=0；带外（`abs(i-j)>
     window`）跳格留 inf；带内 `cost = (d_ref[i-1]-d_target[j-1])**2 +
     min(上, 左, 斜)`；
  6. 回溯 (d_n_ref,d_n_target)→(0,0)：i>0 且 j>0 时**先 append(i-1,j-1)**
     再按 `min_val == 斜 ? 斜 : (== 上 ? 上 : 左)` 走——注意 else 分支涵盖
     “左最小或与 min_val 相等”；越界侧走边缘 append(另一侧 0)；
  7. 路径 reverse；stride>1 ⇒ 经索引数组映射回原始空间（严格递增 ⇒ 映射
     后仍单调）。
- 失败/并列/NaN：归一化保证 dist 非 NaN；inf 格参与 min 时值不变；
  平局由 `==` 精确比较 + elif 顺序决定（斜 > 上 > 左）——这是路径全等的
  唯一敏感点，靠位级一致的归一化保证。
- 与已有 C++ 核关系：全仓无 native DTW（libs/、native/、well-log-engine
  submodule f845e7ab 均无命中）→ 忠实移植，非包装。
- 测试缺口：Python 测试断言性质（cost≥0、路径等长、对角、界内），无数值
  冻结；窗口拒绝分支无 Python 单测 → oracle 全量冻结（约 22 match 案例）。

### DTWLogMatcher.transfer_top_index(ref_top_idx, path_ref, path_target)
- 输入：参考井顶界索引 + 对齐路径；输出目标井索引 int。
- 语义：任一路径空 ⇒ 原样返回 ref_top_idx（哨兵直通）；否则遍历
  `zip(path_ref, path_target)`（长度不等时按短者截断），`abs(r-ref_top_idx)`
  **严格小于**当前最优才更新 ⇒ 距离并列时保留**最先**出现的 t；初始
  best_idx=0。
- 与 match_curves 的关系：消费者把降采样映射后路径当作原空间路径使用
  （等长保证，zip 无实际截断场景）。
- 测试缺口：shift+5 案例（=35）与 E3 近净对齐（≤12）有测试；并列/空路径
  /ref 越界无测试 → oracle 补 6 案例。

## paleo_workbench/viz/stratigraphic_correlation_engine.py（203 行）
Fluent 编排器：`with_wells/with_datum/with_layout/with_dtw_config` 配置 →
`align_curves`（直通 DTWLogMatcher.match_curves，window 来自
`_dtw_window`）、`recommend_top`（转 FormationTopCorrelator，携带真实深度
轴 + #888 的 depth_step=None 语义）、`execute`（shifts+polygons+每对相邻井
alignment+每 top 推荐）。`_get_well_curve` 未命中 ⇒ 空数组（触发 DTW inf
哨兵，#405 UI 显示"不可用"）。纯编排无数值；本切片不移植，C++ 核以
match_curves/transfer_top_index 为界。测试：fluent 管线、哨兵、C40 置信度
归一（exp(-cost/(path_len*2))）。

## paleo_workbench/viz/formation_top_correlator.py（179 行）
DTW 的主要消费者：`compute_correlation_polygons`（顶界四边形，与 DTW 无关）
与 `recommend_top_depth`（#846/#888/#420 深度轴逻辑：升/降轴 median(diff)
判向、非单调回退 0.5 网格 + UserWarning、ref_idx 镜像、target_depths 回映；
置信度 = exp(-cost/(len(path)*2)) 截断 [0,1]，C40 用路径长度归一）。调用
`match_curves` + `transfer_top_index` 各一次。数值契约已被 oracle 间接触达
（transfer/alignment 部分）；深度轴映射属 M8 后续切片，不在本核。
测试：test_formation_top_correlator（多边形、float32 输入、置信度收敛、
420 降轴三例、非单调警告）。

## paleo_workbench/viz/well_log_api.py（31 行）
native_backend 门面：`HAS_CPP_WELL_LOG`、`fast_las_parse_data`（LAS 解析）、
`minmax_downsample`（渲染 LOD，与 DTW 无关）。本切片无关。

## paleo_workbench/viz/well_log_load.py（423 行）
LAS/XML 预览装载 + 双 LRU 缓存（preview 16 条 / full-res 2 条，(path,mtime)
键）+ `WellLogDecimationInfo`（#1193 采样诚实记录）+ `detect_depth_unit*`
（V6 §3 未知=一等状态）+ 协作取消（#1224）。证明：科学推理路径必须用
full-resolution 装载——DTW 输入若来自 100k 预览降采样即违反 #1193。无数值。

## paleo_workbench/viz/well_log_track_layout.py（172 行）
井道布局（每道 ≤3 曲线、合并/拆分、GR 保底可见）。纯 UI 结构，无关。

## paleo_workbench/viz/welllog_engine_adapter.py（821 行）
Workbench→WellLogEngine 单井文档适配：稳定 UUID（uuid5 命名空间）、
`_finite_pairs`（V6 §7 P0-1：有限深度 + NaN 值保留在轴上，gap-honest）、
深度单位信封（unknown→标 m 但 `depth_unit_declared=False`+诊断）、
submit/patch/append 增量决策树。无 DTW 数值；为 M8 接线提供契约词汇。

## paleo_workbench/viz/welllog_multi_well_adapter.py（558 行）
多井剖面→engine plan：重名井 slot 消歧、V8 M1 单位门（m/ft 混合拒绝未声明
井）、`_shift_for_well`（WellSectionDatum）、horizon_line/correlation_band
overlay（按深度排序防 bowtie）。无 DTW 数值。

## paleo_workbench/workflow/stratigraphy_correlation.py（163 行）
工程资源→井列表装载（跳过井不占 id 位，#404）、well_tops .dat 解析分组按
深度排序、大小写不敏感顶界匹配、tops→IntervalItem（末段继承前厚度，单顶
+10m）。无 DTW 数值。

## paleo_workbench/workflow/correlation_artifact.py（106 行）
相关解释产物 JSON 原子写（tmp+os.replace #939-3）、sha256 指纹。无 DTW。

## paleo_workbench/workflow/correlation_lifecycle.py（315 行）
draft→不可变版本→reopen 生命周期；指纹不变 no-op；失败补偿删产物（H7）。
无 DTW。

## paleo_workbench/workflow/correlation_overlay.py（243 行）
顶界 overlay 注入（FormationTopMarker 包装、H8 非 MD 域拒放、ft 白名单换算、
V6 P0-3 未知单位拒放、H9 替换式再应用）。无 DTW 数值。

## paleo_workbench/workflow/correlation_session.py（389 行）
画布行→FormationTop（稳定 id sha256[:16]、source=dtw→DTW_ASSISTED 方法保真
L4）、手动 link 增删改 + 邻接抑制、merge_session_links 合并规则。无 DTW
数值（仅记录"该顶由 DTW 辅助产生"这一溯源标签）。

## well-log-engine/（submodule，检出 f845e7ab）
浅初始化后 grep `dtw|dynamic time warp`（include/ src/）零命中 → 无可复用
native DTW；其 `propagate_pick_via_dtw`/`compute_dtw_propagation` 是 geoviz
(python) 侧 API，与本核不同层。结论：忠实移植而非包装（写入 decisions）。

## paleo_workbench/ui/pages/dtw_propagation_worker.py（136 行，§5 外补充）
`bounded_dtw_band(n, band_radius=None)`：`_MAX_DTW_CELLS=4_000_000`；
默认带 `max(20, n//4)`，cap `max(20,(cells//n -1)//2)`，min 收敛。与
`kMaxCostCells=1e6` 是两套预算（引擎带状 DTW vs 本核降采样）。C++ 本切片
不移植（引擎侧 seam），在 findings 记录防重复实现。

## tests/（10 文件全部全文阅读，断言→oracle 案例表）

- **test_dtw_log_matcher.py**：①100 点 sin + roll(5)：cost≥0、路径等长非空
  → match 案例 ShiftedSin100。②transfer shift=30→35。③E3 NaN（seed 11，
  400 点，ref[180:220]=NaN，tgt[100:130]=NaN，roll 40）：cost 有限、带洞
  transfer 与净曲线 transfer 差 ≤12 → 冻结两对齐全路径 + transfer 值。
  ④E8 20000 点 sin：cost 有限、索引界内、对角 |r-t|≤40、_MAX_COST_CELLS
  ==1e6 → match 案例 LongSin20k（触发 stride=40 降采样）。
- **test_issue1054_dtw_peak_preserving.py**：`_expected_stride` 镜像公式；
  4000 点薄层（1234 高尖、2600/2601 低尖）降采样后尖峰逐字存活、indices
  严格递增、≤2/bin；shifted spike δ=120 对齐误差 < stride；同曲线
  path_ref==path_target 逐元素相等（对角映射）；20000 点 <10s；短曲线恒等
  旁路 → downsample 单元 8 案例 + match 案例 ThinBed4000、IdenticalThinBed、
  SpikeShift4000。
- **test_dtw_propagation_worker.py**：bounded_dtw_band 边界（81→20、2000→
  500、50000 cap ≤40、显式 8→8）——C++ 不移植，记录；其余 Qt 线程测试不适用。
- **test_correlation_engine_depth_step.py**：#888 depth_step=None 用真实轴
  （0.1524m 10k 点）；显式 0.5 覆盖仍生效 → 消费层语义，冻结层不覆盖
  （formation_top_correlator 属后续切片）。
- **test_formation_top_correlator.py**：float32 输入曲线（上转 float64 路径
  → oracle 案例 Float32Pair）；置信度衰减（1000 vs 3000 全分辨率差 <0.05、
  相同曲线 >0.99）→ 消费层；#420 降轴三例 + 非单调警告 → 消费层。
- **test_stratigraphic_correlation_engine.py**：fluent 管线/未绑井哨兵
  （confidence==0、cost≥999）/C40 置信度 == exp(-cost/(len(path)*2))
  → 消费层；证明 5000 点对触发降采样（len(path)<n）。
- **test_stratigraphy_correlation.py / _tops.py / _ui.py /
  test_correlation_link_editing.py**：资源装载 id 对齐（#404）、.dat 解析、
  link 溯源（L4）、UI 工具栏——无 DTW 数值，不产生 oracle 案例。

## docs/adr/0003-multiwell-correlation-architecture.md（8 命中）
`FormationTopCorrelator` 集成 `DTWLogMatcher.transfer_top_index` 提供
置信度推荐是**既定架构决策**；C++ 核须保持这两个入口的语义面（代价、
路径、索引转移）以便后续接线。约束抄录：自动化对齐 + 交互拖拽共存。

## docs/development/scientific-interpretation-v6/00-baseline.md（14 命中）
DTW 相关缺陷登记：#888 fallback 网格伪造深度（P2/DTW fallback grid
fabrication, formation_top_correlator.py:132-135——部分已被 #420/#888 修复，
测试佐证）；C40 置信度归一化契约；#1193 预览降采样不得进科学推理（DTW
输入必须 full-resolution）。约束：C++ 核输入契约 = 归一化无关，但调用方
须喂全分辨率曲线。

## docs/development/scientific-interpretation-v6/01-well-contract.md
不变量 6「渲染降采样永不达科学计算」直接约束 DTW 核的输入来源（M8 接线
义务，非本核职责）；不变量 4「gap 不桥接」与 _normalized 的 NaN 插补是
两层不同策略（渲染保 gap vs 匹配插补），不得混淆。

## docs/development/scientific-interpretation-v6/02-null-unit-depth.md
null 三哨兵历史（-999.25/-999.0/-9000 阈值）→ DTW 的 NaN 来自装载层统一
转换；_normalized 对 NaN/±inf 一视同仁插补，与 NullPolicy 无耦合。深度
单位与 DTW 数值核无关（单位门在消费层）。

## 与已有 C++ 核的关系（汇总）
- libs/mapping_kernel：无 DTW；其 mean_of/population_var 为顺序求和 +
  容差对账，与本核"位级 pairwise + 精确 =="是**有意的不同精度策略**
  （interpolator 1e-12 容差不需要平局稳定；DTW 需要）。默认只读，本任务
  不触碰。
- well-log-engine、native/*：均无 DTW，无包装对象。
- 结论：新建 `libs/well_science`（dtw.hpp/dtw.cpp），Qt-free、依赖-free
  （JSON 仅测试用 Pwb::Domain）。
