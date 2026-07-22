# P5：Marching Cubes 重写 + 等值面/相干性接入 3D 视图 设计

日期：2026-07-22
状态：已确认（头脑风暴后用户逐节批准）
关联：`2026-07-21-viz-perf-hardening-design.md`（P4，已完成；P5 为其明确推迟项）

## 背景

- `marching_cubes_3d` 现实现是"点汤"：voxel ≥ isovalue 即出顶点、每 3 个连续顶点硬凑三角形，C++（`native/seismic_3d_core/src/seismic_3d_core.cpp`）与 Python 降级路径（`paleo_workbench/viz/seismic_3d_api.py`）皆然；无任何生产调用者。
- 引擎 3D 渲染为 pyqtgraph.opengl（`geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/renderer_3d.py`），层位已以 `gl.GLMeshItem` mesh 渲染（`add_horizon`），等值面可完全复用该模式。引擎无 pyvista/vtk/skimage 依赖。
- 引擎已有经测试的 C3 特征结构相干性 `attributes.compute_coherence_c3`，但属性下拉（`attribute_pipeline.ATTRIBUTES`）未收录；workbench 另有 semblance 版 `compute_coherence_3d`（P4-C 已修），保持现状不进 UI。
- 依赖方向为 workbench → 引擎，引擎不能 import workbench 的 C++ 扩展；P4-A 已建立"引擎出钩子、workbench 启动注入"模式（`render_accel.py` 注入 `minmax_downsample`）。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| MC 实现路线 | C++ 自研 Marching Tetrahedra（水密、无外部查找表），不引新依赖 |
| 等值面交互范围 | 仅当前振幅体；SeismicView 工具栏控件组 |
| 相干性实现 | 引擎 C3 接入属性管线；workbench semblance 版不进 UI |
| 跨仓库架构 | 注入模式（引擎 API + 钩子，workbench 启动注入 C++ MC） |

## 范围

### 1. C++ Marching Cubes 重写（workbench 仓库）

- 替换 `seismic_3d_core.cpp` 点汤实现，签名不变：`(volume: float32 3D, isovalue: float) -> (verts float32 [N,3], faces int32 [M,3])`。
- Marching Tetrahedra：逐 cube 剖 6 四面体（主对角线分解，邻接面对角线一致，天然水密），棱上线性插值，法线统一朝外；计算段释放 GIL。
- 输出 voxel 索引坐标；`Renderer3D.set_isosurface` 内部按 volume spacing/origin 变换到物理坐标后叠加。
- 第一版不做顶点去重（YAGNI；128³ 体典型输出几十万三角形，可接受）。
- Python 保底：保留 skimage 可选路径作参考实现；删除点汤降级，无 C++ 且无 skimage 时抛 `ImportError`。

### 2. 引擎等值面渲染与 UI（geo-viz-engine）

- `Renderer3D.set_isosurface(verts, faces, color=(0.9, 0.5, 0.1, 0.8))`：`gl.GLMeshItem`（`shader='shaded'`），存 `_isosurface_item`，重复调用替换旧 item；`clear_isosurface()` 移除；`_clear_visuals` 一并清理。
- 等值面在"正交切片/三维体"两种 render mode 下均显示，独立开关控制。
- `Renderer3D.set_isosurface_extractor(fn)` 注入钩子：`fn(volume, isovalue) -> (verts, faces)`，未注入为 `None`。
- SeismicView 工具栏：「等值面」checkbox + 阈值 `QDoubleSpinBox`（默认值为体积数据范围中点，范围取 volume min/max）。未注入 extractor 时 checkbox 禁用并 tooltip 说明。
- 勾选/改阈值 → 200ms 防抖（QTimer 单发，复用 P4-B 模式）→ 用 Renderer3D 当前 volume 同步提取（128³ C++ <50ms，无需 worker）→ `set_isosurface`；取消勾选 → `clear_isosurface`。
- 提取异常 → 清空等值面 + 复用现有错误提示通道；空 mesh（阈值超界）→ 静默清空不报错。

### 3. workbench 注入接线

- `paleo_workbench/viz/render_accel.py` 追加注入：向引擎 `set_isosurface_extractor` 注入 `seismic_3d_api.marching_cubes_3d`。
- facade 白名单 `GEOVIZ_PUBLIC_FACADE` 按既有流程扩展（若钩子经 `geoviz` 顶层导出）。

### 4. 相干性 C3 接入（geo-viz-engine）

- `attribute_pipeline.ATTRIBUTES` 新增「相干性(C3)」映射 `compute_coherence_c3`，随属性下拉自动出现；显示链路复用属性管线现状，不做特判。
- 实现时确认管线对 C3 输出 [0,1] 范围的归一化/colormap 行为与其他属性一致。

## 测试策略

- MC C++：现有形状/类型测试保持通过；新增语义测试——①半径 5 球体等值面顶点距球心 ∈ [4.5, 5.5]；②faces 索引合法；③封闭性（每条无向棱恰好被两个三角形共享，验证无孔洞）；④C++ vs skimage 仅验顶点数同量级、bbox 一致（表不同，不做逐点 parity）。
- 引擎：offscreen qtbot 下 set/clear 生命周期、重复替换、`_clear_visuals` 清理、防抖合并、未注入禁用、空 mesh 不报错。
- workbench：注入后控件可用且走 C++ 路径；模拟无扩展时降级链正确。
- C3：`labels()` 含新条目；合成断层体结果 ∈ [0,1]、形状一致。
- 双仓库全量回归（基线：workbench 1175 全绿；引擎 112 通过 +1 既有失败 `test_curve_track_viewport_culling` +1 skip）。

## 非目标（YAGNI）

- 等值面顶点去重/棱缓存、多数据源等值面（属性体/相干体）、透明度/颜色控件。
- worker 异步提取（同步 + 防抖足够）。
- workbench semblance 相干性的 UI 接入；pyvista/vtk/skimage 成为硬依赖。
- marching_cubes 输出坐标系变换（保持 voxel 索引坐标）。

## 文档

- `progress.md` 记 P5；`task_plan.md` 加 Phase 16。
