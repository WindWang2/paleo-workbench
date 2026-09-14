# 三个可并行开发优化方向 — 古地理编图工作台

基线：`main` @ `926f3335`（本地已 ff 到远端；V10 修复 #1267、#1277 已合并；
V11 三条线 data-fabric-v11 #1288 / qgis-cartography-runtime-v11 #1290 /
workbench-ux-v11 #1289 已全部合并）

方法：全仓静态走查（读到具体行号）+ **本机实测**（项目 `.venv`，cp312）。
每条结论都做了"V11 是否已覆盖"的排除性核对。

**实测环境**：Windows / GitBash / `.venv`（uv cpython-3.12）。
计时为单次运行，未做统计重复；量级用于定序，不用于验收。

---

## 结论速览

| # | 方向 | 主战场 | 实测最痛点 | 并行性理由 |
|---|---|---|---|---|
| 1 | **导入/入库 I/O 流水线** | `catalog/{storage,adapter,lifecycle}.py`、`resources/` | 单次受管 RAW 导入 = **完整读 3 遍 + 写 2 遍**；去重命中读 4 遍 | 纯存储层，不碰 Qt/QGIS/编图数学 |
| 2 | **编图计算核** | `mapping/geological_pipeline/`（+ 决策：`_vendored/haiyou_constrained_idw/`） | 克里金 100×100 网格 **N=2000 需 27.6s**，同条件 IDW 0.047s（**583×**）；等值线 300×300 **6.0s**；多边形化 150×150 **24.2s 且超线性**。**且等值线存在两套并行实现** | 纯 numpy 数值层，零 UI、零 catalog |
| 3 | **渲染/镜像增量通道** | `mapping/{map_render_backend,qgis_mirror,topology}.py` | 每帧全幅 RGBA `.copy()`；`_PreparedLayer` 无缓存；拓扑校验逐要素串行过桥 | 渲染层，与 1/2 文件零交集 |

### 实测数据（原始输出）

```
=== marching squares，单层（纯 Python）===
  100x100: 0.164s  cells=9,801   16.78 us/cell  segs=528
  200x200: 0.725s  cells=39,601  18.32 us/cell  segs=1922
  300x300: 1.801s  cells=89,401  20.14 us/cell  segs=4043

=== 完整等值线层（默认 5 个 level）===
  100x100: 0.515s  features=5,051
  200x200: 2.272s  features=19,989
  300x300: 6.035s  features=44,103

=== IDW(cKDTree) vs Kriging(dense)，网格 100x100 ===
  N= 200  IDW=1.702s  Kriging=  8.272s  ratio=   4.9x
  N= 500  IDW=0.034s  Kriging=  9.579s  ratio= 281.1x
  N=1000  IDW=0.048s  Kriging= 21.375s  ratio= 443.5x
  N=2000  IDW=0.047s  Kriging= 27.618s  ratio= 583.2x

=== 多边形化单类边界 ===
   50x50:  0.251s  loops=130
  100x100: 3.179s  loops=490
  150x150: 24.185s  loops=840      ← 面积 ×2.25，耗时 ×7.6（超线性）
```

---

## 方向一：导入/入库 I/O 流水线 — 消除重复读盘

### 问题证据

一次受管 RAW 导入，字节被**完整读 3 遍、完整写 2 遍**：

| 遍 | 位置 | 做什么 |
|---|---|---|
| 读 1 | `catalog/adapter.py:266` | `sha256_file_or_none(resolved_path)` — 先算摘要 |
| 读 2 | `catalog/storage.py:445-449` | `place_managed_file` 边读边算摘要边写临时文件 |
| 写 1 | 同上 `:452` | `os.replace` 落盘为受管 payload |
| 读 3 | `catalog/storage.py:166` | `place_blob` → `_place_blob_bytes` **再读一遍刚落盘的 target** |
| 写 2 | 同上 `:167-171` | 写入 `blobs/xx/<digest>` |

**去重快路径更糟**：`catalog/storage.py:416-431`，当 `known_sha256` 命中已有
blob 时，为"证明源文件内容确实等于该摘要"又调一次 `_digest_of(source)`
（`:419`）——**第 4 遍全量读**，然后才 O(1) 免拷贝。

第 3 遍是**纯可省**的：`place_managed_file:441-452` 手上已有打开的 `fd` 和
累积好的 `digest`，`_place_blob_bytes` 却重新 `source.open("rb")` 再流一遍。

### 附带问题：目录导入串行 vs 扫描并行

- `resources/import_service.py:215`（`_collect_folder`）— 纯串行 `for path in paths`
- `resources/import_service.py:246`（`import_files`）— 同样串行
- 但 `resources/scanner.py:89` — **已经**是 `ThreadPoolExecutor(max_workers=workers)`

同一仓库里扫描并行、导入串行。1000 文件目录，每次 `path.stat()` +
`_probe_summary` 的 syscall 全串行压单核。

### 影响面

- 大文件：1 GB 栅格白付 3 倍读盘
- 小文件海量：`_collect_folder` 串行是唯一瓶颈
- 导入已在 worker 线程（`ui/pages/data_page.py:1066` `_ImportWorker`），
  **不冻 UI**；但墙钟时间直接决定用户感受

### 预期收益

- 单文件：读 3→1（**−67%**），写 2→1（**−50%**）
- 去重命中：读 4→1（**−75%**）
- 目录导入：与 `scanner.py` 对齐后随核数近线性

### 改造要点

1. `place_managed_file` 复用 target 的 `fd` 给 blob 落盘，或让
   `_place_blob_bytes` 接受"已打开源 fd + 已知 digest"；**禁止**再开 source。
2. 去重快路径：`known_sha256` 由调用方保证时**相信它**（`:458-465` 的
   mismatch 检查在真正拷贝路径上仍生效，语义不丢）。
3. `_collect_folder`：先并发 `stat`，再串行组装（保持 `sorted(paths)`
   顺序确定性，测试不会因顺序抖动而红）。

### 风险与护栏

- **必须保住**：temp+fsync+rename 原子性、只读标记、`known_sha256`
  mismatch 仍报 `CatalogError`。
- 现有回归：`tests/test_v11_scale.py`、`tests/test_v10_schema_constraints.py`。
- 建议新增：用 monkeypatch 统计 `_digest_of` 调用次数，把"单次导入恰好
  1 次"钉死。

---

## 方向二：编图计算核 — 这是三个方向里收益最大的

### 证据 A：克里金是 IDW 的 583 倍

`mapping/geological_pipeline/interpolator.py`：

- `:424-471` `_fit_variogram_numpy`：在**样本两两距离矩阵**上做 4 轮 × 12
  range × 6 nugget 网格搜索。`:433` `np.triu_indices_from(dists, k=1)`
  ——O(N²) 内存 + O(N²) 时间，常数 ×288。
- `:473+` `_pure_numpy_kriging`：`:544` `K = np.zeros((n+1, n+1))` 又一个
  N² 稠密矩阵；`:571-590` 对每个网格点分块调 `np.linalg.solve(K, rhs)`。

**关键反差**：同模块的 `IDWInterpolator` 已经很现代——`:231` 用
`scipy.spatial.cKDTree` + 分块查询（`:241`），`:132-141` 有明确邻域设计。

**更关键**：`InterpolationOptions` 已经**声明**了
`max_neighbors` / `search_radius` / `min_neighbors` 三个字段
（`models.py`），且 IDW 真的在用（`interpolator.py:165-308` 全在 IDW 路径内）。
**克里金完全不读这三个字段**——能力已声明、参数已存在、就是不接线。

`pipeline.py:119` 默认插值器是 `KrigingInterpolator()`，所以**默认路径
就踩在最贵的实现上**。

### 证据 B：等值线是纯 Python 双层循环

`contouring.py:221` `_marching_squares_pure_python`：

- `:237` `for i in range(h-1)` 套 `:239` `for j in range(w-1)`
  ——**每个网格单元一次 Python 迭代**，逐格 `float()` 转换、`math.isfinite`
  四次、16 分支 case 判断。实测 **16-20 µs/cell**。
- `:381` `for idx, level in enumerate(levels)` —— **每个 level 重扫全网格**。
- `:397-408` 再对每条折线做 clip + `calculate_polyline_length`
  （`:59-66` 又是逐点 Python 循环）。

300×300 网格 = 89,401 单元 × 5 level = 44.7 万次外层迭代 → **6.0s**，
产出 44,103 个 feature。

### 证据 C：多边形化是超线性的（最严重）

`polygonization.py:230-246`：

```python
for hole in holes:                                  # :230
    for g_idx, pg in enumerate(poly_groups):        # :238
        votes = sum(1 for pt in hole[:-1]            # :239-243
                    if _point_in_ring(pt[0], pt[1], pg["exterior"]))
```

**每个洞 × 每条外环 × 洞的每个顶点** —— O(holes × exteriors × ring_vertices)。
`:62` `_point_in_ring` 本身还是逐边 Python 循环（射线法）。

实测证实超线性：**面积 ×2.25 → 耗时 ×7.6**（100×100: 3.18s → 150×150: 24.2s）。
150×150 就已经 24 秒，这个默认网格尺寸是**常规操作就踩到**的。

### 证据 D：存在两套并行的等值线实现（架构级发现）

这是走查中最重要的发现，它**改变方向二的范围**：

1. `mapping/geological_pipeline/contouring.py` — `_marching_squares_pure_python`
   （445 行，纯 Python 双层循环，就是证据 B 里那个）
2. `paleo_workbench/_vendored/haiyou_constrained_idw/drawing/single_factor/`
   `constrained_engine.py` — **自带一整套等值线体系**（8,827 行文件）：
   `masked_marching_squares` (:8554)、`connect_segments` (:8683)、
   `postprocess_contours` (:5966)、`cartographic_smooth_contours` (:3555)、
   `guarantee_no_contour_crossings` (:2673)、`interrupt_contours_at_barriers`
   (:2934)、`prepare_contour_extraction_surface` (:4831) 等 30+ 个
   contour/topology 函数。

而 `workflow/constrained_idw_adapter.py:607-624` 表明**入册路径走的是第 2 套**：

```
# #928: run the vendored upstream contour pipeline (smooth / prune /
extract_contours=True,
...
from paleo_workbench.workflow.contour_draft import ...
contour_levels = suggest_nice_levels_from_range(
```

`run_constrained_idw` 返回的 dict 里直接带 `"contours"`（`:705-713`），
即**约束 IDW 路径的等值线由 vendored 引擎产出，根本不经过
`geological_pipeline/contouring.py`**。

**后果**：
- 同一个"编图"目的，两条路径（`build_factor_map_document` 默认走
  `geological_pipeline`；任务/预览走 `constrained_idw_adapter` → vendored）
  各自维护一套等值线算法，**优化必须两处都做，否则收益只覆盖一半用户路径**。
- 这也是一个**语义一致性风险**：两条路径的等值线平滑/修剪/断面处理规则
  不同，同一份数据经不同入口可能得到不同图形。

**给方向二的影响**：在动手前必须先确定"哪条是权威路径"。
建议做法：
- 若目标是**统一**：把 `geological_pipeline/contouring.py` 退役、全部导向
  vendored 引擎（它明显更成熟：30+ 个后处理函数 vs 445 行纯 Python）。
  这是一个独立的架构任务，应作为方向二的**前置**或**独立方向 2.0**。
- 若目标是**先提速不改架构**：只做 `polygonization.py` 的超线性修复
  （方向二证据 C，24s → 亚秒），因为 `polygonization` 是
  `geological_pipeline` 独有、且是纯性能问题、无架构争议。

⚠️ 注意 `_vendored/` 的语义：`ATTRIBUTION.md` 表明这是第三方（海油）
代码，含"host performance"补丁。改动 vendored 代码需要考虑上游同步成本，
且它带 `ATTRIBUTION.md:66-69` 记载的行为差异说明。

---

## 影响面

- `FACTOR_DEFAULTS` 默认 `KrigingInterpolator` → 默认路径最慢
- 改一个插值参数就重跑整链 → 交互手感直接被这三项支配
- 直接决定"编图"这个核心目的的可用性
- 加上证据 D：同目的双实现，优化覆盖面被砍半

### 预期收益

- **克里金**：接线已有的邻域参数（moving neighborhood，k=16~32 局部解
  k×k 而非 N×N）→ 从 27.6s 量级降到与 IDW 同阶。地统计学标准做法，
  不改科学语义（但**必须**把 k 与搜索半径写进结果元数据以保可复现）。
- **等值线**：外层循环向量化（numpy 一次算出所有单元的 case_idx），
  或直接换 `skimage.measure.find_contours` / `contourpy`（QGIS 侧已有 GEOS）。
  预期 5-20×。
- **多边形化**：把洞归属的暴力三重循环换成**空间索引**（外环 bbox 预筛
  + cKDTree / STRtree）。这一项本身就能把 24s 打到亚秒级。

### 改造要点（顺序建议）

> ⚠️ **先读证据 D**：等值线有两套并行实现。下面的第 4、5 步涉及
> "改哪一套"的架构决策，应作为前置议题单独定。

1. **先建黄金值基线**：跑一遍现有插值输出存盘，改造后用容差比对
   （**不要逐位相等**——任何数值路径改变都会动尾数）。
2. 抽取共享邻域设施：`_idw_knn`（`:212`）现在硬绑 IDW，应抽成模块级
   `knn_weights(...)` 供 IDW + Kriging 共用。
3. 克里金读 `options.max_neighbors` / `search_radius`（字段已存在，
   零 schema 变更）。**这一项收益最大、风险最小，建议最先做。**
4. 多边形化洞归属加 bbox 预筛 + 空间索引（`:238-243`）。
5. 等值线向量化（工作量最大，可放最后）。
6. **任何近似必须落进 `grid_result.metadata` 并在 Inspector 可见** ——
   沿用仓库既有的"诚实降级"惯例（参照 `tool_availability` 的
   `provider_writable_approximate` 先例）。

### 风险与护栏

- 敏感测试：`tests/test_interpolation_evaluation.py`、
  `tests/test_factor_v8_duplication_cv_parity.py`（交叉验证一致性）、
  `tests/test_contour_draft.py`、`tests/test_facies_legend.py`。
  改动前先读。
- 本方向是三者中数值风险最高的，建议**最后启动或独立分支厚测试**。

---

## 方向三：渲染/镜像增量通道 — 消费侧仍是全量

### 问题证据

V11 的镜像 delta 通道（`qgis_mirror.py:889-956`）做得相当完整：逐要素签名
缓存、delta 计算、空 delta 短路、`_SIGNATURE_CACHE` 复用（`:1033`）。
**但这是发布侧。**

- `map_render_backend.py:1815` `_native_snapshot` — 每次 `set_layer_snapshot`
  都重建完整 native snapshot 列表
- `map_render_backend.py:1909` `_reship_full_snapshot` — 名字说明一切，
  全量重发路径仍在
- `map_render_backend.py:1093-1127` `_prepared_layer` — 逐 layer 逐 feature
  构建 `_PreparedLayer`（含 numpy 组装），`:1099` `for feature in layer.features`
- `map_render_backend.py:1665-1688` `_draw_scalar_grid` — **每帧**调
  `scalar.rasterize()` 取全幅 RGBA，再 `.copy()` 一份 QImage（`:1677-1683`）。
  滚轮缩放时每帧都吃这个全幅拷贝。
- `mapping/topology.py:129-189` `validate` / `validate_records` — 逐要素
  串行：`:131` `for layer` 套 `:161` `for record`，每个几何单独走一次桥
  （`:170` `bridge_validate(geometry)`）→ **N 个要素 = N 次跨语言往返**。
  `:147-149` 已有一处"单次提升探测"优化（review-2 P2-6），说明这类 O(N)
  开销被识别过，只是没做成批量接口。这与 `qgis_mirror` 已有"批量发布"
  的成熟度形成反差。

### 影响面

- 回退渲染路径（无 vendor QGIS 构建的环境就落回退，`create_map_render_backend`
  `:2412` 默认 `prefer_qgis=True`）
- 与方向一"重复读盘"同类，但**这是交互路径**：用户直接感知为卡顿
- 拓扑校验：编辑大图层时每次校验都可能秒级

### 预期收益

- 标量栅格去 `.copy()`：省每帧 ×1 全幅 RGBA 拷贝
- `_PreparedLayer` 按 `data_revision` 缓存（抄镜像侧 `_SIGNATURE_CACHE`
  同构设计）：无变化图层零重建
- 拓扑校验批量化：桥接口一次传数组，N 次往返 → 1 次。这是三者中最干净的
  一个改造点（`bridge_validate` 改成 `bridge_validate_many`）

### 改造要点

1. `_draw_scalar_grid`：确认 `rasterize()` 返回值生命周期后用 `QImage`
   直接引用（不 `.copy()`），或让 `rasterize()` 直接产出 `QImage` 并缓存
   在 scalar 对象上，把拷贝摊到"数据变更时一次"。
2. `_PreparedLayer` 加 `(layer_id, data_revision)` 键缓存——**建议抽公共
   缓存类**，与 `qgis_mirror._SIGNATURE_CACHE` 共用，避免第三处平行实现。
3. `topology` 桥校验改批量接口。
4. `qgis_mirror` 消费侧：现在 delta 只发给 C++；Python 侧准备 snapshot
   时仍全量。

### 风险与护栏

- `_PreparedLayer` 缓存最易出的 bug 是**陈旧几何**——正是 #1257
  （定位器不失效）同类。缓存键必须含完整 `data_revision`，并要有
  "改一个顶点后缓存必失效"的对照测试。
- 现有护栏：`tests/test_mirror_lifecycle_v11.py`（336 行）、
  `tests/test_layer_tree_diff_v11.py`、`tests/perf/test_mirror_publish_scale.py`。
  ⚠️ 后者 `[50]` 用例在本机**已是既有失败**（预算 60ms，实测 64.6/201.4ms），
  非本次引入，不要误判。

---

## 为什么这三个方向可以并行

### 文件集零交集

| 文件 | 一 | 二 | 三 |
|---|---|---|---|
| `catalog/storage.py` | ● | | |
| `catalog/adapter.py` | ● | | |
| `resources/import_service.py` | ● | | |
| `resources/scanner.py` | ● | | |
| `mapping/geological_pipeline/interpolator.py` | | ● | |
| `mapping/geological_pipeline/contouring.py` | | ● | |
| `mapping/geological_pipeline/polygonization.py` | | ● | |
| `mapping/map_render_backend.py` | | | ● |
| `mapping/qgis_mirror.py` | | | ● |
| `mapping/topology.py` | | | ● |

可以同时开三条 worktree 分支，git 层面不冲突。

### 不共享被测契约

- 方向一：`_digest_of` 调用次数、落盘结构、原子性
- 方向二：数值等价性（对黄金值容差）、复杂度上界
- 方向三：缓存命中、帧预算、跨语言调用次数

三套测试文件不重叠，可各自独立跑、独立验收。

### 唯一的共享纪律

"改性能不动语义" + "近似必须诚实披露"。两者都是仓库既有惯例，但各自落在
不同代码上，不构成耦合。

---

## 建议落地顺序

若必须串行：**方向一 → 方向三 → 方向二**。
理由：方向一收益确定、风险最低（纯 I/O 去重，语义不变）；方向三中等且
有一个干净的高收益点（拓扑批量化）；方向二收益最大但数值风险最高
（须先建黄金值基线）。

但用户问的是**并行**——所以按上面三个分支同时开即可，代价只是三条分支的
review 负担。若 review 带宽有限，建议先合方向一（最快、最安全）。

---

## 本报告未覆盖 / 需继续查

- `_vendored/haiyou_constrained_idw/` 已**部分**审计（见方向二证据 D：
  确认它持有第二套等值线体系）。但其 8,827 行 `constrained_engine.py` 的
  **性能特征未实测**（`generate_constrained_idw` :582 是主入口，
  `_interpolate_euclidean_cells_batch` :1863 看起来已做批处理，
  `build_barrier_proximity_mask` :4334 / `fill_internal_gaps` :4626 等
  可能有循环热点）。**这是编图核里最大的未知量，值得单独一轮。**
- `mapping/composer/renderer.py`（1,341 行，成图排版渲染）未审计——
  与方向三同域但不重叠文件。
- `catalog/service.py`（4,675 行）的 `_aggregates_cache` /
  `_paged_fallback_cache` / `_lineage_summary_cache` 失效语义未复核
  （V11 后可能已变）。
- 计时为**单次运行**，未做统计重复。量级用于定序，不用于验收。
  若要写进性能门禁，需改成统计重复（本仓库已有 `tests/perf/` 基础设施可复用）。
- 本报告只读了各方向的"主战场"文件；未做全仓穷尽扫描，不排除别处还有
  同类问题。
