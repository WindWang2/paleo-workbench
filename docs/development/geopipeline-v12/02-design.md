# V12-B 设计（编图计算核提速）

前置阅读：00-decisions.md（D1–D5）。本文件只记落地结构，不重复决策论证。

## 1. 克里金 moving neighborhood（`interpolator.py`）

```
KrigingInterpolator.interpolate(options)
  └─ _neighborhood_requested(max_neighbors, search_radius)?
       ├─ 否 → 原路径（geoviz 引擎优先；ImportError → 全局 numpy 回退）【零改动】
       └─ 是 → _pure_numpy_kriging(..., max_neighbors, search_radius, min_neighbors)
              ├─ 去重 / O(N²) 距离矩阵 / 变差函数拟合 / 常量短路   （共用，零改动）
              └─ _kriging_moving_targets(...)                    （新增）
                    ├─ cKDTree 查询 k 近邻（含半径上界，chunked）
                    ├─ 逐目标 (k+1)² 增广 OK 系统：
                    │    半径剪枝的邻居 = 行列清零 + 对角置 1 + 权重钉 0
                    │    （拉格朗日行只约束保留的权重 → 精确消去，非近似）
                    ├─ batched np.linalg.solve((G, k+1, k+1))
                    │    奇异 → _solve_single_system（solve→ridge→lstsq 阶梯）
                    └─ z_pred / variance（方差公式与全局路径同式）
```

- 复杂度：O(N²)（变差函数预处理，与全局共用）+ O(M·k²)（近邻距离与系统装配）
  + O(M·k³/3)（batched solve）。全局路径是 O(N³/3) + O(M·N²)。
- 内存：`(chunk, k+1)²` 按目标分块（`_KRIGE_NEIGHBOR_CELLS` 预算），k 上限
  `_KRIGE_NEIGHBORHOOD_CAP=256`，超限截断且必须披露（`neighborhood.capped`）。
- 元数据：`algorithm_parameters.neighborhood = {engine, max_neighbors,
  requested_max_neighbors, search_radius, min_neighbors, capped[, cap, note]}`；
  路径整体标注 `degraded=True`（诚实降级，理由写明 geoviz 引擎无邻域参数）。

## 2. 多边形化洞归属（`polygonization.py`）

```
_polygonize_raster_boundaries
  └─ _assign_holes_to_exteriors(poly_groups, exterior_rings, holes, qc)  【模块级，
        │                                                                供反向对照 monkeypatch】
        ├─ 逐外环预算 bbox（ext_arrays / ext_bbox，提升的岛追加）
        ├─ 逐洞：bbox 相交预筛（两框不相交 ⇒ 必无顶点命中 ⇒ 可证超集）
        └─ _hole_vertex_votes(hx, hy, ring_arr)
              (环边, 洞顶点) 二维广播，边按 _HOLE_VOTE_EDGE_CHUNK 分块；
              每边表达式与原标量射线法逐字相同（同浮点次序 → 同布尔结果），
              逐顶点奇偶 parity 即原判定。
```

- 复杂度：洞 × 候选外环（bbox 相交者）× O(边×顶点/向量化宽度)。
  speckle 场实测面积 ×4 耗时比 4.2（线性），原实现 12.1（超线性）。
- 语义不变的机制：预筛是超集 + 投票谓词逐位等价 + 选择规则（面积升序、
  严格多数、平票归最小、未匹配提升为岛）逐字未动 → 输出逐字节一致
  （黄金值 poly_* 为证）。
- 附带修复：`crs_policy.crs_is_geographic` 加 `lru_cache`（纯函数；
  pyproj 缺失时每次调用重试失败 import，每层上万次 ≈2s）。

## 3. 黄金值基线（`scripts/geopipeline_v12_golden.py` + `tests/data/`）

- generate/compare 两子命令；25 案例覆盖矩阵见 01-golden-baseline.md。
- 比对策略：默认路径字节级一致；克里金网格 max|Δ| ≤ 1e-5（D5 论证）。
- 脚本显式钉死纯 numpy 回退路径（`sys.modules.setdefault("geoviz", None)`）：
  geoviz 可导入性随环境漂移（site-packages 出现 matplotlib 即可让 editable
  指向的 geoviz_plots 导入成功），不钉死则被比对对象会静默翻转。

## 4. 不做的事（本轮）

- `contouring.py` 不动（D1 选项 A）；其黄金值基线已建好供下一轮使用。
- `_vendored/`、`native/`、`third_party/`、UI/QGIS、catalog：零改动。
- 变差函数拟合不做大 N 子采样（N=2000 时 0.11s 非瓶颈；见 04 已知限制）。
