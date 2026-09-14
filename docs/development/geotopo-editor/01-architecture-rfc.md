# 01 · 架构 RFC — 地质拓扑编辑引擎数学模型与算法推导

状态：Proposed→Accepted（文档先行阶段定稿） ｜ 前置：00-decisions.md

---

## 1. 术语与问题域

- **控制线（control line）**：古岸线、相变分界线、断层线的折线集合 L = {l₁…lₘ}，每条 lᵢ = (pᵢ₀…pᵢₙᵢ)，坐标取图层 CRS 线性单位。
- **相带多边形（facies band polygon）**：由控制线网络围出的最小面域，携带沉积相属性。
- **问题一（动态构面）**：给定 L，求平面细分 Σ(L) 的全部有界面（最小闭合回路），并输出每个面的**父线溯源**（由哪些控制线围成），供相属性继承。
- **问题二（断-相截断）**：给定断层折线 f 与面集合 P，对每件与 f 真相交的 p∈P 执行原子分割，属性克隆 + `fault_bounded` 标记。
- **问题三（共边重塑）**：给定相邻两面 pₐ,p_b 的共享弧 a 及新曲线 c，同时替换两侧环，保持 ∪ 无缝无叠。
- **问题四（拓扑守卫）**：提交前对编辑真值执行相律邻接 / 悬挂断层 / 等厚线-剥蚀边界三类地质不变量校验。

## 2. DCEL 平面细分模型（问题一）

### 2.1 数据结构

```
Node    { double x, y; size_t first_he; }        // 节点
HalfEdge{ uint32_t origin; int32_t twin;         // 半边：起点 + 孪生
          int32_t next; uint32_t face;            // 面内后继 + 所属面
          uint32_t parent_lines_bits; }           // 父线溯源（小集合位压缩，>64 父线退化为首父+计数）
Face    { int32_t outer_he; double signed_area; }
```
全部存储于三个 `std::vector`（SoA 倾向但保持 AoA 简单），无逐边堆分配——这是 30 ms 门禁的工程前提。

### 2.2 Noding（相交打断）

**输入规整**：折线 → 有向段 s = (a,b)，段级属性 (line_id, seq)。

**空间索引**：均匀网格，格子宽 `w = extent / ceil(sqrt(N))`；段按 bbox 插入覆盖格。候选对 = 同格段对。网格用例（5000 段 50×50）平均每格 ~8 段，候选对 ≈ N·k，k≪N。

**精确求交**（每候选对，ε=tolerance）：
1. 令 d = cross(b-a, d-c)。
2. `|d| ≤ ε·|b-a|·|d-c|` → 共线判定：投影区间 [t₀,t₁]∩[u₀,u₁] 为空 → 邻接跳过；非空 → **端点注入法**：把对方的两个端点参数 t 化后插入本段打断表（反之亦然），不生成显式交点——重叠域被细化为逐段全等子段，随后去重。
3. 否则计算 t = cross(c-a, d-c)/d 等 ∈ [0,1]（ε 膨胀），交点 q = a+t(b-a) 同时插入两段打断表。
4. 端点数值稳定：t 钳位 [0,1] 后距端点 < ε 视为端点本身。

**节点合并**：交/端点坐标按 `round(coord/tolerance)` 网格化哈希，邻格（含自身 9 格）查重合并——容差传递闭包由网格粒度截断（一次归并，不迭代），保证 O(1) 摊销。

**段去重**：打断后的子段按 (min_node, max_node) 排序，同键取一，父线位集按位或合并——**共享边（相邻相带共有界线段）天然成为单条 DCEL 边**，这是共边联动（问题三）的拓扑根基。

### 2.3 悬挂枝剪除

度数统计后迭代删除端点度为 1 的边（控制线自由端、未闭合断层尖灭端），直至不动点。剪除数进入诊断输出 `dropped_dangles`（守卫问题四会复用该语义判定"悬挂断层"是否合法图元外残留）。

### 2.4 面追踪（Leftmost-Turning 最小回路）

对每节点出边按极角 θ∈[0,2π) 排序（atan2 一次预计算）。从任一半边 h 出发：

```
walk(h): ring ← []
  loop:
    ring.push(origin(h))
    h ← twin(h)                       // 跨到对面
    h ← prev_ccw_at(origin(h), h)     // 该节点出边中比 twin 极角小一位的边（角序前驱）
  until h == start
```
该 walk 恒沿"面的边界逆时针侧"前进，遍历每半边恰一次 → 得到全部最小回路与一个无界面（signed_area 符号异号或包围盒达 extent 者）。**剔除无界面**即"剔除外包大框"；可选 `clip_envelope` 剔除越界面。

**正确性论证**（草图）：平面细分的面-半边对应是双射；leftmost-turn 在无悬挂、无自重边的连通平面图上恰好实现面边界的逆时针遍历，回路最小性由局部极角序保证（任一更小闭合回路会要求在某节点跳过角序前驱，与构造矛盾）。自交输入已被 noding 消解为合法细分，故前提成立。

### 2.5 输出与溯源

面 → OGC Polygon（外环 CCW，数值化简到输入精度位数）；`source_lines` = 环上边的父线位集展开。宿主侧相属性继承策略：新面与旧相带面求交面积最大者继承其属性（host 层 `geotopo_service.py` 提供，属 UI 编排，不进核心）。

### 2.6 性能预算（5000 段 ≤ 30 ms）

| 阶段 | 预算 | 依据 |
|------|------|------|
| 网格索引 | 4 ms | 5000 段 bbox 插入 ~2 格均值 |
| 求交+打断 | 14 ms | 候选对 ~20k，每对 ~50 ns |
| 节点合并+排序 | 6 ms | ~2601 节点 + ~10k 子段排序 |
| 面追踪 | 5 ms | E≈10k 半边，角排序 O(E log d) |
预算在单核 Release x64；`elapsed_ms` 字段回传实测值，性能门禁测试断言。

## 3. 断-相协同截断（问题二）

### 3.1 拾取

`feature_ids` 空时：`QgsFeatureSource::getFeatures(QgsFeatureRequest(bbox))` + GEOS `intersects(curve)`；曲线自预先 `QgsGeometry::fromGeoJSON + makeValid`。

### 3.2 分割

`QgsVectorLayerEditUtils::splitFeatures(curve, topoPoints, true /*topologicalEditing*/, false)` — QGIS 语义：每件被穿越要素替换为 N 件，**属性全量克隆**。端点恰在边界（"端点正好贴合边界"用例）时 GEOS 边界相交退化 → splitFeatures 返回 0 表示未切动，属合法幂等。

### 3.3 断裂标记

同一宏内：`fault_bounded` 缺失 → `addAttribute(QgsField("fault_bounded", QMetaType::Type::Bool))`；对新旧两部分 `changeAttributeValues(fid, {fault_bounded: true})`。`fault_side`（可选）：新面质心相对断层折线首末向量叉积符号 → hanging/footwall。**同沉积断层语义**：截断后两盘相带属性各自独立演化，故只克隆不合并——属性延续性由克隆保证，分异由标记显式化。

### 3.4 手势与原子性

单一 `beginEditCommand("断层截断")` 宏；结束发 `edit_gesture`（gesture="fault_cut", layers=[面层,(经 addTopologicalPoints 波及的线层)]）→ 宿主 EditGestureManager 归并为单手势 → 一次 Ctrl+Z 同步撤销（与 Ticket 5 的 compound_macro 复合）。

## 4. 共边联动重塑（问题三）

### 4.1 共享弧识别

`find_shared_arcs(polygon_a, polygon_b, tol)`：两环顶点按容差节点化（复用 2.2 节点合并），共节点链 = 候选弧；弧上连续子段双亲分别属 a/b → 输出弧（含端点索引）。多段共边（enclave/飞地）输出多弧。

### 4.2 替换与守恒

环表示为节点循环链；把弧区间 [i..j] 替换为 `curve`（a 环正向、b 环用 reverse(curve)）。守恒三校验（GEOS）：
1. 两新环 `isGeosValid`（simple + 方向）；
2. `area(intersect(a',b')) ≤ ε_a`（ε_a = tolerance × 曲线长度，无重叠/sliver）；
3. `|area(union(a',b')) - area(union(a,b))| ≤ ε_a`（无裂隙）。
面积和守恒 `area(a')+area(b') = area(a)+area(b)` 是 2+3 的推论（因 a∩b 面积在 2 中被压零）。**任一失败 → 错误码拒绝，零变更**（D6 拒绝式哲学）。

### 4.3 Ribbon 语义

地质图上共边即"相变界线"——重塑后该界线两侧同时更新（同一 curve 镜像双向），保证界线是两相带的**公共弧**而非两条独立边；`addTopologicalPoints` 把 curve 顶点散布到关联层（AvoidIntersectionsV2 同族机制），后续顶点编辑天然联动。

## 5. 地质拓扑守卫（问题四）

### 5.1 相律邻接（facies_adjacency_gap）

shapely `relate`/共享边界长度：两面 boundary 交集长度 > `min_shared_len`（默认 10×tolerance）即"直接相邻"；对 (facies_a, facies_b) 查 D7 邻接矩阵，非法 → error 违规，message 含"缺失过渡相"语义（由秩差推导，如 深水盆地↔冲积扇 → "缺失 陆棚/滨岸 过渡相带"）。

### 5.2 悬挂断层（dangling_fault_unsealed）

断层线端点 p：若 p 不在容差内触及（任一其他断层线 / 任何相带面边界 / 工区外框），且 p 落于某相带面内部 → error（"相带内部未封闭悬挂断层"）。仅触及工区框或达到面边界 → 合法尖灭。

### 5.3 等厚线-剥蚀边界（isopath_crosses_unconformity）

等厚线（role=isopath）与剥蚀边界（role=erosion_boundary，面边界）相交处，等厚线**无容差内顶点**（未断开节点）→ error。判定：shapely `intersection(line, boundary)` 产点数 > 该点处 line 顶点匹配数。

### 5.4 不变量输出

`InvariantViolation(code, severity, message, layer_id, feature_ids, hint)`；矩阵全组合测试见 03-tdd-test-plan。

## 6. 原子宏事务（问题五）

两层：手势级（EditGestureManager 既有 undo_plan 跨层逆序）+ 提交级补偿（快照-重写-单宏恢复，见 D9）。并发撤销压力：多线程**不**新增——Qt GUI 单线程权威 + 桥计算段 GIL 释放，压力测试用多手势交错 undo/redo 验证计划一致性（详见 03）。

## 7. 模块边界与依赖方向

```
native/qgis_render_bridge/src/
  geological_topology_core.{hpp,cpp}   ← 零 QGIS；纯 std；可 standalone_test
  edit_tools.{hpp,cpp}                  + PwbFaultCutTool / PwbBoundaryReshapeTool (QgsMapTool)
  map_stack_service.cpp                 + faultCutMirrorFeatures / reshapeSharedBoundary / findSharedArcs
  bindings.cpp                          + geotopo 子模块 + mapstack 新方法
paleo_workbench/mapping/
  geotopo_service.py                    host 包装：桥优先，shapely fallback（polygonize/共边）
  geological_invariants.py              纯 Python + shapely 守卫（零桥依赖）
  native_edit_session.py                + geology 谓词 + 补偿事务
paleo_workbench/resources/facies_adjacency.json
paleo_workbench/ui/workstation/composite_editing.py  + fault_cut/boundary_reshape 工具接入 + compound_macro
```
依赖单向：UI → mapping → (桥 | shapely)；核心 C++ 不反向依赖任何上层。
