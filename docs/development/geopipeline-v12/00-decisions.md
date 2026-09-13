# V12-B 决策记录（geopipeline 计算核提速）

| # | 决策 | 日期 | 状态 |
|---|---|---|---|
| D1 | 等值线双实现：本轮选 **选项 A**（不动 `contouring.py`） | 2026-09-13 | 已采纳 |
| D2 | 克里金邻域路径：`_pure_numpy_kriging` 内新增 moving-neighborhood 求值器，opt-in；默认路径零改动 | 2026-09-13 | 已采纳 |
| D3 | 邻域参数触发时**始终走 numpy 路径**（即使 geoviz 可用） | 2026-09-13 | 已采纳 |
| D4 | 多边形化洞归属：bbox 保守预筛 + 向量化 point-in-ring，输出必须逐字节复现 | 2026-09-13 | 已采纳 |
| D5 | 黄金值比对策略：默认路径字节级一致；克里金网格容差 1e-5（BLAS 内核噪声论证） | 2026-09-13 | 已采纳 |

## D1：等值线双实现 —— 选项 A

**问题**（Prompt §3.4）：等值线存在两套（实为三套）并行实现：

1. `paleo_workbench/mapping/geological_pipeline/contouring.py`（445 行，纯 Python
   marching squares）—— `build_factor_map_document` 路径使用；
2. `_vendored/haiyou_constrained_idw/.../constrained_engine.py`（8,826 行）内嵌的
   等值线管线 —— 约束 IDW 入册路径使用（`constrained_idw_adapter.py:612`
   `extract_contours=True`，结果以 `"contours"` 键随 `FactorGridResult` 返回）；
3. `geoviz` 门面的 `extract_contour_lines`（`workflow/contour_draft.py:209`）——
   draft 无存储引擎等值线时的回退提取器。

**自问自答（grilling）**：

- *Q: 统一到 vendored 引擎是否可行？* A: 不可行（本轮）。引擎等值线管线内嵌在
  `generate_constrained_idw`（:582）里，需要 wells/boundaries/barriers 输入，
  **无法对任意 grid 独立调用**；把它抽成通用等值线服务等于重写引擎入口，
  且 ATTRIBUTION.md 定位该目录为 SHApinned 的 vendored 依赖。
- *Q: 统一到 geoviz 门面是否更好？* A: 生产环境 geoviz 可用，但本仓测试矩阵
  必须在无 geoviz 环境下可跑（当前 worktree 即无 geoviz）；且 `contouring.py`
  被 9 个测试文件直接锚定，其中两个直接断言 `_marching_squares_pure_python`
  的鞍点 case 行为（test_challenger_m6 :710-722、test_m3_adversarial_contour_polygon
  :245-259）。
- *Q: 两套实现会同时服务同一工件吗？* A: 不会。引擎等值线只存在于约束 IDW
  结果；默认 Kriging/IDW 路径没有引擎等值线可用。用户可见分叉限于"同一格网
  走约束 IDW draft 视图 vs 走 mapping 图层"的线形差异——这是既有状态，不是
  本轮引入的。

**结论**：选项 A。本轮只优化 `interpolator.py` 与 `polygonization.py`。
等值线统一化（含三套实现收敛、nice-levels 双份算法合并）另开一轮，已在
04-known-limitations.md 登记。等值线的黄金值基线（contour_smooth_100/200/300）
**本轮已建立**，下一轮直接可用。

## D2：克里金 moving neighborhood 是新增路径，不是改写

`InterpolationOptions.max_neighbors / search_radius / min_neighbors` 已声明且
IDW 已消费；克里金回退路径完全不读。本轮在 `_pure_numpy_kriging` 内新增
邻域求值器：

- **两个参数均为 None（默认）→ 走既有全局路径，一行不改**。这保证
  `test_kriging_fallback_quality.py` 的全部契约（常量场短路、样本点精确
  插值、`_KRIGE_TARGET_CHUNK` 分块平价、R²>0.7）与黄金值基线不受扰动。
- 任一参数设置 → cKDTree 查询 k 近邻（含可选半径剪枝），逐目标构建小型
  (k+1)² 增广 OK 系统，**按目标分批 `np.linalg.solve`（batched 维度）**，
  不需要按邻域签名分组。剪枝掉的邻居以"零权重恒等行"从系统中精确消去
  （不是数值近似）。
- 常量场短路保留在邻域选择**之前**（零方差输入的既有语义）。

## D3：邻域参数触发时始终走 numpy 路径

geoviz 的 `kriging_grid` 不接受邻域参数；若 geoviz 可用且用户设置了邻域参数，
静默走全局引擎等于无视用户参数，**把参数选择变成谎言**。因此：邻域参数设置
时一律走 numpy 路径（含 numpy 变差函数拟合），并在 `algorithm_parameters`
中披露 `neighborhood` 块 + `variogram_fit`。代价：geoviz 环境下邻域克里金
不用引擎的 WLS 拟合——这是显式降级，按本仓"诚实降级"惯例标注（参照
`mapping/tool_availability.py` 的 `provider_writable_approximate` 先例：
声明 + 判词可见）。

## D4：多边形化洞归属 —— 精确超集预筛 + 逐字节复现

现状 O(holes × exteriors × hole_vertices × ring_edges) 超线性。改为：

1. 每个外环预算 bbox；候选 = bbox 包含洞 bbox 的外环（**精确超集**：点集
   包含 ⇒ bbox 包含，无假阴性）。
2. 候选仍按面积升序、严格 `votes > best_votes` —— 选择规则与现状逐位相同。
3. 顶点投票改用与 `point_in_ring_scalar` **同表达式**的向量化射线法
   （`geometry_planar.points_in_ring_vectorized`，见 D4a），浮点运算次序
   一致 ⇒ 布尔结果一致 ⇒ 归属一致 ⇒ 输出几何逐字节复现（黄金值
   poly_* 案例为证）。

**D4a**：向量化内核放进 `geometry_planar.py`（与既有 scalar/vectorized
几何内核同址），`polygonization._point_in_ring` 的调用点不改公开面。

## D5：黄金值容差论证

- IDW / 多边形 / 等值线 / 克里金参数标量：**字节级一致**。这些路径是
  纯 Python 或确定性逐元素 numpy，无线程化归约。
- 克里金网格（z/variance）：实测线程化 OpenBLAS（scipy-openblas 0.19，
  pip wheel）在大矩阵上按缓冲区对齐选择内核，同一代码两次运行末位比特
  可差 ~1e-7（float32 存储；见 01-golden-baseline.md 的复现记录）。容差
  **max|Δ| ≤ 1e-5**：值域 O(1..100)（黄金值场 5–15），1e-5 是观测噪声
  (~9.5e-7) 的 ~10 倍余量、又远小于任何真实语义改动（邻域/求解路径变化
  的典型量级 ≥ 1e-3）。NaN 模式必须一致（cell 数相等）。
- 统计摘要：rtol 1e-6（同源噪声）。

## 环境适配记录（Linux 适配，偏离 Prompt 原文的 Windows 假设）

- 仓库实际位于 `/home/kevin/projects/paleo_project`（bare + worktree 布局），
  本轮 worktree：`/home/kevin/projects/paleo_project/geopipeline-v12`。
- Python 3.12.13（uv 管理的 CPython）；`-r requirements-geoviz.txt` 因
  geo-viz-engine 子模块未检出而不可安装——与本轮目标一致（不编译引擎，
  克里金走纯 numpy 回退路径，即侦察实测的路径）。
- 侦察的 27.6s/24.2s/6.0s 来自较慢机器；本机同结构问题为 1.0s/3.0s/0.6s
  （多边形化超线性、克里金全局 O(N³)+O(M·N²) 的**算法结构**不变）。
  before/after 以本机同机对比为准。
