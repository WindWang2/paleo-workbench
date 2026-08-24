# Paleo Workbench 结构化问题汇总与分类报告 (Issue Summary)

## 1. 多角色审查团队 (Multi-Agent Swarm) 审查总览

本次代码审计由 6 大专业审查智能体独立审查并汇总而成：
- **Agent 1 (Software Architect)**: 聚焦系统解耦、CAS 单写入口、Symmetric Parity 契约、事件总线与无头服务完整性。
- **Agent 2 (Algorithm Expert)**: 聚焦测井 DTW、3D 相干、各向异性约束 IDW、高斯散度地层体积积分与拓扑自愈算法的数值鲁棒性。
- **Agent 3 (Performance Engineer)**: 聚焦大文件 mmap、GIL 释放、NumPy 连续列内存导出、GPU Instanced Wiggle 与渲染防抖。
- **Agent 4 (GIS/QGIS Expert)**: 聚焦图层树体系、符号与分级色带、空间拓扑校验、R-Tree 空间索引与 QGIS Processing 架构融合。
- **Agent 5 (UI/UX Expert)**: 聚焦 Design Tokens 体系、多主题动态热重载、Dockable 工作区预设与地学软件交互对标。
- **Agent 6 (AI Harness Architect)**: 聚焦自然语言意图理解、DAG 任务规划、四大注册中心（Tool/Skill/Algo/Template）与 8-Agent 闭环协同。

---

## 2. 问题统计矩阵 (Issue Statistics)

| 类别 (Category) | P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low) | 合计 (Total) |
|---|---|---|---|---|---|
| **AI Harness & Workflow** | 0 | 2 | 2 | 1 | **5** |
| **GIS Engine & QGIS** | 1 | 2 | 2 | 1 | **6** |
| **Algorithm & Numerics** | 1 | 1 | 2 | 1 | **5** |
| **Performance & Memory** | 0 | 1 | 3 | 1 | **5** |
| **Data Management & IO** | 0 | 1 | 2 | 1 | **4** |
| **UI/UX & Design** | 0 | 1 | 2 | 2 | **5** |
| **Testing & Stability** | 1 | 1 | 1 | 1 | **4** |
| **总计 (Total)** | **3** | **9** | **14** | **8** | **34** |

---

## 3. 结构化核心 Issue 详细清单 (Core Issue Catalog)

### 3.1 P0 (Critical) Issues
1. **`[Testing][P0]` CI 3.13 腿随机段错误 (Qt 事件循环退出前清理与 C++ 弱引用保护)**
   - **文件**: `paleo_workbench/mapping/map_render_backend.py`, `native/`
   - **现象**: CI 3.13 运行多测试用例时有极小概率发生 exit 139 段错误。
   - **方案**: 加强 `_LIVE_FALLBACKS` 弱引用清理与 QThreadPool/QImage 析构顺序保护。
2. **`[Algorithm][P0]` DTW 算法在空曲线与超长退化曲线下的边界保护与内存配额**
   - **文件**: `paleo_workbench/viz/dtw_log_matcher.py` (`match_curves`)
   - **现象**: 当输入全空或退化极端长曲线时可能耗尽内存或除零。
   - **方案**: 引入 `_MAX_COST_CELLS` 动态步长自适应降采样与空数组直接防护。
3. **`[GIS Engine][P0]` 地质多边形自相交与未封闭环导致 Shapely 崩溃与自愈机制**
   - **文件**: `paleo_workbench/mapping/topology.py` (`repair_invalid_geometry`)
   - **现象**: 复杂地质断块勾绘容易产生 Bow-tie 自相交多边形。
   - **方案**: 采用 Shapely `make_valid` / `buffer(0)` 自动修复拓扑。

### 3.2 P1 (High) Issues
4. **`[Harness][P1]` 构建四大注册中心 (Tool, Skill, Algorithm, Template) 支撑自主智能体**
   - **文件**: `paleo_workbench/agent/registries/`
   - **方案**: 完善强类型参数反射、JSON Schema 导出与高阶地质技能组合。
5. **`[Harness][P1]` 实现基于 DAG 任务图的 8 大专业智能体协同工作流 (PaleoAIHarness)**
   - **文件**: `paleo_workbench/agent/harness.py`, `planner.py`, `intent.py`, `agents/`
   - **方案**: 落地 Data, Well, Seismic, GIS, Carto, Viz, QA, Result 智能体闭环。
6. **`[GIS Engine][P1]` 统一标量栅格层与 QGIS / Fallback 渲染管线**
   - **文件**: `paleo_workbench/mapping/layer_model.py`, `single_factor_pipeline.py`
   - **方案**: 支持标量栅格图层与光滑等值线、相带面的无缝叠加与渲染。
7. **`[GIS Engine][P1]` 声明式 Map Composer 地图排版与出版级整饰要素系统**
   - **文件**: `paleo_workbench/mapping/composer/` (`models.py`, `renderer.py`)
   - **方案**: 覆盖主图、指北针、比例尺、图例、经纬网与高精 SVG/PDF 矢量导出。
8. **`[Performance][P1]` 测井大表格 NumPy 连续内存列导出与 DataFrame 互操作性能提升**
   - **文件**: `paleo_workbench/workflow/well_table.py` (`well_table_to_arrays`)
   - **方案**: 提供零拷贝/单遍生成连续内存数组，消除逐行迭代装箱开销。
9. **`[UI/UX][P1]` ThemeManager 多主题动态热重载与 Dockable Workspace 预设管理**
   - **文件**: `paleo_workbench/ui/theme.py`, `dock_manager.py`
   - **方案**: 支持深色、浅色与地学出版高对比度主题切换，提供多专业工作区预设。

### 3.3 P2 & P3 Issues (Medium & Low)
10. **`[Performance][P2]` IDW 空间阻隔判定引入 R-Tree 空间索引粗筛** (`_vendored/haiyou_constrained_idw/`)
11. **`[Data Management][P2]` 大文件 CAS 存储碎片垃圾回收与增量索引持久化** (`catalog/service.py`)
12. **`[Algorithm][P2]` 连井剖面对齐引入 FastDTW 多尺度分层粗细匹配** (`viz/dtw_log_matcher.py`)
13. **`[QGIS Integration][P2]` 抽象统一的 GeoAlgorithm 端口描述规范** (`mapping/`)
14. **`[UI/UX][P2]` 增加交互式参数微调滑块与实时热更新视口** (`ui/pages/`)
15. **`[UI/UX][P3]` 拓扑图形编辑操作历史面板 (History Undo/Redo Timeline)** (`ui/`)
16. **`[Documentation][P3]` 完善 AI GIS Harness API 开发指南与地质技能编写规范** (`docs/`)
