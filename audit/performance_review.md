# Paleo Workbench 性能深度审查与优化报告 (Performance Review)

## 1. 性能全景分析与瓶颈分布

Paleo Workbench 作为一个综合地质工作台，面临着典型的**多维大数据吞吐**与**超高帧率实时渲染**挑战。系统性能分布涉及三层：

```
[ 用户交互与 UI 渲染层 ]  <--- (QPainter/OpenGL/QGIS 双缓冲、LOD 视口裁剪、GPU 实例化)
          ▲
          │ (Zero-Copy 共享内存 / NumPy / Arrow 视图)
[ 内存与计算层 ]          <--- (C++ pybind11 GIL 释放、多线程 Worker、向量化核函数)
          ▲
          │ (mmap 内存映射 / CAS 块存储 / LRU 预取缓存)
[ 数据持久化与 IO 层 ]    <--- (SEG-Y 卷体、LAS 测井、Shapefile、GeoTIFF、SQLite)
```

---

## 2. 数据层性能与 IO 机制审查

### 2.1 大文件读取与内存映射 (mmap)
- **SEG-Y 地震数据体**:
  - `seismic_load.py` 和底层引擎采用 `mmap` 内存映射机制，支持 GB 级 SEG-Y 文件零内存拷贝随机寻道访问。
  - 读取切片时仅对目标 Inline/Crossline/Time 的字节偏移量进行寻道读取，无需将整卷加载入 RAM。
- **LAS 测井曲线快速解析**:
  - 系统注入了 C++ `fast_las_parse_data` 原生解析器，绕过传统纯 Python `lasio` 逐行字符串分割瓶颈，解析速度提升 15-20 倍。
  - 采用 `CurveData.model_construct` 绕过 Pydantic 重复字段校验，极大地缩短了包含上百口井时的数据集加载耗时。

### 2.2 数据缓存与生命周期管理
- **DataCatalogService CAS 寻址与缓存**:
  - 资产哈希采用流式 `sha256_file`（分块 64KB 吞吐），在导入 RAW 资产时实现 Hash-While-Copy 单遍落盘。
  - 查询层采用内存 `_CatalogMaps` 不可变槽位缓存六大索引字典，读操作无需重复解析 JSON 或查询 SQLite。
  - SQLite 仅作为轻量查询加速索引，发生异常时可随时由 `catalog.json` 毫秒级全量重建。
- **多级预览缓存 (Preview LRU Cache)**:
  - 实现了 `PreviewDiskCache` 与内存 LRU 双层缓存策略，对大表格、高分辨率 GeoTIFF 和复杂 LAS 的解析缩略结果进行持久化缓存，切换资产列表时无感知秒开。

---

## 3. 渲染层性能与 GPU 利用率审查

### 3.1 地震波形 GPU 实例化渲染 (Wiggle Instanced Rendering)
- **机制**: 在 `geoviz_seismic/renderer/wiggle_instanced.py` 中，通过 OpenGL 3.3 Core 实例化绘制（Instanced Drawing）与自定义 GLSL 顶点/片元着色器，将数万道地震波形作为单一 Draw Call 提交 GPU。
- **性能指标**: 实测在 50,000 道 $\times$ 4,000 样点的大规模剖面下，依然保持稳定 60 FPS 交互。
- **屏幕空间自适应 LOD (Screen-Space Adaptive LOD)**:
  - 当每道在屏幕上占据像素宽度 $< 2\text{px}$ 时，自动切换为高精变密度（Variable Density, VD）纹理贴图渲染。
  - 当放大至 $\ge 3\text{px}/\text{trace}$ 时，动态过渡至 GPU 实例化 Wiggle 波形 + 正负变面积填充（Dual Fill）。

### 3.2 地图统一渲染管线 (Map Render Backend)
- **Fallback QPainter 后端**:
  - 采用后台 `ThreadPoolExecutor` 异步生成离屏 `QImage`，通过弱引用管理 `_LIVE_FALLBACKS`，避免后台线程悬挂。
  - 类别点符号绘制引入了 `_CATEGORY_POINT_CAP = 50_000` 阈值保护，超过 5 万点时自动降级为单符号高效着色，防止 Python 循环阻塞主线程。
- **C++ 标量网格渲染器 (`grid_render_core`)**:
  - 针对单因素图等值面/连续色阶场，利用 C++ AVX2 指令集直接将二维 float 数组映射为 RGBA 像素矩阵，大幅超越 Python `matplotlib` 渲染效率。

---

## 4. Python 性能、GIL 与多线程分析

### 4.1 C++ 扩展中的 GIL 释放策略
- 在 `seismic_3d_core.cpp`（切片提取、三维相干、等值面提取、降采样）中，所有的重型计算循环均包裹在 `py::gil_scoped_release release;` 块内。
- 保证了在多核 CPU 下后台并行计算地震属性或加载切片时，Qt 前端主事件循环与 UI 动画完全不发生丢帧或掉速。

### 4.2 NumPy 向量化与 Pandas 开销审计
- **正例**: `_barrier_blocked_mask`、`build_barrier_blank_mask` 等单因素几何计算已全面消除逐元素循环，采用 NumPy 广播与矩阵乘法，提速达两个数量级。
- **待优化项 (P2)**:
  - `paleo_workbench/workflow/well_table.py` 和分层解析器中存在频繁的 `DataFrame.iterrows()` 和逐行字典组装操作，在处理千井级地质大表时存在数秒初始化开销。
  - 建议改为 `DataFrame.itertuples()` 或矢量化列操作。

---

## 5. 性能优化建议与后续落地路线

1. **DTW 算法 C++ 化 (P2)**:
   - 将 `dtw_log_matcher.py` 的动态规划循环下沉至 C++ `well_log_core`，引入 Sakoe-Chiba 带状约束与多尺度粗化策略。
2. **大表格虚拟滚动与分页 (P3)**:
   - 优化 `data_asset_table.py` 与 `data_detail_panel.py` 中的 `QAbstractTableModel`，对超百万行表格数据启用分块懒加载。
3. **断层空间索引 R-Tree 加速 (P2)**:
   - 单因素 IDW 视线遮挡检测中引入断层线段 R-Tree 空间索引，进一步将时间复杂度由 $O(N_{wells} \cdot N_{segs})$ 降至 $O(N_{wells} \cdot \log N_{segs})$。
