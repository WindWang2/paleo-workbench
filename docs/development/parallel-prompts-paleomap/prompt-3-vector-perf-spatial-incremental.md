# Prompt 3 — 超低延迟交互响应、拓扑局部增量计算与大尺度矢量渲染性能提升引擎

> **使用方式**：直接复制以下全部内容，粘贴到 zcode agent 的输入框中直接运行（无需在命令行拆分执行）。
> 本 Prompt 内部已通过 `$goal` 与 `$loop` 命令调度，内置「先生成文档 → TDD 驱动开发 → 最终 Multi-pass Review」三阶段闭环。

```markdown
$goal "研发面向复杂大工区矢量编辑的超低延迟性能提升引擎（M1-M5），攻坚 C++ 动态 R-Tree 空间索引、拓扑局部脏区增量重构、矢量自适应 LOD 批处理渲染以及跨语言零拷贝二进制 EditDelta 总线。严格恪守不做 100GB 全量栅格驻留内存的硬边界。全程先生成文档，再以 TDD/基准驱动，最后执行严苛 Review 闭环。"

$loop max_iterations=60 condition="docs_generated && perf_tdd_all_green && sla_targets_achieved && memory_leak_free && review_passed"

## 0. 任务元数据与资源边界（硬约束）

- **所属系统**：Paleo Workbench 古地理编图桌面系统（C++20 QGIS Render Bridge + PySide6）。
- **任务目标**：彻底消除大工区矢量编辑过程中的手势卡顿与拓扑停顿，将万级顶点吸附拾取延迟压减至 $<1\text{ ms}$、拓扑闭合验证降至 $<35\text{ ms}$、相带花纹缩放重绘稳定在 $60\text{ FPS}$（$<16\text{ ms}$），彻底消除 Python-C++ 跨语言 JSON 序列化抖动与 GC 停顿。
- **研发规模**：支持至少 4 小时全自主推演与开发，对标 10 亿+ tokens 研发交付量（含精细数据结构重构、微基准测试套件、内存/并发压力对抗审计）。
- **⛔ 业务范围硬边界（绝对红线）**：
  - **不做地质整体 100GB 栅格驻留内存方案！** 严禁引入任何暴力将全局高精度大体积栅格/地震体全量加载进内存的虚假方案。
  - 核心发力点必须百分之百聚焦在**复杂大尺度矢量要素编辑、局部增量空间索引、视口瓦片化与零拷贝内存总线**上。
- **⛔ 编译与并发资源硬约束**：
  1. **最多只能启用 3 个 subagents**（严禁任何时刻同时超过 3 个 subagent 运行，防止并行编译挤爆 CPU 与内存）。
  2. **C++ 编译并发限制**：编译 `native/qgis_render_bridge` 时强制 `CMAKE_BUILD_PARALLEL_LEVEL=2`，严格使用 Ninja。
  3. **环境隔离**：在主仓库同级目录建立独立 worktree `../paleo-workbench-vector-perf`，切入独立分支 `feat/vector-perf-increment`。
  4. **代码纯洁性**：遵守 `CLAUDE.md` 与 Karpathy Guidelines，保持原有对外 API 兼容性，采用内部加速替换策略。

---

## 1. 启用的 Skills 与协作规范

请按需自动调用以下 skills：
- `planning-with-files`：所有技术基准、性能数据、架构 RFC 与决策实时记录至 `docs/development/vector-perf-increment/`。
- `matt` / `gstack`：用于精细性能优化提交管理、Git 分支守卫与 PR 收尾。
- `wayfinder`：将复杂空间算法优化点分解为明确的性能 ticket，杜绝无休止的过早优化。
- `tdd`：基准先行（Benchmark First），先写出具有可重复测量精度的基准测试断言（断言当前基线红灯/超时），再实现优化直到绿灯。
- `code-review`：针对 C++ 内存布局、SIMD 指令集兼容性、多线程锁争用进行专家级双轴审查（$\le 2$ 个 subagents）。

---

## 2. 三阶段开发流转协议（Document-First → TDD → Review）

```
┌────────────────────────────────────────────────────────────────────────┐
│ 阶段一：先生成文档 (Documentation First)                                │
│   └─ 00-decisions.md / 01-perf-baseline.md                             │
│   └─ 02-spatial-index-and-delta-design.md / 03-tdd-benchmark-plan.md   │
│   └─ 04-known-limitations.md                                           │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段二：TDD / 基准驱动开发 (TDD & Benchmark-Driven)                    │
│   └─ Ticket 1: C++ 动态 R-Tree / BVH 空间索引核 (SpatialIndexCore)     │
│   └─ Ticket 2: 局部脏区拓扑增量计算 (Dirty Bounding Box Topo Engine)   │
│   └─ Ticket 3: 屏幕空间自适应矢量 LOD 化简 (Visvalingam Decimator)     │
│   └─ Ticket 4: 地质相带花纹纹理图集与批渲染 (Texture Atlas & Instancing)│
│   └─ Ticket 5: 跨语言零拷贝二进制 EditDelta 总线 (Zero-Copy FFI Ring)   │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段三：最后 Review 与 10 万顶点极限压测 (Review & Stress Audit)       │
│   └─ 100,000 顶点编辑压测 + 72小时连续操作 0 内存增长测试              │
│   └─ 达到 SLA 指标 + 04-sla-verification-report.md 验收产出与 PR 收尾   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 阶段一：先生成文档（必须首先落地，严禁跳过）

在开始编写代码前，必须在 `docs/development/vector-perf-increment/` 目录下创建并维护以下 5 份结构化性能工程文档：

1. `00-decisions.md`：记录所有算法选型决策（如 R-Tree vs BVH 选型、共享内存内存布局对齐规范），并详细说明为什么拒绝全量 100G 栅格方案的物理机理论证。
2. `01-perf-baseline.md`：**先量化现状！** 编写测试脚本实测当前基线在 1,000 / 10,000 / 50,000 顶点下的真实耗时（吸附拾取延迟、全量几何检查延迟、渲染重绘 FPS、FFI 序列化开销）。
3. `02-spatial-index-and-delta-design.md`：详述 C++ 动态 R-Tree 树高平衡策略、局部脏区裁剪边界判定、二进制 POD 紧凑结构体内存布局。
4. `03-tdd-benchmark-plan.md`：详细罗列每个 Ticket 的基准测试用例、断言 SLA 指标及回归钉设计。
5. `04-known-limitations.md`：明确记录本期边界（如仅加速二维平面坐标系，不涉及非流形网格等）。

---

## 4. 阶段二：TDD 驱动开发（红绿循环，逐 Ticket 推进）

每个 Ticket 严格执行：**写基准/失败测试（Red）→ 最小实现（Green）→ 重构优化（Refactor）→ 单一 Atomic Git Commit**。

### Ticket 1：C++ 原生动态 R-Tree 空间索引核 (`SpatialIndexCore`)
- **文件定位**：
  - 新建 `native/qgis_render_bridge/src/spatial_index_core.hpp` / `.cpp`
  - 重构 `native/qgis_render_bridge/src/edit_tools.cpp`（替换第 306 行的 `verticesNear` 线性遍历）
- **契约要求**：
  - 采用 R-Tree 空间索引管理编辑图层的顶点与边段。监听图层编辑事务，支持 $O(\log N)$ 节点插入、删除与最近邻（KNN）查询。
  - **SLA 门禁**：在 20,000 个多边形顶点场景下，单次鼠标移动的最近顶点吸附判定耗时从现有的 $25\text{ ms}$ 骤降至 $< 1.0\text{ ms}$。
  - **TDD 先行**：编写 `tests/perf/test_spatial_index_benchmarks.py`，预置 50,000 点网格，断言拾取耗时与正确性。

### Ticket 2：局部脏区拓扑增量计算引擎 (`DirtyBoxTopologicalCore`)
- **文件定位**：
  - 新建 `native/qgis_render_bridge/src/incremental_topology.cpp`
  - 修改 `native/qgis_render_bridge/src/map_stack_service.cpp`
- **契约要求**：
  - 废除全图层全要素扫描校验机制。将手势编辑影响域限制为：操作要素外包矩形扩大 $2\times \text{tolerance}$ 的局部脏区（Dirty Bounding Box）。
  - 仅提取与脏区相交的多边形环段，在隔离局部空间内完成相交证明与闭合验证，随后以拓扑补丁（Patch）合入全局镜像。
  - **SLA 门禁**：单次节点移动后的拓扑有效性验证从现有的 $300\sim 1200\text{ ms}$ 降至 $< 35\text{ ms}$。
  - **TDD 先行**：编写 `tests/perf/test_incremental_topology_bench.py`，验证局部计算与全量计算在数学证明上的 100% 等价性。

### Ticket 3：屏幕空间自适应矢量 LOD 动态化简 (`AdaptiveVectorLOD`)
- **文件定位**：
  - 新建 `geo-viz-engine/native/map_edit_core/src/vector_lod.cpp`
  - 修改 `paleo_workbench/mapping/map_render_backend.py`
- **契约要求**：
  - 基于视口缩放比例（Map Scale/DPI），采用 Visvalingam-Whyatt 算法对密集体等厚线、蜿蜒古岸线进行动态几何化简，剔除屏幕像素误差范围内的冗余顶点。
  - 维持地质拓扑形态特征点不丢失（极值点、拐点严格保留）。
  - **TDD 先行**：编写测试验证大比例尺下化简结果不失真，小比例尺下顶点数量下降 80%+。

### Ticket 4：地质相带花纹纹理图集与 GPU 批处理渲染 (`FaciesTextureAtlas`)
- **文件定位**：
  - 修改 `paleo_workbench/mapping/facies_brush_cache.py`
  - 新建 `native/qgis_render_bridge/src/texture_atlas.cpp`
- **契约要求**：
  - 将 `assets/patterns/facies/*.svg` 所有地质填充矢量花纹在初始化时动态烘焙至单一 GPU Texture Atlas。
  - 在相带多边形填充绘制时，以 Instanced Quad 批处理提交绘制调用（Draw Calls），平移和缩放过程重绘延迟从 $100\text{ ms}+$ 压减至 $< 16\text{ ms}$（稳定 $60\text{ FPS}$）。
  - **TDD 先行**：编写无头 QPainter 渲染帧率压测脚本，断言连贯缩放不卡顿。

### Ticket 5：跨语言零拷贝二进制 EditDelta 总线 (`ZeroCopyDeltaBus`)
- **文件定位**：
  - 新建 `native/qgis_render_bridge/src/edit_delta_pod.hpp`
  - 修改 `native/qgis_render_bridge/src/bindings.cpp`
  - 修改 `paleo_workbench/mapping/edit_delta.py`
- **契约要求**：
  - 彻底废除 Python 与 C++ 桥之间编辑手势与坐标更新的 JSON 字符串拼装与解析通道。
  - 定义紧凑 64 字节对齐的 C-POD 结构体，通过 pybind11 `py::buffer_protocol` / Arrow 共享内存环直接映射投递事件。
  - 彻底消除 FFI 频繁通信触发的 Python 内存碎片与垃圾回收（GC）偶发卡顿。
  - **TDD 先行**：编写每秒 10,000 次高频事件压测用例，断言 Python 端内存分配为 0。

---

## 5. 阶段三：最后 Review 与 10 万顶点极限压测闭环

优化开发完成后，**必须启动严格的多轮 Review、内存泄漏审计与极端压力测试**（并发 subagents $\le 2$）：

1. **Standards 性能与并发审查**：
   - 检查 C++ 动态空间索引在多线程读写下的互斥锁竞争，验证读写锁（`std::shared_mutex`）读多写少下的无等待路径。
   - 检查共享内存缓冲区的越界保护与内存对齐边界。
2. **100,000 顶点极端地质底图标杆压测**：
   - 生成包含 100,000 个顶点、2,000 个相带多边形、500 条断裂线的极端复杂工区。
   - 连续执行 2,000 次移动、框选、吸附与撤销重做操作，连续监测内存占用：断言 72 小时压力下无任何内存线性增长（Zero-leak），GC 停顿时间恒为 0。
3. **最终 SLA 验收报告产出**：
   - 对比 `01-perf-baseline.md` 与最终测量结果，在 `docs/development/vector-perf-increment/04-sla-verification-report.md` 中输出详尽的 Before/After 性能矩阵。
   - 使用 `gstack` 规范收拢提交，生成生产级 PR。
```
