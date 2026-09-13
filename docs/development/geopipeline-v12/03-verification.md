# V12-B 验证报告（before/after + 容差论证 + 测试证据）

**BASE**：`926f3335` · **环境**：见 01-golden-baseline.md（同机同 venv 前后对比；
侦察机的 27.6s/24.2s/6.0s 为另一台更慢机器的实测，机器常数 ≈ 本机 2.4–9×，
算法结构结论一致——本 Goal 的结构性修复以同机对比为准）。

## 1. before/after 实测表

### 1.1 克里金（纯 numpy 回退路径 = 默认路径，无 geoviz 环境）

N=2000 样本 / 100² 网格，固定种子（ warmed，`_pure_numpy_kriging` 直测）：

| 配置 | before | after | 倍数 |
|---|---|---|---|
| 全局（默认，两邻域参数均未设置） | 3.24–3.83s | **不变**（字节级一致） | 1× |
| moving k=16（min_n=4） | — | 0.330s | vs 全局 ~10× |
| moving k=32（min_n=8） | — | 0.655s | vs 全局 ~5.5× |
| moving k=64 | — | 1.638s | vs 全局 ~2.2× |
| moving k=32 + 半径 60（0.9% 目标 nodata） | — | 0.627s | — |
| 参照：IDW（同规模） | 0.061s | 0.061s | — |

侦察机等效推算：全局 27.6s ↔ 本机 ~3.3s（机器系数 ≈8×）→ k=32 在侦察机
量级 ≈ 5s、k=16 ≈ 2.6s，从「半分钟」进入「秒级」；与 IDW 同阶（O(M·k) 级
邻域工作 + 共享的 O(N²) 变差函数预处理），但常数天然大于 IDW（每目标解
(k+1)² 系统vs 加权平均）——这是克里金语义的固有成本，不是实现低效。

### 1.2 多边形化（speckle 噪声 = 洞/外环最坏场）

`_polygonize_raster_boundaries`（单类二值，直测）：

| 网格 | before | after | 面积比 | 耗时比(after) | 耗时比(before) |
|---|---|---|---|---|---|
| 50² | 0.168s | 0.056s | — | — | — |
| 100² | 2.350s | 0.266s | ×4 | 4.7 | **14.0** |
| 150² | 9.982s | 0.590s | ×2.25 | 2.2 | **4.2** |
| 200² | — | 1.069s | ×1.78 | 1.8 | — |

**超线性已消除**（before 的 4.2–14× 面积比对 → after 的 1.8–4.7，逼近线性；
残余超线性来自环长随网格增长，属 O(cells + Σring_len) 的正常部分）。

`generate_facies_polygon_layer`（三分类完整层路径，黄金值案例）：

| 案例 | before | after |
|---|---|---|
| poly_speckle_50 | 0.370s | 0.165s |
| poly_speckle_100 | 1.541s | 0.496s |
| poly_speckle_150 | **2.979s** | **0.941s（亚秒）** |
| poly_smooth_300 | 0.080s | 0.073s |

层路径的加速来自两处：洞归属（本 Goal 主项）+ `crs_is_geographic`
lru_cache（pyproj 缺失时每层上万次失败 import 重扫 ≈2s）。

m6 对抗门禁（手工复现，本环境无法收集 m6，见 §4）：棋盘 50² 0.358s
（门禁 <3.0s）、噪声二值 100² 0.443s（门禁 <15.0s），全部 shapely valid。

### 1.3 等值线（D1 选项 A：本轮不动）

| 案例 | before | after |
|---|---|---|
| contour_smooth_100/200/300 | 0.088/0.218/0.626s | 不变（0.083/0.205/0.539s，抖动） |

## 2. 数值保真论证

### 2.1 默认路径：字节级一致（黄金值 25 案例）

- IDW / 多边形 / 等值线 / 克里金参数标量：**逐字节相同**。
- 克里金网格：两次全量比对中除一个案例逐字节相同外，仅 krig_n500_g300
  出现 max|Δ|=9.5e-07，来源是线程化 BLAS 按缓冲区对齐选择内核（同代码
  同输入、不同进程历史 → 末位归约次序不同；复现记录见 01 §BLAS）。
- **容差**：克里金网格 max|Δ| ≤ 1e-5。论证：黄金值场值域 5–15，1e-5 ≈
  值域的 1e-6 相对量、观测噪声 (~9.5e-7) 的 ~10 倍余量；任何真实的语义
  改动（邻域集、求解路径、变差函数参数）的典型影响 ≥ 1e-3，比容差大
  两个数量级——容差分辨得出语义变化，又不会被平台噪声误触。NaN 模式
  （cell 数）必须一致，不接受容差。
- 摘要统计 rtol 1e-6（同源噪声）。

### 2.2 新增邻域路径（无黄金值前体，用结构断言钉）

- **k=n 等价**：k 设为样本总数且 ≤ 上限时，逐目标系统 = 全局系统，
  结果 allclose 1e-9（不同 LAPACK 布局的末位差异）。
- **样本点精确插值**：OK 无偏性质，k=12 下 20 个样本点估值 max|Δ|=1.8e-14
  （测试断言 1e-4）。
- **半径剪枝 = 精确消去**：被剪邻居行列清零、权重钉 0，拉格朗日行只约束
  保留权重（不是数值衰减）；邻居数 < min_neighbors 的目标为 NaN（与 IDW
  契约一致）。
- **确定性**：同进程重复运行逐字节相同。
- **方差**：全网格 ≥ 0；样本处方差 < 全场最大。

### 2.3 多边形化：语义不变 = 输出逐字节一致

预筛是**可证超集**（洞 bbox 与外环 bbox 不相交 ⇒ 无顶点可命中 ⇒ 不丢票）；
投票谓词逐位等价（同表达式同浮点次序）；选择规则逐字未动。黄金值
poly_* 五案例（含 150² speckle、300² smooth）canonical JSON 逐字节一致。

## 3. 近似披露（metadata 可见性）

| 近似 | 落点 | 可见性 |
|---|---|---|
| 邻域克里金（局部 kNN 系统） | `algorithm_parameters.neighborhood`（k、请求 k、半径、min_n、capped、note） | Inspector/QA 读 algorithm_parameters 即见；本仓 Inspector 消费该 dict |
| 邻域路径非引擎等价 | `degraded=True` + `degraded_reason`（写明 geoviz 无邻域参数、grid-OLS 拟合、无引擎 LOO） | 下游 QA/publish 门禁读这些键（V8 M1 既有惯例） |
| k 上限截断（>256） | `neighborhood.capped=True` + `cap` + `note` | 同上 |
| 常量场 + 邻域 | `neighborhood.note="constant field: ..."` | 同上 |
| IDW/克里金半径 nodata | NaN cell（既有语义）+ neighborhood.min_neighbors 记录 | 网格统计 valid_count 反映 |

未做 UI 改动（§4.4 边界）；metadata 键已按既有 Inspector 消费路径
（`FactorGridResult.to_descriptor().algorithm_parameters`）落盘。

## 4. 测试证据（本 worktree venv，无 geoviz 引擎）

| 文件 | 结果 |
|---|---|
| tests/test_kriging_neighborhood.py（新增，13 用例） | 13 passed |
| tests/test_kriging_fallback_quality.py（#1036 专项） | 10 passed |
| tests/test_polygonization_complexity_nail.py（新增，含反向对照） | 2 passed |
| tests/test_polygon_quality_adversarial.py | 14 passed |
| tests/test_m3_adversarial_contour_polygon.py | 14 passed |
| tests/test_m3_stress_topological_remediation.py | 4 passed |
| tests/test_m3_adversarial_stress.py | 19 passed |
| tests/test_geological_mapping_pipeline.py | 57 passed, 2 failed（**预存**：stash 验证基线同样失败；等值线分位/定间隔两例，环境相关） |
| 黄金值 compare（25 案例） | 全部 OK（§2.1） |
| tautology 守卫（test_no_tautological_assertions） | 守卫文件本身在本环境无法收集（需 geoviz_plots→matplotlib）；**复刻其 AST 扫描**于两个新测试文件 → CLEAN |

无法在本环境运行的文件（与改动无关的预存环境限制，均经 stash 对照确认）：
tests/test_challenger_m6_adversarial_stress.py（收集需 pyqtgraph/OpenGL——
3D/OpenGL 腿为 §1.3 禁装；其两个多边形墙钟门禁已手工复现并通过）、
tests/test_crs_distance_policy.py、tests/test_interpolation_evaluation.py、
tests/test_factor_v8_duplication_cv_parity.py、tests/test_contour_draft.py
（收集需 geoviz_plots）。这四个敏感文件全部走 geoviz 引擎路径，本 Goal
对引擎路径零改动（邻域参数仅在 opt-in 时改道 numpy，见 D3）。

环境敏感性事件记录：为尝试收集 m6 安装的 matplotlib 使 editable 指向的
geoviz_plots 可导入 → 克里金默认路径翻转成引擎路径 → 黄金值比对 9 案例
FAIL（max|Δ|~1）。处置：卸载偏离规格的包 + 黄金值脚本显式钉死回退路径
（`sys.modules.setdefault("geoviz", None)`）后全绿。此事件正是
"先建黄金值基线"的价值证明：环境漂移被字节级闸门当场捕获。

## 5. 复杂度回归钉

tests/test_polygonization_complexity_nail.py：

- 正向：面积 ×4（60²→120² speckle）耗时比 < 8.0（线性 ≈ 4.2）。
- 反向对照：monkeypatch 回暴力实现（V12-B 前的逐洞×逐外环×逐顶点标量
  射线法）后同一比值实测 ≈ 12 → 断言其**必须 ≥ 8**（若不超阈即钉失效，
  测试自身会红）；同时断言暴力输出与真实现完全相同（同样语义、更差
  复杂度），排除假阳性对照。
- 校准（本机 2026-09-13）：fast 4.17 / brute 12.12，阈值 8.0 两侧各 ~1.9×
  余量；每尺寸取 min-of-2 抑制调度噪声。
