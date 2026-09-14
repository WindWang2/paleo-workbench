# 02 — 空间索引 / 脏区拓扑 / POD 总线设计

## 1. SpatialIndexCore（Ticket 1）

### 1.1 数据结构

```
// spatial_index_core.hpp（节选；POD，无递归析构热路径）
struct IndexEntry {          // 叶项：一个顶点或一条边段
  double minx, miny, maxx, maxy;   // 顶点时 min==max
  qint64 feature_id;               // QGIS fid
  int32_t part, ring, vertex_nr;   // QgsVertexId 三元组（边段存首点 nr）
  int32_t kind;                    // 0=vertex, 1=segment
};
struct Node {
  double bminx, bminy, bmaxx, bmaxy;   // 节点 MBR（写后回溯收紧）
  int32_t count; int32_t leaf;         // 叶/枝标记
  int32_t children[kMaxChildren];      // 枝: 子节点下标；叶: 项表下标
};
```

- 定容节点数组（`kMaxChildren=16`），单块连续存储（`std::vector<Node>` +
  `std::vector<IndexEntry>`），下标寻址——缓存友好、无指针追逐。
- 批量构建：STR（Sort-Tile-Recursive）打包，leaf-fill 满载起步；运行期
  `insert()` 分裂采用二次分裂（_pickSeeds/_pickNext，经典 Guttman），分裂
  后 MBR 回溯收紧；`remove(feature_id)` 借助每 feature 项桶账（`unordered_
  map<fid, small_vector<entry_slot>>`）O(k·logN) 定位，下溢节点重插。
- 查询：`radiusQuery(cx, cy, r)` 与 `rectQuery(box)` 走 MBR 剪枝的 DFS；
  `knnQuery(cx, cy, k, max_dist)` 用最小堆 best-first。
- 并发：`std::shared_mutex`——查询取共享锁（读多写少无等待路径，Phase 3
  审查项）；构建/失效/插入取独占锁。索引只在 GUI 线程变更（Qt 世界的
  既有单写者约束），共享锁保护的是渲染/定位线程的并发读。

### 1.2 与 PwbVertexTool 的接线

- `Impl` 持 `unordered_map<QgsVectorLayer*, LayerVertexIndex>`（弱键 +
  `destroyed` 断连）。
- 失效钩子（全部在既有代码路径上，无新增监听面）：
  `startMirrorLayerEditing`/`commitMirrorLayer`/`rollBackMirrorLayer`、
  `applyMirrorFeatureDelta` 成功路径、`edit_tools.cpp` 每个宏
  `endEditCommand` 之后（feature 粒度 remove+reinsert）。
- `verticesNear`/`verticesInRect` 改为先查索引（命中即按
  `vertexIdFromVertexNr` 复核坐标仍在容差内——索引项可能落后于编辑缓冲
  的窗口由失效钩子封闭为空）；索引不存在时走原线性扫描（能力降级路径，
  保持桥在旧宿主上的行为）。
- 闭合环首尾同点去重逻辑原样保留（`kSharedNodeEpsilon` 语义不变）。

### 1.3 SLA 断言与微基准

- 新增绑定 `vertex_pick_bench(canvas, doc_id, x, y, radius, repeats)`：
  直调生产 `PwbVertexTool::verticesNear`，返回 {hits, micros[]}。诊断面，
  契约计入 capability_manifest。
- `tests/perf/test_spatial_index_benchmarks.py`：
  - 50k 顶点网格（确定性种子），radius 命中/不命中混合；
  - 断言：中位 <1.0 ms（SLA）、hits 与线性扫描参照完全一致（正确性）；
  - 反向对照（anti-tautology）：人为把索引换回线性路径（环境开关
    `PWB_DISABLE_VERTEX_INDEX=1`）时，20k+ 规模必须超时变红。

## 2. DirtyBoxTopologicalCore（Ticket 2）

### 2.1 会话缓存

```
// incremental_topology.cpp（节选）
struct FeatureFingerprint { qint64 fid; uint64_t wkb_hash; };
struct TopoSessionCache {
  // 每 (layer_doc, fid)：几何指纹 + 上轮该要素的错误（is_valid/dangle）
  // 每 (layer_doc, fidA, fidB) 有序对：上轮 overlap 错误
  // 全图层 gap：整层指纹集合 → 上轮 gap 错误列表
};
```

- 指纹 = `QgsGeometry::asWkb()` 的 FNV-1a 64（每次 run 增量更新，代价
  O(变更要素)，非 O(全图)——与基线 4 s 的检查本身相比可忽略）。
- **脏区** = `MBR(指纹变化要素 ∪ 新增要素 ∪ 删除要素旧 MBR)` 外扩
  `2 × tolerance`（tolerance 来自 checks config 的 precision；缺省
  1e-8 同 `kSharedNodeEpsilon` 惯例）。

### 2.2 受限复检（patch 语义）

1. 池 = 脏要素 ∪ 邻居（索引 `rectQuery(脏区)` 命中的要素，几何只读）。
2. is_valid/dangle：只对脏要素跑；干净要素错误原样保留。
3. overlap：对（脏,任意）对重跑；（干净,干净）对错误缓存直用。OverlapCheck
   在子池上的 pair 结果与全池一致（其相交判定是逐对几何运算，与池无关）。
4. 合并去重（host fid 对有序化）后序列化——与全量输出逐字段相等
   （`test_incremental_topology_bench` 的等价性断言）。
5. gap：仅"全图层指纹集合未变 → 缓存直返"；变化时全量（记入 04）。

### 2.3 SLA 断言

- 10k 面（50k 顶点）：移动 1 顶点 → 复检中位 <35 ms（基线 3,920 ms）。
- 等价性：随机 20 步编辑序列，每步后 run() 的错误列表 == 关缓存全量
  run() 的列表（排序后逐字段相等）。

## 3. Visvalingam LOD（Ticket 3）

- 有效面积 `area(p) = |cross(prev, p, next)| / 2`；最小堆逐点剔除至
  `area >= tolerance²`；环首尾、凸包极值点、拐点（符号翻转处）强制锚定。
- 阈值：`tolerance_map = pixel_tol(0.75) / mupp`；按 2 的幂分档
  （scale bucket）入缓存，键 `(layer, data_revision, bucket)`。
- C++（map_edit_core `vector_lod(ring_xy, tolerance) -> (keep_mask, out_xy)`
  批量接口）与 Python 参照实现位相等（同浮点运算序），测试双实现互证。

## 4. 相带图集（Ticket 4）

- `FaciesTextureAtlas`：init 时 `QSvgRenderer` 逐张渲染到网格图集
  （每 pattern 一格 32×32 × 3 档 scale），`brush_for(pattern, scale)` 从
  UV 子图构造纹理笔刷（QImage 拷贝仅发生在档位未命中时，正常缩放 0 次）。
- 绘制：`flush_polygon` 改为按 pattern 分组累积 QPainterPath 后一次
  `drawPath`/pattern；底色 pass 不变。首帧烘焙从 O(first paint) 提前到
  init 且只做一次。
- 无头压测：`test_facies_atlas_bench`（zoom/pan 各 12 帧）断言 2k 面
  <16 ms/帧、10k 面 <16 ms/帧（SLA）。

## 5. EditDelta POD 总线（Ticket 5）

### 5.1 POD 布局（64 字节对齐钉死）

```
// edit_delta_pod.hpp
struct alignas(64) PwbEditEventPod {      // static_assert(sizeof==64)
  double x, y;            // 地图坐标
  double dx, dy;          // 位移（手势类）
  int32_t kind;           // EventKind: hover/snap/move/delete/...
  int32_t layer_slot;     // 注册层槽位（避免字符串跨界）
  int64_t feature_ref;    // 宿主 feature id（数值化）
  uint64_t sequence;      // 生产者序号（SPSC 穿越检测）
  uint64_t timestamp_ns;  // steady_clock
  uint32_t payload_u32[2];// 事件专属（如 vertex path part/ring/nr）
  uint32_t crc32;         // 尾字段校验（越界/撕裂检测）
};
```

### 5.2 SPSC 环与批量排水

- 环存储：`std::vector<PwbEditEventPod>`（2 的幂容量，C++ 侧持有），
  pybind 以 `py::buffer_protocol` 暴露只读视图 + `drain_into(dst_buffer)`
  单次 FFI 批量 memcpy（调用方预分配 `array.array`/memoryview）。
- 写侧（C++）：head/tail 原子序号 + release 发布；读侧 acquire。
- Python `edit_delta.py`：`ZeroCopyEventBus`——`poll()`（非阻塞）/
  `drain_into(buf)`；事件解码按需（默认延迟到消费者读字段，避免中间
  对象）。
- 接线：`set_event_bus_enabled(canvas, true)` 后 `snap_feedback`/
  `edit_gesture` 写环（JSON 回调并行保留，宿主未启用时行为与今完全一致）。
- SLA 压测：10,000 事件 / 10k Hz 排水，tracemalloc 断言 0 追踪分配；
  JSON 参照通道同负载的分配数作为反向对照（必须 >0，防退化）。
