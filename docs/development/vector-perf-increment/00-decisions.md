# 00 — 架构与算法决策（vector-perf-increment）

基线：`main` @ `e7214566`（worktree `feat/vector-perf-increment`，首个提交为
qgis-runtime loader 的 vendor 预加载移植）。

所有决策遵循 CLAUDE.md 的 Karpathy 准则：最小实现、外科手术式改动、对外 API
兼容（内部加速替换）。

## D1 空间索引：自研动态 R-Tree（`spatial_index_core.hpp/.cpp`）

**备选**：(a) 复用 `QgsSpatialIndex`（libspatialindex 封装）；(b) 复用
`QgsPointLocator`；(c) 自研 R-Tree。

**选择 (c)**，理由：

1. **载荷是顶点级**（`{fid, part, ring, vertex_nr}`），而 `QgsSpatialIndex` 以
   feature bbox 为键——每个顶点需伪造一个 `QgsFeature` 才能入索引，构建与
   失效的开销反而超过线性扫描的收益。
2. `QgsPointLocator::nearestVertex` 只返回单个最近点，无法表达
   `verticesNear` 的"半径内全部顶点"与 `verticesInRect` 的矩形查询，且其
   缓存失效与画布 snapping 配置耦合（hover 路径已在用它，手势路径不应共享
   失效时机）。
3. 审查阶段要求读多写少下 `std::shared_mutex` 无等待读路径与可控的批量
   STR 装载——自研树（节点 POD、容量预置、无递归析构热路径）可控性最高。
4. Ticket 2 的脏区环段提取复用同一索引（边段矩形），一树两用。

**树形**：叶子/枝节点均为定容 POD 数组（M=16/32，STR 批量装载起步，
运行期插入用二次分裂（quadratic split）+ 删除下溢借位/合并；KNN 用
best-first 优先队列）。复杂度目标：批量构建 O(N log N)、插入/删除
O(log N)、半径/KNN 查询 O(log N + k)。

**失效纪律（关键正确性决策）**：顶点编号在插点/删点后整体平移，逐顶点
手术式更新不安全——以 **feature 为失效粒度**：任何几何变更 → 删除该
feature 的全部索引项（每 feature 维护项数桶账）→ 用编辑缓冲后的最新几何
重新插入。图层级兜底：会话开始/结束、provider 重载、镜像 delta 应用后全量
重建（bulk STR）。索引重建成本实测被摊销进多次手势。

## D2 拓扑增量：指纹缓存 + 脏区受限复检（`incremental_topology.cpp`）

- 每次 `run_geometry_checks` 的输入按 feature 计算几何指纹（WKB 哈希）。
  与缓存指纹一致的 feature 视为 clean，其历史错误记录直接复用。
- 脏区 = 本轮指纹变化（含新增/删除）的要素并集外包矩形，外扩
  `2 × tolerance`（配置 precision 决定）。仅"脏要素 ∪ 与脏区相交的邻居"
  进入受限检查池；overlap/dangle 的配对错误在（脏,干净）对上重算、
  （干净,干净）对沿用缓存。
- **gap 规则例外**：间隙是覆盖全局属性，子集池会产生边界假间隙。决策：
  gap 仅做"全图层指纹未变 → 原样返回缓存"的快路径，覆盖变化时全量重算
  （记入 04-known-limitations）。SLA 场景（节点移动后的有效性验证）不受影响。
- 等价性契约：测试用随机编辑序列断言"增量结果集 == 全量结果集"逐字段相等。

## D3 LOD：Visvalingam-Whyatt 有效面积 + 特征点锚定

- C++ 侧 `vector_lod.cpp`（map_edit_core 扩展）+ Python 侧同算法回退实现
  （能力探测式分发，遵循仓库 native_backend 惯例）。
- 阈值由视口比例推导：`tolerance_map = pixel_tol / map_units_per_pixel`；
  顶点有效面积 < tolerance² 即剔除；环首尾点与拐点（凸包极值）强制保留。
- 缓存键 `(layer_id, data_revision, scale_bucket)`，挂在既有
  `_prepared_layer`/`_reprojected_prepared` 缓存同层，不新建平行缓存体系。
- 既有帧级像素网格量化（>400k 顶点档）保留不动——本票是数据集级化简，
  两者正交。

## D4 相带花纹：单图集预烘焙 + 按花纹分组批量填充

- 初始化时把 `assets/patterns/facies/*.svg`（17 张、32×32）一次性烘焙进
  **单一 QImage 图集**（网格排布 + UV 矩形表），替代"首个绘制帧逐张
  QSvgRenderer"的懒烘焙。
- 绘制侧：同一 pattern 的全部多边形合并为一个 QPainterPath 一次
  `drawPath`（纹理笔刷从图集 UV 区域构造）——绘制调用次数从 O(features)
  降到 O(patterns ≤ 8)。QPainter 栅格化路径没有真 GPU Instancing，
  "批处理"在此语义下成立；不伪造 GPU 术语（记入 04）。
- 笔刷缓存键去掉 scale 维度中的连续化（quantize 到图集档位），避免缩放
  过程反复重烘焙。

## D5 零拷贝 EditDelta 总线：SPSC POD 环 + buffer_protocol 批量排水

- `edit_delta_pod.hpp` 定义 64 字节对齐 POD（`static_assert` 钉死尺寸与
  对齐）：坐标、位移、事件种类、feature 宿主 id、序号、纳秒时间戳。
- C++ 生产者（edit_tools 手势/吸附事件）写入无锁 SPSC 环（acquire/release
  语义 + 序号穿越检测）；Python 端 **一次 FFI 调用批量排水到调用方预分配
  的 buffer**（`py::buffer_protocol`）——按记录零 Python 对象、零 JSON、
  零拷贝（memcpy 进复用缓冲）。
- **opt-in**：`set_edit_pick_callback` JSON 通道保持默认且语义不变（API
  兼容红线）；总线由 Python 显式启用。SLA 压测断言 tracemalloc 追踪的
  Python 分配为 0。
- 排水后事件仍可在调试模式下镜像为 JSON（诊断通道），默认关闭。

## D6 拒绝 100GB 栅格驻留内存（红线论证）

- 物理层：本机 DDR 带宽 ~50GB/s、页错误恢复 ~µs/4KB——100GB 驻留意味着
  2.5 万万次页错误级别的冷启动，或把工作集压进 swap 后每次平移都抖动。
  访问模式上，编图交互是**视口局部性**（任意时刻仅可见范围被采样），
  全量驻留对任何用户路径都没有渐进收益。
- 本分支的全部工作聚焦矢量编辑链路（索引/拓扑/LOD/图集/总线），
  栅格路径继续走既有的视口窗口化与瓦片缓存，不引入任何全量驻留方案。

## D7 编译与环境纪律

- 复用主仓 vendor 构建（`PALEO_QGIS_REUSE_VENDOR=1` +
  `PALEO_QGIS_BUILD_DIR` 指向主仓 `build/qgis-vendor`），**绝不重复构建
  vendored QGIS**（setup.py 官方跨 worktree 约定）。
- 桥 .pyd 在 worktree 内 `setup.py build_ext --inplace --parallel 2`
  （≤2 并发）；测试经 `PYTHONPATH=<worktree>/native/qgis_render_bridge`
  遮蔽共享 .venv 的 editable 指向，**不改动共享 .venv**。
- 不 `git worktree prune`（仓库红线）；提交 → push → `gh pr create`。

## D8 已知崩溃与测量通道降级（本机、今日、既有）

主仓 vendor 构建于今日 14:09 被并行会话重建后，`QTest` 真手势路径存在
访问冲突：命中共享节点的 press（任意规模）与 ≥20k 顶点的 press 直接崩溃
（`tests/test_qgis_topo_m1_native_editing.py::test_scenario5` 单测亦然，
主 .pyd 与本 worktree .pyd 同崩）。该域属并行 prompt-1（拓扑编辑器）。
本分支决策：手势级计时保留 ≤10k 规模（实测稳定）；≥20k 的 SLA 证据改走
**C++ 微基准绑定**（直调生产 `verticesNear` 实现，无 Qt 事件投递面），
崩溃事实记入 04-known-limitations 并在 PR 描述同步。
