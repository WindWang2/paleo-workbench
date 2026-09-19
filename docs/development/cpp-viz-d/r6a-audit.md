# VIZ-D R6a 审计门 — 地震基础件逐文件等价性结论

基线：`origin/main` f0af9d4e（2026-09-19）；Python 冻结源 `geo-viz-engine@08851951`（submodule gitlink）。
审计范围：完成计划 §2 R6a 列出的 10 个文件。结论分 **COVERED / PARTIAL / GAP**；本线**只补真实缺口**，已覆盖项一律标 legacy reference 不迁。

## 逐文件结论

| # | Python 文件 (LOC) | 结论 | C++ 等价落点（证据） | 备注 |
|---|---|---|---|---|
| 1 | chunked.py (881) | PARTIAL | `libs/seismic_io` `tile_read.hpp:57-73`（`read_voxel_window` 半开窗读取 parity，头注释 :9-11 点名）、`segy_layout` inspect、`seismic_service/tiled_volume.cpp:86-117`（相邻面共享 tile，不整卷复制）、`volume_service` O(1) open | zarr 后端被 PWBVOL1 架构性替代（`seismic_volume.hpp:4-7` 预留 chunked 后端）。**缺口 A1**：`read_arbitrary_line`/`sample_polyline_slice` CPU parity —— 本线补（gpu_ops CPU parity 是计划显式要求） |
| 2 | workers.py (577) | PARTIAL | `libs/job_runtime`（CONV-30 七态机）；SEG-Y 导入 `main_window.cpp:2518` + 5ms cancel 桥；`SliceReadWorker` 语义 = `slice_controller.cpp:74-132`（latest-wins、generation/epoch 迟到丢弃、失败诊断）；shutdown = `job_scheduler.hpp:122-133` | preview 降采样体（128³ 预算）在流式架构下过时不迁；synthetic demo 为测试数据（fixture 替代）。**缺口 A2**：`_PREFETCH_OFFSETS=(1,-1,2,-2)`（time 轴跳过）无等价 —— 本线在 SliceController 内补（计数上限 LRU 预算不变） |
| 3 | preview_widget.py (528) | PARTIAL | `libs/ui_pages_preview/qt/seismic_slice_preview_widget`（UI-07 移植，源是 `paleo_workbench/ui/pages/` 同名文件，非本文件）| 本文件的 80ms 防抖/异步读/prefetch(32) 在该 widget 中未复制（同步 GUI 线程读，`seismic_slice_preview_widget.cpp:204-222`）。**缺口 A3**：预览页异步读路径 —— 本线以新 presenter（seismic 专用文件）补，不改 UI-07 冻结 widget |
| 4 | vram_cache.py (353) | COVERED(适配) | `seismic_io/tile_cache.{hpp,cpp}`：字节预算 LRU、`set_budget` 收缩即逐出（`tile_cache.cpp:109-123`，测试 `tile_cache_test.cpp:66-81`）、超预算 tile 服务但不缓存（:50-57） | 无 GL 纹理账本属架构差异（C++ 光栅 QImage）；预算 per-volume 而非进程全局，`volume_service.hpp:13-16` 已声明前提（平台一次一体）。不迁 |
| 5 | chunked_worker.py (276) | PARTIAL | 调度半 = `slice_controller.cpp:74-132`（请求循环/latest-wins/open 一次带错误上报） | LOD 服务（`LodPolicy.select_lod`、50ms idle refine）与 `DirectionalPrefetcher` 依赖 LOD 层级——C++ 无 LOD 后端（见 #6）。`ArbitraryLineWorker` 依赖 A1，随 A1 补数值半 |
| 6 | lod.py (189) | GAP（裁决：不迁） | 无任何 C++ LOD | LOD 金字塔服务于 chunked/zarr 预览体架构；C++ 为全分辨率 tile 流式（计划 §2 "不重造加载框架"）。**能力声明**：CPU 全分辨率读取已满足交互（16ms 防抖 + coalescing）；LOD 金字塔待 #148 chunked 后端落地再评估，不在本线承诺。方向性 prefetch 的可移植部分并入 A2 |
| 7 | cache.py (180) | COVERED(适配) | `tile_cache`（字节预算 + 可选条目上限）+ `slice_controller` 面 LRU（计数上限，键 (epoch,axis,index)） | 全局 1GiB 跨实例账本被 per-volume 预算替代（同 #4 前提）。env `PWB_SEISMIC_TILE_CACHE_BYTES`（`volume_service.cpp:9-22`）。不迁 |
| 8 | gpu_ops.py (154) | PARTIAL | `slice_volume_gpu` → `ISeismicVolume::read_slice`（`seismic_volume.hpp:74-83`，且不整卷复制） | GPU 路径明确不迁（计划 §2）。**缺口 A1（同 chunked）**：`sample_polyline_slice` CPU parity 无任何 C++ —— 本线补 |
| 9 | profile_widget.py (168) | PARTIAL | VD 索引显示 = `seismic_viewer/seismic_slice_widget` + `color_maps`；`reset_view` 有 | wiggle/极性/增益/percentile 裁剪为 R6 范围（本线主任务，见 v5-product-delta.md）。轴刻度/标注、跨面板 crosshair 联动、井/断层路径 overlay、annotation 记录为遗留能力，本线补 horizon 拾取 overlay；其余如实声明未迁 |
| 10 | seismic_view.py (2563) | PARTIAL | 交互切片核心已覆盖：debounce/缓存优先/迟到丢弃/colormap/缩放平移/选择扇出/物理坐标（`seismic_slice_widget` + `slice_controller`，接线 `main_window.cpp:463-467`） | 其余面归属：面板级 2D 属性显示 → 属性核已在 `seismic_attributes`（10 核），面板显示路径属 ui_wellseis 显示管线（#1394 seam），本线经 crossplot 数据半提供抽验入口；任意线 curtain 3D 呈现 → V4/C 线；well-tie → R4/B 线；3D 体渲染 → R5/C 线；slice 导出与视图态持久化 → 本线不承诺（记录为遗留）；horizon 拾取/管理 → 本线补（R6） |

## 计划断言核验

| 计划断言（§V5 前置审计门） | 核验 |
|---|---|
| chunked → seismic_io tile_read + TileCache | **真**（窗口读 + 字节预算缓存核心）；任意线/LOD 例外如上 |
| workers → job_runtime/job center | **真**（导入/属性/切片读三链都有）；prefetch 例外（A2 本线补） |
| preview_widget → seismic_slice_preview_widget 已替代 | **部分**：该 widget 是 UI-07 另一源文件的移植，同步 I/O；异步路径本线以新 presenter 补（A3） |
| seismic_view → seismic_viewer 已替代 | **部分**：单面交互查看核心已替代；4 面板/属性/任意线/horizon/3D/well-tie 归各批次（本线补 horizon + 显示差量） |
| profile_widget → seismic_viewer 已替代 | **部分**：仅 VD 索引显示；wiggle/极性/增益/裁剪为本线主差量 |

## 本线纳入的缺口（全部关闭，见 ledger）

- **A1** 任意线/折线采样 CPU parity（`sample_polyline_slice` scipy order=1 constant 语义 + `read_arbitrary_line` 双线性 gather 语义）→ `libs/seismic_viewer/display_core`
- **A2** SliceController 相邻面 prefetch（±1/±2，sample 轴跳过；计数上限不变、取消/切体安全）
- **A3** 预览页 seismic 异步 presenter（世代守卫 + queued GUI 更新；不改 UI-07 冻结 widget）

## 明确不迁（诚实能力声明）

- LOD 金字塔（`lod.py` 全部、`chunked.build_lod`）：架构性替代为全分辨率 tile 流式；无消费方。
- GPU/CuPy 路径：计划排除；CPU parity 见 A1。
- zarr 后端：PWBVOL1 替代。
- vram pin/release、GL 纹理释放回调：无 GL 渲染面。
- preview 128³ 降采样体、synthetic demo 生成器：测试 fixture 替代。
- 面板级 2D 属性/RGB 融合显示：属性核已迁（`seismic_attributes`），面板呈现属 ui_wellseis 显示管线与 V4/C 线场景；本线提供 crossplot 数据半（envelope/inst-freq 复用既有核）。
- slice 导出 npy/csv/png、seismic 视图态持久化：遗留未迁，PR 如实列出。
