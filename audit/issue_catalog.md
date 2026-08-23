# Paleo Workbench 全系统缺陷与改进目录 (Issue Catalog)

本目录记录对 Paleo Workbench 全仓深度审计发现的所有结构性缺陷、性能瓶颈、功能盲区与架构演进需求。

---

## 目录索引

- [P0 级严重缺陷 (Critical)](#p0-级严重缺陷-critical)
  - [ISS-P0-001: DTWLogMatcher 在极端大曲线下的内存爆炸与超时卡死风险](#iss-p0-001)
  - [ISS-P0-002: Fallback 渲染器在超大点集下主线程事件循环阻塞](#iss-p0-002)
  - [ISS-P0-003: 拓扑多边形共边拖拽并发竞争导致的自相交崩溃隐患](#iss-p0-003)
- [P1 级架构重构 (Architecture)](#p1-级架构重构-architecture)
  - [ISS-P1-001: 缺少全局 AI Harness 与领域多 Agent 协同编排框架](#iss-p1-001)
  - [ISS-P1-002: 四大注册表 (Tool / Skill / Algorithm / Template) 机制缺失](#iss-p1-002)
  - [ISS-P1-003: 单因素插值输出与地图图层管线之间缺乏统一栅格图层抽象](#iss-p1-003)
- [P2 级性能优化 (Performance)](#p2-级性能优化-performance)
  - [ISS-P2-001: DTW 动态规划核心循环由 Python 解释执行缺乏 C++ 硬件加速](#iss-p2-001)
  - [ISS-P2-002: 单因素插值断层视线遮挡缺乏 R-Tree 空间索引导致大图耗时偏高](#iss-p2-002)
  - [ISS-P2-003: 地震切片数据多线程并发预取与 LRU 缓存淘汰效率不足](#iss-p2-003)
  - [ISS-P2-004: 测井表格数据模型在大规模井位下的全量组装性能开销](#iss-p2-004)
- [P3 级界面与体验 (UI/UX)](#p3-级界面与体验-uiux)
  - [ISS-P3-001: 缺少动态多主题切换 (Dark / Light / High-Contrast) 与高分屏微调](#iss-p3-001)
  - [ISS-P3-002: 缺少自由停靠浮动的 Dockable Workspace 与工作区预设](#iss-p3-002)
  - [ISS-P3-003: 拓扑编辑历史缺乏可视化 Undo/Redo 历史面板](#iss-p3-003)
- [P4 级功能增强 (Enhancement)](#p4-级功能增强-enhancement)
  - [ISS-P4-001: 构建声明式 Map Composer 地图排版与整饰要素系统](#iss-p4-001)
  - [ISS-P4-002: 单因素图自动生成等值线、相带多边形与统计图斑增强](#iss-p4-002)
  - [ISS-P4-003: 建立自动化 QA 质检规则与地质合理性自愈诊断器](#iss-p4-003)

---

## P0 级严重缺陷 (Critical)

### <a id="iss-p0-001"></a>ISS-P0-001: DTWLogMatcher 在极端大曲线下的内存爆炸与超时卡死风险
- **Title**: DTWLogMatcher 动态规划矩阵内存与计算边界加固
- **Category**: P0 Critical
- **Priority**: P0
- **Module**: `paleo_workbench.viz.dtw_log_matcher`
- **Problem**: 当两个测井曲线未降采样且长度均达到数万点时，$O(N \cdot M)$ 浮点矩阵分配可能消耗数 GB 内存，且 Python 双重循环将冻结进程数分钟。
- **Current Behavior**: 当前虽然存在 `_MAX_COST_CELLS = 1_000_000` 的保护，但对步长计算和退化输入（如全 NaN 曲线或单点曲线）缺乏弹性防线，异常情况下可能引发 `MemoryError` 或死循环。
- **Expected Behavior**: 引入严格的计算预算配额（Time/Memory Budget）、全异常状态安全截断、纯 Python 弹性降维与防御式回退。
- **Technical Analysis**: `DTWLogMatcher.match_curves` 需在分配 `cost_matrix` 前进行维度硬校验，支持自适应分块与 Sakoe-Chiba 带状约束，确保任何输入下耗时控制在 50ms 内。
- **Suggested Solution**: 增强 `dtw_log_matcher.py` 中的防御性分段降采样算法与输入矩阵维度硬上限。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p0-002"></a>ISS-P0-002: Fallback 渲染器在超大点集下主线程事件循环阻塞
- **Title**: MapRenderBackend 离屏渲染线程池优雅关闭与大点集分片渲染
- **Category**: P0 Critical
- **Priority**: P0
- **Module**: `paleo_workbench.mapping.map_render_backend`
- **Problem**: 在测试或快速切换视口时，未完成的后台渲染任务可能持有无效的 Qt 句柄，导致 Python 3.13 退出时发生段错误（Segfault）。
- **Current Behavior**: 虽然通过 `weakref.WeakSet` 记录了 live backends，但在高频连续拖拽时，过多排队的 Future 堆积占用线程池资源。
- **Expected Behavior**: 引入主动取消令牌（Cancellation Token）与渲染帧防抖节流（Debounce），在窗口析构时原子级关闭所有后台 Worker。
- **Technical Analysis**: 利用 `threading.Event` 标记弃用帧，在新帧到达时立刻中断旧帧绘制循环。
- **Suggested Solution**: 在 `FallbackMapRenderBackend` 中完善帧取消逻辑与资源回收守卫。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p0-003"></a>ISS-P0-003: 拓扑多边形共边拖拽并发竞争导致的自相交崩溃隐患
- **Title**: FeatureEditor 顶点编辑事务并发原子性与拓扑自愈回滚
- **Category**: P0 Critical
- **Priority**: P0
- **Module**: `paleo_workbench.mapping.feature_editor` / `topology`
- **Problem**: 在编辑相邻共边多边形时，若用户快速拖拽产生蝴蝶形自相交（Bow-tie self-intersection），偶发抛出未捕获的拓扑异常导致 UI 崩溃。
- **Current Behavior**: 发生拓扑异常时，状态可能处于部分更新状态，后续的撤销操作会导致多边形顶点丢失。
- **Expected Behavior**: 事务机制严格保证“全成功或全回滚”，并在检测到自相交时自动应用缓冲区自愈修复（Buffer(0) repair）。
- **Technical Analysis**: 在 `FeatureEditor.move_selected_vertex` 中引入原子快照机制，在 Shapely 拓扑校验失败时自动触发修复策略。
- **Suggested Solution**: 完善 `topology.py` 中的 `repair_invalid_polygon` 并增强 `FeatureEditor` 事务安全。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

---

## P1 级架构重构 (Architecture)

### <a id="iss-p1-001"></a>ISS-P1-001: 缺少全局 AI Harness 与领域多 Agent 协同编排框架
- **Title**: 构建 Paleo AI GIS Harness 核心与专业智能体集群
- **Category**: P1 Architecture
- **Priority**: P1
- **Module**: `paleo_workbench.agent`
- **Problem**: 系统当前缺乏将大模型意图解析、任务图规划与领域工具执行串联的完整 AI Harness。
- **Current Behavior**: 仅有固定的 UI 按钮触发本地简单启发式模型，无法通过自然语言或高级指令完成自动化复合分析。
- **Expected Behavior**: 提供统一的 `PaleoAIHarness`，内置 Planner 与 `DataAgent`、`GISAgent`、`WellAgent`、`SeismicAgent`、`CartoAgent`、`VizAgent`、`QAAgent`、`ResultAgent` 八大专业智能体。
- **Technical Analysis**: 基于 DAG 任务图模式构建 Agent 协作流水线，支持流式日志、中间状态缓存与断点续跑。
- **Suggested Solution**: 在 `paleo_workbench/agent/` 下实现完整的 Harness、Planner、BaseAgent 与专业 Agents。
- **Estimated Complexity**: L (Large)
- **Dependencies**: ISS-P1-002

### <a id="iss-p1-002"></a>ISS-P1-002: 四大注册表 (Tool / Skill / Algorithm / Template) 机制缺失
- **Title**: 实现 ToolRegistry、SkillRegistry、AlgorithmRegistry、TemplateRegistry
- **Category**: P1 Architecture
- **Priority**: P1
- **Module**: `paleo_workbench.agent.registries`
- **Problem**: 系统中的算法能力、业务脚本、制图模板与执行工具缺乏统一注册中心，智能体无法动态发现与调用。
- **Current Behavior**: 工具调用硬编码在各模块内部，参数校验与文档元数据不统一。
- **Expected Behavior**: 建立统一的元数据注册中心，支持通过装饰器自动注册工具，输出标准 JSON Schema，支持技能编排与模板复用。
- **Technical Analysis**: 构建基于类型注解与 Pydantic 的反射式注册系统，支持工具自动发现与权限控制。
- **Suggested Solution**: 在 `paleo_workbench/agent/registries/` 实现四大注册表及对应的工具集。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p1-003"></a>ISS-P1-003: 单因素插值输出与地图图层管线之间缺乏统一栅格图层抽象
- **Title**: 统一单因素标量栅格层与 QGIS 渲染管线 (ScalarRasterLayer 规范化)
- **Category**: P1 Architecture
- **Priority**: P1
- **Module**: `paleo_workbench.mapping` / `paleo_workbench.workflow`
- **Problem**: `haiyou_constrained_idw` 输出的标量网格为纯 NumPy 矩阵，与 `mapping` 模块的图层管理体系割裂。
- **Current Behavior**: 需要经过多层私有数据格式转换才能在地图画布上显示，无法直接享受图层混合模式、透明度调节与图例联动。
- **Expected Behavior**: 定义标准 `ScalarRasterLayer`，携带仿射变换 GeoTransform、CRS、数据空值掩码与色标配置，直接接入 `MapRenderBackend`。
- **Technical Analysis**: 统一 `MapLayerSnapshot` 对 `layer_type="raster"` 的定义与离屏光栅化流程。
- **Suggested Solution**: 增强 `scalar_raster_mirror.py` 与 `map_render_backend.py` 中的栅格图层渲染通路。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

---

## P2 级性能优化 (Performance)

### <a id="iss-p2-001"></a>ISS-P2-001: DTW 动态规划核心循环由 Python 解释执行缺乏 C++ 硬件加速
- **Title**: 测井 DTW 动态规划算法 C++ 原生加速与向量化优化
- **Category**: P2 Performance
- **Priority**: P2
- **Module**: `native.well_log_core` / `paleo_workbench.viz.dtw_log_matcher`
- **Problem**: DTW 距离矩阵计算在 Python 解释器内运行，耗时偏长。
- **Current Behavior**: 大井段对比时存在可感知的延迟。
- **Expected Behavior**: 在 `well_log_core` 中提供 C++ 动态规划核函数，耗时缩短 50 倍以上，同时保持 Python 回退一致性。
- **Technical Analysis**: 利用 C++ 单精度/双精度滑动窗口优化 DP 递推，并通过 `py::gil_scoped_release` 释放 GIL。
- **Suggested Solution**: 扩展 `well_log_core.cpp` 与 `native_backend.py`，无缝集成 DTW 核心。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p2-002"></a>ISS-P2-002: 单因素插值断层视线遮挡缺乏 R-Tree 空间索引导致大图耗时偏高
- **Title**: 单因素 IDW 断层遮挡检测 R-Tree 空间索引加速
- **Category**: P2 Performance
- **Priority**: P2
- **Module**: `paleo_workbench._vendored.haiyou_constrained_idw`
- **Problem**: 视线相交检测对所有断层线段进行全量比对，复杂度为 $O(N_{wells} \cdot N_{segs})$。
- **Current Behavior**: 当工区包含数百条复杂断裂带且网格分辨率高时，插值计算时间显著增加。
- **Expected Behavior**: 利用线段包围盒（AABB）与 R-Tree 空间索引对井-网格连线进行候选集快速粗筛，将复杂度降至 $O(N_{wells} \cdot \log N_{segs})$。
- **Technical Analysis**: 在 `constrained_engine.py` 中引入轻量级线段索引过滤。
- **Suggested Solution**: 优化断层相交检测逻辑，增加空间索引预筛选。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p2-003"></a>ISS-P2-003: 地震切片数据多线程并发预取与 LRU 缓存淘汰效率不足
- **Title**: 地震正交切片异步优先级队列预取与智能 LRU 缓存
- **Category**: P2 Performance
- **Priority**: P2
- **Module**: `paleo_workbench.viz.seismic_load` / `SliceReadWorker`
- **Problem**: 快速拖动切片滑块时，大量过期的切片请求堆积在队列中，导致当前目标切片响应迟缓。
- **Current Behavior**: 队列按 FIFO 执行，旧请求阻塞新请求。
- **Expected Behavior**: 采用 LIFO / 优先级队列，丢弃过时切片请求，同时对临近切片（$\pm 3$ 帧）进行后台智能预取。
- **Technical Analysis**: 优化 Worker 请求通道，支持队列去重与动态优先级提升。
- **Suggested Solution**: 增强 `SliceReadWorker` 与切片缓存管理器。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p2-004"></a>ISS-P2-004: 测井表格数据模型在大规模井位下的全量组装性能开销
- **Title**: 测井数据大表格虚表懒加载与分块渲染优化
- **Category**: P2 Performance
- **Priority**: P2
- **Module**: `paleo_workbench.ui.pages.data_detail_panel` / `well_table`
- **Problem**: 加载包含数千口井及大量分层属性的大表时，一次性组装全部 Python 对象导致卡顿。
- **Current Behavior**: 界面初始化时出现数秒白屏。
- **Expected Behavior**: 采用 `QAbstractTableModel` 虚表机制，仅在视口请求 `data()` 时按需读取切片。
- **Technical Analysis**: 重构表格模型，基于 NumPy/Polars/Pandas 内存列连续存储提供索引。
- **Suggested Solution**: 优化数据模型与表格视图渲染。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

---

## P3 级界面与体验 (UI/UX)

### <a id="iss-p3-001"></a>ISS-P3-001: 缺少动态多主题切换 (Dark / Light / High-Contrast) 与高分屏微调
- **Title**: 构建动态主题引擎 (ThemeManager) 并支持深浅双主题切换
- **Category**: P3 UI/UX
- **Priority**: P3
- **Module**: `paleo_workbench.ui.theme` / `tokens`
- **Problem**: 仅支持单一深色样式表，在强光环境、论文打印或浅色显示偏好下可用性受限。
- **Current Behavior**: 样式表硬编码在 `tokens.py`，无法无刷新动态切换。
- **Expected Behavior**: 提供 `ThemeManager`，支持 `Dark`、`Light`、`Print-High-Contrast` 三套主题动态热重载，并自适应高 DPI 缩放。
- **Technical Analysis**: 将 QSS 样式表参数化，通过变量插值生成不同主题样式。
- **Suggested Solution**: 实现 `ThemeManager` 与多主题 QSS 模板。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p3-002"></a>ISS-P3-002: 缺少自由停靠浮动的 Dockable Workspace 与工作区预设
- **Title**: 实现 QGIS / ArcGIS Pro 风格的 DockPanel 工作区与多模式布局预设
- **Category**: P3 UI/UX
- **Priority**: P3
- **Module**: `paleo_workbench.ui.app`
- **Problem**: 页面布局主要基于固定 Splitter，用户无法根据多显示器或多任务需求自由拖拽停靠面板。
- **Current Behavior**: 面板位置固定，无法单独拉出至第二屏幕。
- **Expected Behavior**: 采用 `QDockWidget` 体系，支持图层树、属性表、工具箱、工作流向导自由停靠，并提供“测井解释”、“单因素编图”、“三维建模”预设布局。
- **Technical Analysis**: 在主窗口中集成 `QMainWindow` 标准 Dock 停靠管理与布局持久化（`saveState`/`restoreState`）。
- **Suggested Solution**: 重构工作台主框架为现代 Dockable Workspace。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None

### <a id="iss-p3-003"></a>ISS-P3-003: 拓扑编辑历史缺乏可视化 Undo/Redo 历史面板
- **Title**: 增加拓扑图形编辑操作历史面板 (History Dock)
- **Category**: P3 UI/UX
- **Priority**: P3
- **Module**: `paleo_workbench.ui.pages.map_edit_commands`
- **Problem**: 用户在执行移动顶点、分割多边形、合并图斑等操作时，无法直观查看历史记录和回滚节点。
- **Current Behavior**: 仅支持快捷键 Ctrl+Z / Ctrl+Y，缺乏操作描述与历史栈可视化。
- **Expected Behavior**: 提供可视化的历史操作列表，点击任意历史项可快速撤销至对应状态。
- **Technical Analysis**: 将 `QUndoStack` / `QUndoView` 与 `FeatureEditor` 事务机制绑定。
- **Suggested Solution**: 开发 `HistoryPanel` 并接入编辑命令栈。
- **Estimated Complexity**: S (Small)
- **Dependencies**: None

---

## P4 级功能增强 (Enhancement)

### <a id="iss-p4-001"></a>ISS-P4-001: 构建声明式 Map Composer 地图排版与整饰要素系统
- **Title**: 开发标准地图排版器 (Map Composer) 与全要素制图模板引擎
- **Category**: P4 Enhancement
- **Priority**: P4
- **Module**: `paleo_workbench.mapping.composer`
- **Problem**: 缺乏独立的地图整饰与打印排版系统，导出图件缺少工业级标准化地图要素。
- **Current Behavior**: 只能截取当前画布内容，无法配置标准图框、动态图例、指北针和经纬网。
- **Expected Behavior**: 提供完整的 `MapComposer` 模块，支持主图、图名、动态图例、线段比例尺、地质样式指北针、公里网格与地质年表色标，并支持无损 SVG/PDF 矢量导出。
- **Technical Analysis**: 建立基于 QGraphicsScene 或纯 Python 矢量绘制的排版引擎，支持图件元素的拖拽排版与属性联动。
- **Suggested Solution**: 在 `paleo_workbench/mapping/composer/` 下实现完整的 Composer 核心与 UI。
- **Estimated Complexity**: L (Large)
- **Dependencies**: ISS-P1-003

### <a id="iss-p4-002"></a>ISS-P4-002: 单因素图自动生成等值线、相带多边形与统计图斑增强
- **Title**: 单因素图等值线自动追踪、相带多边形拓扑提取与多维符号化
- **Category**: P4 Enhancement
- **Priority**: P4
- **Module**: `paleo_workbench.mapping.single_factor_pipeline`
- **Problem**: 单因素图目前主要呈现为标量网格栅格图，缺乏自动矢量化为等值线与相带图斑的能力。
- **Current Behavior**: 需人工根据网格手动画线划分岩相边界。
- **Expected Behavior**: 支持 Marching Squares 自动提取平滑等值线，并基于地质阈值自动生成封闭的岩相带多边形图层，实现单因素图向古地理图的一键转化。
- **Technical Analysis**: 整合 `skimage.measure.find_contours` 或自研等值线算法，将等值线闭合为拓扑合规的 GeoJSON 面图层。
- **Suggested Solution**: 开发 `SingleFactorPipeline` 矢量化与拓扑生成转换器。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: ISS-P1-003

### <a id="iss-p4-003"></a>ISS-P4-003: 建立自动化 QA 质检规则与地质合理性自愈诊断器
- **Title**: 构建地学制图与空间拓扑智能 QA/QC 规则引擎
- **Category**: P4 Enhancement
- **Priority**: P4
- **Module**: `paleo_workbench.workflow.qc` / `paleo_workbench.agent.agents.qa_agent`
- **Problem**: 现有的质检逻辑主要针对基本字段完整性，缺乏空间拓扑悬挂点、重叠面、异常极大值、井点拟合残差超标等深层地质质量检测。
- **Current Behavior**: 质检报告较为简略，无法指出几何微观缺陷。
- **Expected Behavior**: 提供包含 15+ 项地质与拓扑合规性检测规则的 QA 引擎，并在发现轻微缺陷时提供一键自愈（Auto-heal）功能。
- **Technical Analysis**: 结合 Shapely 空间谓词与统计异常检测算法，输出富文本交互式质检报告。
- **Suggested Solution**: 增强 `paleo_workbench/workflow/qc.py` 与 `QAAgent`。
- **Estimated Complexity**: M (Medium)
- **Dependencies**: None
