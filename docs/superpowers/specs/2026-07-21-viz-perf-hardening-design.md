# 测井与地震可视化性能加固（P4）设计

日期：2026-07-21
状态：已确认（头脑风暴后用户批准）
关联：`2026-07-21-cross-well-correlation-optimization-design.md`（连井对比 P1–P3，已完成）

## 背景

对 `well_log_core` 与 `seismic_3d_core` 两个 C++ 扩展及其调用链的审查结论：

- C++ 核心本身高效（GIL 释放基本到位），但**集成粒度错误**：测井曲线数据以 Python list 存储，每次重绘 list→ndarray→C++→list→ndarray 封送占该环节耗时约 98%，C++ 核心只占约 2%。
- 地震切片的帧耗时主体在 geo-viz 引擎侧：GUI 线程 segyio 磁盘读（每跳 10–100ms+）、任一剖面变化重建全部 3 个 3D 切片平面、切片缓存按数量计（可达 GB 级）。
- 两个原生函数有问题：`marching_cubes_3d` 算法错误（点汤非 MC）且无调用者；`compute_coherence_3d` 静默忽略 `sample_window` 且内层循环多算 w² 倍。
- 附带 bug：表头 min/max 每次重绘 O(n) 全扫描且 NaN 导致 `nan~nan` 显示；`_path_cache` 交互中永不命中；`_on_jump` 三连发信号互相覆盖致 2D 面板陈旧；`task_plan.md` "C++ 多线程"表述与实现（单线程）不符。

## 目标与范围

用户确认纳入全部四个包，并确认拆分：**P4 = 性能加固（本 spec）；P5 = marching_cubes 重写 + 等值面/相干性接入 3D 视图（另立，不在本 spec）**。

技术路线（用户确认）：
- 测井 ndarray 化走 **CurveTrack 内部改造**（`CurveData` 公共模型不动）。
- 地震切片走 **worker + 邻域预取 + 内存上限缓存**（不做全量预提取、不做 shader 方案）。

三个阶段，按风险从低到高排序，各自独立交付与回归：

| 阶段 | 内容 | 落点 |
|---|---|---|
| A 测井渲染通道 | CurveTrack ndarray 化 + 表头缓存（含 NaN bug）+ path cache 修复 + 预览解析器去 lasio + LAS C++ 解析器优化 | geo-viz-engine + workbench + well_log_core |
| B 地震切片交互 | 切片读取 worker + 预取 + 字节上限缓存 + read_timeslice 修复 + 3D 仅重建变化平面 + `_on_jump` bug + 预览控件修整 | geo-viz-engine（主）+ workbench 预览控件 |
| C coherence 修正 + 文档 | `compute_coherence_3d` 修正；crossover_fill 删除；task_plan 纠偏 | seismic_3d_core + well_log_core + 文档 |

**明确排除（P5 或放弃）**：marching_cubes 重写、等值面/相干性接入 3D 视图、shader 纹理采样、`CurveData` 模型改造、全量切片预提取。

## 阶段 A：测井渲染通道

1. **CurveTrack ndarray 化（核心）**：构造时 `_sorted_depths/_sorted_values` 存 float64 ndarray（仍从 `CurveData` list 构建，公共模型不变）；`_visible_data` 改 `np.searchsorted` 零拷贝视图；引擎 downsample 钩子协议升级为 **ndarray 进 ndarray 出**——直接更换协议并迁移唯一注入方 `paleo_workbench/viz/render_accel.py`（注入方只有一处，不做双协议兼容）；`paint_content` 消除重复 `np.array()` 与 Python 级 NaN 检查（改 `np.isfinite` 掩码分段）。
2. **表头 min/max 缓存 + NaN 修复**：构造时用 `np.nanmin/np.nanmax` 预计算每曲线范围字符串，重绘复用；修复 `nan~nan` 显示 bug。
3. **path cache 修复**：缓存键改量化键（曲线名 + pixel_height + 量化深度窗 + 轨道宽度），缓存抽稀后数组而非 QPainterPath；连续平移帧可命中，每帧只重建 ≤4k 点路径。
4. **预览解析器去 lasio**：`resources/preview_parsers/well_log_parsers.py` 表格预览改用 `fast_las_parse_data`（前 100 行），消除死 import。
5. **LAS C++ 解析器优化**：解析循环释放 GIL；`istringstream+stod` 改 `std::from_chars`（不可用时 strtod）；rows 改 flat vector 一次写入；`well_log_api.py` wrapper 消除签名不匹配时的整文件双重解析重试。

## 阶段 B：地震切片交互

1. **切片读取 worker（核心）**：geo-viz 侧新增 `SliceReadWorker`（QThread，复用 `SegyLoadWorker` 协作取消模式）：请求队列最新优先（拖拽丢弃过期请求）、当前 index ±2 邻域预取、结果信号回投 GUI 应用。GUI 立即显示上一帧并标记加载中。
2. **字节上限缓存**：切片 LRU 从按数量（50 张全分辨率）改为按字节上限（默认 512MB，可配）+ 预取联动。
3. **`read_timeslice` 回退修复**：消除逐 inline O(n) 读盘循环，改单次跨步扫描构建或 worker 加载期缓存。
4. **3D 仅重建变化平面 + `_on_jump` 修复**：`_update_slice_planes` 按轴拆分，仅位置变化的平面重新提取+colormap+上传；`_on_jump` 合并为单次更新，保证 3 个 2D 面板一致刷新。
5. **预览控件修整**：滑杆 80ms 防抖；resize 只重缩放缓存 pixmap；256 色表 NumPy 构建（去 matplotlib import）；`norm.T` 拷贝由 C++ 直接输出转置布局。

## 阶段 C：coherence 修正 + 文档

- `compute_coherence_3d`：`sample_window` 生效（垂直窗参与相干计算）；内层改 running-sum/按列计算消除 w² 冗余；保持 GIL 释放；更新 C++/Python parity 测试覆盖新参数语义。
- `generate_crossover_fill`：无调用者且算法不正确——删除函数、pybind 绑定与测试（git 历史可恢复），`well_log_api.py` 同步移除。
- `task_plan.md` Phase 9 "C++ 多线程"表述纠偏为"单线程 + GIL 释放"；`progress.md` 如实记录本阶段。

## 测试策略

- 阶段 A：抽稀输出与现状逐点一致的渲染等价测试；表头 NaN 用例；path cache 命中测试；LAS C++/Python parity 全量保持。
- 阶段 B：worker 请求合并/取消单测；缓存字节上限测试；`_on_jump` 三面板一致性回归；read_timeslice 等价性测试。
- 阶段 C：coherence parity（含非默认 sample_window 用例）。
- 每阶段双仓库全量回归（基线：workbench 1153 全绿；引擎 77+ 全绿，3 个 P1 已确认既有失败除外）。
- 用 `tests/perf/` 现有工具记录关键路径 before/after 数字（测井整幅重绘、LAS 加载、地震切片跳变），写入 `progress.md`。

## 非目标（YAGNI）

- marching_cubes 重写与 3D 等值面/相干性接入（P5）。
- shader 纹理采样切片、全量切片预提取、`CurveData` 模型改造。
- SEGY 重复解析去重（预览解析器 vs SegyLoadWorker）——记录为后续候选，本阶段不动。
- 不引入新第三方依赖。
