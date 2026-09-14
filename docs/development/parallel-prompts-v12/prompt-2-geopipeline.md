# Prompt 2 — 编图计算核性能（V12-B）

> **用法**：把本文件全文作为 `/goal` 的输入交给 zcode。全自动，无需人工选择；
> 遇到歧义按「默认最佳」自行决策并记录。
> **本 Goal 是三个里数值风险最高的** —— 请把「先建黄金值基线」当作不可跳过的第一步。

---

## 0. 你的身份与目标

你是 **Paleo Workbench** 仓库的独立开发代理，在一个**全新 worktree 分支**上
完成一个完整的工程目标。

**Goal（一句话）**：把编图链路的计算核从「分钟级」拉回「秒级」——
克里金从 N=2000 需 27.6s 降到与 IDW 同阶；多边形化从 150×150 的 24.2s
（**超线性**）降到亚秒级；等值线从 300×300 的 6.0s 显著下降。
**科学语义必须保真**：任何近似都必须显式落进结果元数据并可被 UI 看到。

**预期规模**：约 10 亿 tokens 的开发量。这个方向的正确性验证成本远高于
写代码成本——请把大部分预算花在**黄金值基线 + 数值等价性证明**上。

---

## 1. 强制前置：环境与并发预算

### 1.1 工作目录

```bash
cd /c/Users/wangj.KEVIN/projects/paleo-workbench
git fetch origin main
git rev-parse origin/main      # BASE

git worktree add ../paleo-workbench-geopipeline-v12 \
    -b feat/geopipeline-v12 origin/main
cd ../paleo-workbench-geopipeline-v12
```

> ⚠️ 不要用 `git worktree prune`。收尾用 `git worktree remove <path>`。

### 1.2 环境

- Python **3.12**。在新 worktree 建自己的 venv：
  ```bash
  python -m venv .venv
  .venv/Scripts/python.exe -m pip install -e ".[dev]" -r requirements-geoviz.txt
  ```
- Shell 是 **Windows / GitBash**。本环境 coreutils 可能缺失
  （`dirname`/`cat`/`head`/`tail`/`ls` 可能 command not found）——
  用 Python 或专用工具代替。
- `numpy` / `scipy` 已在依赖里（`scipy` 提供 `cKDTree`，本 Goal 会用到）。

### 1.3 ⛔ 编译资源预算（硬约束）

- **本 Goal 不需要编译任何 C++**。不要碰 `native/`、`third_party/`。
- **本 Goal 不需要 QGIS 桥**。编图计算核是**纯 numpy/Python**。
- **禁止**跑 `tests/perf/` 全量、`-m slow`、3D/OpenGL 腿。
  本方向的性能验证**自己写独立脚本**，不要挂在重型套件上。
- 只跑你改动的模块相关测试文件。

### 1.4 ⛔ 并发预算（硬约束）

**最多同时启用 2 个 subagents。** 单条消息里最多 2 个 `Agent` 调用。

推荐分工：

| 阶段 | subagent A | subagent B |
|---|---|---|
| 侦察 | 读 `interpolator.py` 数值路径 | 读 `polygonization.py` / `contouring.py` |
| 基线 | 造黄金值数据 + 跑现状 | 复核 vendored 引擎的对应实现 |
| 实现 | 改克里金 | 改多边形化 |
| 评审 | Standards 轴 | Spec 轴 |

> 需要第 3 个视角时**串行**执行，不要并行开第 3 个。

### 1.5 ⛔ 无 CI

**不依赖任何 CI**。不要 `gh pr checks --watch`。本地验证完即止。

---

## 2. 可用的 skills（按需加载）

1. **`wayfinder`** — 用来把"哪条实现是权威"这个**架构决策**变成 ticket
   并当场解决（见 §3.4，这是本 Goal 最关键的前置决策）。
2. **`planning-with-files`** — **强制**在 worktree 内维护：
   - `docs/development/geopipeline-v12/00-decisions.md`
   - `docs/development/geopipeline-v12/01-golden-baseline.md` ← **最重要**
   - `docs/development/geopipeline-v12/02-design.md`
   - `docs/development/geopipeline-v12/03-verification.md`
   - `docs/development/geopipeline-v12/04-known-limitations.md`
3. **`implement`**、**`code-review`**（双轴并行 2 subagent）、**`gstack` `/ship`**。
4. **`diagnosing-bugs`** — 数值不一致时用它系统排查。
5. **`domain-modeling`** / **`ubiquitous-language`** — 处理"近似/降级"语义时
   确保术语与 `CONTEXT.md` 一致。
6. **`grilling`** — **仅在** §3.4 的架构决策上对自己用（自问自答，
   把结论写进 00-decisions.md）。

`CLAUDE.md` 强制的 Karpathy guidelines 全程有效。

---

## 3. 待解决的问题（侦察结论，需你自行复核行号）

> 基线 `926f3335` 的实测数据。**行号可能已漂移，必须自己重读确认。**

### 3.1 克里金是 IDW 的 583 倍（实测量化）

实测环境：`.venv`（cp312），网格 100×100，随机样本：

```
N= 200  IDW=1.702s  Kriging=  8.272s  ratio=   4.9x
N= 500  IDW=0.034s  Kriging=  9.579s  ratio= 281.1x
N=1000  IDW=0.048s  Kriging= 21.375s  ratio= 443.5x
N=2000  IDW=0.047s  Kriging= 27.618s  ratio= 583.2x
```

（注：IDW 在 N=200 的 1.702s 是首次调用的建树/预热成本，之后趋于 0.05s。）

**根因**，`mapping/geological_pipeline/interpolator.py`：

- `_fit_variogram_numpy`（约 `:424-471`）：在**样本两两距离矩阵**上做
  4 轮 × 12 range × 6 nugget 的网格搜索。约 `:433`
  `np.triu_indices_from(dists, k=1)` —— O(N²) 内存 + O(N²) 时间，常数 ×288。
- `_pure_numpy_kriging`（约 `:473+`）：约 `:544` `K = np.zeros((n+1, n+1))`
  又一个 N² 稠密矩阵；约 `:571-590` 对**每个网格点分块**调
  `np.linalg.solve(K, rhs_matrix)`。

**关键发现（最省力的高收益点）**：
`InterpolationOptions`（`mapping/geological_pipeline/models.py`）**已经声明**了
`max_neighbors` / `search_radius` / `min_neighbors` 三个字段，且
**IDW 真的在用**（`interpolator.py` 约 `:165-308` 全在 IDW 路径内）。
**克里金完全不读这三个字段** —— 能力已声明、参数已存在、就是不接线。

**同模块的 `IDWInterpolator` 已经很现代**：约 `:231` 用
`scipy.spatial.cKDTree` + 分块查询（约 `:241` 按 `chunk_len` 切），
约 `:132-141` 有明确的邻域设计文档。**这是可以照抄的成熟范式。**

`pipeline.py:119` 默认插值器是 `KrigingInterpolator()`，所以**默认路径
就踩在最贵的实现上**。

### 3.2 多边形化是超线性的（最严重）

`mapping/geological_pipeline/polygonization.py`，约 `:230-246`：

```python
for hole in holes:                                  # :230
    for g_idx, pg in enumerate(poly_groups):        # :238
        votes = sum(1 for pt in hole[:-1]            # :239-243
                    if _point_in_ring(pt[0], pt[1], pg["exterior"]))
```

**每个洞 × 每条外环 × 洞的每个顶点** ——
O(holes × exteriors × ring_vertices)。而 `_point_in_ring`（约 `:62`）
本身还是逐边 Python 循环（射线法）。

实测证实超线性：

```
   50x50:  0.251s  loops=130
  100x100: 3.179s  loops=490
  150x150: 24.185s loops=840      ← 面积 ×2.25，耗时 ×7.6
```

150×150 是**常规操作就踩到**的默认网格尺寸。

### 3.3 等值线是纯 Python 双层循环

`mapping/geological_pipeline/contouring.py`：

- `_marching_squares_pure_python`（约 `:221`）：约 `:237` `for i in range(h-1)`
  套 `:239` `for j in range(w-1)` —— **每个网格单元一次 Python 迭代**，
  逐格 `float()` 转换、`math.isfinite` 四次、16 分支 case 判断。
  实测 **16-20 µs/cell**。
- 约 `:381` `for idx, level in enumerate(levels)` —— **每个 level 重扫全网格**。
- 约 `:397-408` 再对每条折线做 clip + `calculate_polyline_length`
  （约 `:59-66` 又是逐点 Python 循环）。

实测：

```
单层：
  100x100: 0.164s  cells=9,801   16.78 us/cell
  200x200: 0.725s  cells=39,601  18.32 us/cell
  300x300: 1.801s  cells=89,401  20.14 us/cell

完整层（默认 5 个 level）：
  100x100: 0.515s  features=5,051
  200x200: 2.272s  features=19,989
  300x300: 6.035s  features=44,103
```

### 3.4 ⚠️ 架构决策：等值线存在两套并行实现（**先解决这个**）

这是侦察中最重要的发现，它**决定本 Goal 的范围**：

1. `mapping/geological_pipeline/contouring.py`（445 行，纯 Python，
   就是 §3.3 那个）
2. `paleo_workbench/_vendored/haiyou_constrained_idw/drawing/single_factor/`
   `constrained_engine.py`（**8,827 行**，自带一整套等值线体系）：
   `masked_marching_squares`（约 `:8554`）、`connect_segments`（约 `:8683`）、
   `postprocess_contours`（约 `:5966`）、`cartographic_smooth_contours`
   （约 `:3555`）、`guarantee_no_contour_crossings`（约 `:2673`）、
   `interrupt_contours_at_barriers`（约 `:2934`）、
   `prepare_contour_extraction_surface`（约 `:4831`）等 30+ 个函数。

`workflow/constrained_idw_adapter.py`（约 `:607-624`）显示**入册路径走第 2 套**：
`extract_contours=True`，返回 dict 里直接带 `"contours"`（约 `:705-713`）。
即**约束 IDW 路径的等值线由 vendored 引擎产出，不经过
`geological_pipeline/contouring.py`**；而 `build_factor_map_document`
走第 1 套。

**这是你必须先做的决策（用 wayfinder 把它变成 ticket 并当场解决）**：

- **选项 A（保守，推荐）**：**本 Goal 只优化 `polygonization.py` 与
  `interpolator.py`**，等值线先不动。理由：`polygonization` 的超线性是纯
  性能问题、无架构争议、收益巨大（24s → 亚秒）；克里金接线零 schema 变更。
  等值线统一化是**独立的架构任务**，应另开一轮。
- **选项 B（激进）**：统一到 vendored 引擎，退役
  `geological_pipeline/contouring.py`。**风险高**：涉及双路径语义对齐、
  改 `_vendored/`（第三方代码，带 `ATTRIBUTION.md` 的上游同步成本），
  且会改变图形输出。

**默认按选项 A**。把决策理由写进 `00-decisions.md`。
如果你判断证据强烈指向 B，可以选 B，但**必须**在文档里论证，
并把「语义可能变化」写进已知限制。

---

## 4. 交付要求

### 4.1 不可跳过的第一步：黄金值基线

在改任何代码之前：

1. 构造**确定性的**测试数据集（固定随机种子），覆盖：
   - 小/中/大样本（如 N=50 / 500 / 2000）
   - 小/中/大网格（如 50² / 200² / 300²）
   - 含/不含边界多边形（`InterpolationOptions.boundary`）
   - 含/不含各向异性（`anisotropy_angle` / `anisotropy_ratio`）
   - IDW 与 Kriging 两条路径
   - 含 nodata 的情况
2. 用**当前代码**跑出输出，存进 `tests/data/geopipeline_golden/`
   （或等价位置）作为黄金值。
3. 记录**当前**墙钟耗时，写进 `01-golden-baseline.md`。

**没有黄金值，不许开始改数值代码。** 这是硬要求。

### 4.2 必须达成的可验证目标

1. **克里金**：接线 `max_neighbors` / `search_radius`（字段已存在，
   **零 schema 变更**）。预期 N=2000 / 100² 从 27.6s 量级进入秒级。
   - 若要实现"局部邻域克里金"（moving neighborhood），**必须**把
     k 与搜索半径写进结果元数据，保证可复现。
2. **多边形化**：洞归属的暴力三重循环换成**空间索引**
   （外环 bbox 预筛 + `scipy.spatial.cKDTree` 或 STRtree）。
   预期 150×150 从 24.2s 到亚秒级。
3. **等值线**：按 §3.4 的决策执行（选项 A 则本项延后并记录）。
4. **数值保真**：
   - 与黄金值的差异必须**在容差内**（**不要逐位相等**——任何数值路径
     改变都会动尾数）。容差要**明确写出来并论证**。
   - **任何近似/降级必须落进 `grid_result.metadata`**，
     并能在 Inspector 里被看到。沿用本仓既有的"诚实降级"惯例
     （参照 `mapping/tool_availability.py` 的 `provider_writable_approximate`
     先例——声明 + 判词标注"近似"）。
5. **新增复杂度回归钉**：把「多边形化在大网格上不超线性」做成结构性断言。
   **必须含反向对照**（人为退回暴力实现，断言必须变红），证明不是空断言。

### 4.3 护栏与风险

- ⚠️ **本仓有 tautological assertion 守卫**
  （`test_no_tautological_assertions`，见 #1266/#1028）。
  **不要写 `assert True` / `or True`**。
- ⚠️ **敏感测试文件，改动前先完整读一遍**：
  - `tests/test_interpolation_evaluation.py`
  - `tests/test_factor_v8_duplication_cv_parity.py`（交叉验证一致性）
  - `tests/test_contour_draft.py`
  - `tests/test_facies_legend.py`
  这些是交叉验证/黄金值性质的测试，动数值极易误伤。
- 不要改 `_vendored/`（除非 §3.4 选了 B，且那时要论证）。
- 不要引入新的重型依赖（`scipy` 已有；不要加 `pykrige` 之类）。
- **不要**改 `InterpolationOptions` 的字段名或默认值——
  那会破坏序列化兼容。

### 4.4 边界（明确不做）

- 不碰 UI/Qt/QGIS 渲染（那是另一个 Goal）。
- 不碰 `catalog/`。
- 不做 `_vendored/haiyou_constrained_idw/constrained_engine.py` 的整体优化
  （它是最大的未知量，单独一轮）——除非 §3.4 选了 B 且只碰等值线部分。
- 不追求 GPU / 多进程；本 Goal 是**算法与数据结构**优化。

---

## 5. 执行流程（全自动，不要停）

```
1. 建 worktree + venv（§1）
2. 读 CLAUDE.md / CONTEXT.md / karpathy-guidelines / 三个敏感测试文件
3. ★ 建黄金值基线（§4.1）—— 不可跳过
4. wayfinder：解决 §3.4 的架构决策，写进 00-decisions.md
5. 克里金接线（收益最大、风险最小，先做）→ commit
6. 多边形化空间索引 → commit
7. （可选）等值线向量化 → commit
8. 写复杂度回归钉 + 反向对照 → commit
9. 自测：只跑相关测试文件
10. code-review（并行 2 subagent）→ 修 P0/P1
11. 更新 03-verification.md：before/after + 容差论证 + 测试证据
12. 提交 PR
```

### 5.1 提交规范

- 每个逻辑变更一个 atomic commit：
  `perf(geopipeline): 接线克里金邻域参数 (#<issue>)`、
  `perf(geopipeline): 多边形化洞归属改用空间索引`。
- 不要 `[skip ci]`。

### 5.2 PR 规范

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"
"$GH" pr create --base main --head feat/geopipeline-v12 \
  --title "perf(geopipeline): 编图计算核提速（V12-B）" \
  --body "<见下>"
```

PR body 必须包含：
- **Base SHA**
- **before/after 实测表**（克里金 / 多边形化 / 等值线，逐尺度过列）
- **数值保真论证**：容差是多少、为什么这个容差可接受、
  黄金值比对结果
- **近似披露**：哪些是近似、在哪里可见
- **测试证据**：跑了哪些文件、多少 passed/skipped
- **`## Known limitations`**：含 §3.4 未做的部分
- **明确声明**：本 Goal 不涉及 C++/QGIS 构建

---

## 6. 完成定义（Definition of Done）

- [ ] worktree 分支 `feat/geopipeline-v12` + PR 已提交
- [ ] `docs/development/geopipeline-v12/` 五份文档齐全
- [ ] **黄金值基线存在且被 commit**
- [ ] 克里金邻域参数已接线，实测数字达标
- [ ] 多边形化超线性已消除，实测数字达标
- [ ] 数值差异在**明文论证过的容差**内
- [ ] 近似/降级已落进 metadata 且 UI 可见（或明确记录为何不可见）
- [ ] 复杂度回归钉含反向对照，**tautological 守卫通过**
- [ ] code-review 双轴已出，P0/P1 清零
- [ ] 全程 subagent 并发 ≤2（有记录）

---

## 7. 完成后回报

给出：BASE SHA、分支、PR URL、**before/after 数字表**、容差论证、
测试摘要、P0/P1 处理、以及后续需要单独一轮的事。
数值上任何"我没能完全验证"的地方，**必须明说**，不要含糊过去。
