# AGENT_TASK_BOARD — 古地理综合绘图分析平台

> **Created:** 2026-07-16  
> **Role:** Multi-agent external memory (Planning with files)  
> **Protocol:** Read before code · Write after act · No blind business edits without board lock  

## 0. Architecture Snapshot (Phase 1 baseline)

| Dimension | State |
|-----------|--------|
| **Product** | paleo-workbench — desktop paleogeography compilation GUI |
| **GUI** | **PySide6** (Qt6) — **not** web/React; no `npm run dev` |
| **Entry** | `python -m paleo_workbench.main` / `paleo_workbench/main.py` |
| **State** | In-memory `ProjectDocument` (Pydantic) + `.paleo.json` via `ProjectManager` — **no** Redux/Vuex; shell rebuild on project switch |
| **Viz subproject** | `geo-viz-engine/` git submodule — algorithms & widgets (`geoviz_*` packages + `geoviz` facade) |
| **Geo stack** | **GDAL/osgeo** (reference layers), **shapely** (topology merge/split), **rasterio** (GeoTIFF preview), **numpy/pandas**, **lasio/segyio** (via engine) |
| **NOT present** | PostGIS, MapLibre, OpenLayers, geopandas, QGIS API |
| **Native** | optional `native/map_edit_core` (pybind11) for map edit hot path |
| **Python pin** | pyproject `>=3.12,<3.14` — CI matrix 3.12 + 3.13 |
| **Nav** | 10 pages, `QStackedWidget` + IconRail index 0–9 |

### Page index map (product ↔ code)

| Idx | Product name (tokens) | User goal label | Page class | Maturity |
|-----|----------------------|-----------------|------------|----------|
| 0 | 首页 | 1 项目总览 | `HomePage` | **DONE** |
| 1 | 数据 | 2 数据 | `DataPage` | **DONE** (A/B/C + I/O enrich) |
| 2 | 测井预测 | 4 地层·单井相 | `WellLogPredictionPage` | **DONE** (LAS+相道/导出) |
| 3 | 地震预测 | 5 地震·地震相 | `SeismicPredictionPage` | **DONE** (属性/Tie/运行·发送) |
| 4 | 层序格架 | 3 格架 | `SequenceFrameworkPage` | **DONE** (方案持久化) |
| 5 | 地层对比 | 4 连井对比 | `StratigraphyCorrelationPage` | **DONE** (CrossWell MVP) |
| 6 | 可视化 | 6 可视化 | `VisualizationPage` | **DONE** (hosts + engine align) |
| 7 | 制备 | 7 数据制备 | `PreparationPage` | **DONE** (IDW) |
| 8 | 编图 | 8 地理图制作 | `MappingPage` | **DONE** (editor V1) |
| 9 | 成图审核 | 9 质检 | `ReviewExportPage` | **DONE** (运行检查+导出报告) |

---

## 1. 任务总表

| 任务ID | 所属页面 | 优先级 | 状态 | 负责人 | 说明 |
|--------|----------|--------|------|--------|------|
| T-BASE-01 | 全局 | P0 | **DONE** | Agent | Phase 1 架构侦测 + 本看板创建 |
| T-IO-01 | 数据 | P0 | **DONE** | Agent | 导入元数据/角色 + 导出服务 + 清单 |
| T-VIZ-01 | 可视化 | P0 | **DONE** | Agent | viz/hosts 模块化；引擎对齐 |
| T-VIZ-02 | 可视化 | P1 | **DONE** | Agent | Review 修复：clear/project/seismic volume-first |
| T-MAP-01 | 编图 | P0 | **DONE** | Agent | 草稿属性保留 + 保存门禁 flush |
| T-DATA-01 | 数据 | P0 | **DONE** | Agent | 导入 UI 线程 QueuedConnection；清单菜单接线 |
| T-COMMIT-01 | 全局 | P0 | **DONE** | Agent | push: workbench `9998222` + geoviz `a6ca6dba` |
| T-DATA-02 | 数据 | P1 | **DONE** | Agent | DataPage.project_path；导入/重扫/导出 resolve + external |
| T-MAP-02 | 编图 | P1 | **DONE** | Agent | 演示草稿生成前 dirty 确认；view_state 持久化 |
| T-MAP-03 | 编图 | P1 | **DONE** | Agent | 参考层 offline 状态；`MapReferenceLayer.external` 字段 |
| T-QC-01 | 质检 | P1 | **DONE** | Agent | QC upsert + active_quality_reports for dashboard |
| T-VIZ-03 | 可视化 | P1 | **DONE** | Agent | SVG/PDF 按钮按 Tab 能力门控；连井/古地理专用导出 API |
| T-ADP-01 | 适配器 | P2 | **DONE** | Agent | PaleoMapAdapter 禁用假 pdf/svg；仅 geojson |
| T-PREP-01 | 制备 | P1 | **DONE** | Agent | 单因素真实插值链路对接 engine plots/IDW；与编图 factor shelf 闭环 |
| T-SEQ-01 | 格架 | P1 | **DONE** | Agent | 层序方案持久化加深；与预测/编图 target_horizon 双向绑定 |
| T-STRAT-01 | 地层(新) | P1 | **DONE** | Agent | 地层对比页：多井 CrossWell + 相/顶叠加 + SVG 导出 |
| T-SEIS-01 | 地震 | P1 | **DONE** | Agent | 地震相工作流：属性/层位/Auto-Tie 信号接通 SeismicView |
| T-WELL-01 | 测井 | P1 | **DONE** | Agent | 单井相：岩性/相道/导出；绑定真实 LAS 资源非仅 mock |
| T-FLOW-01 | 全局 | P0 | **DONE** | Agent | test_e2e_dataflow_contract.py 覆盖资源→…→导出契约 |
| T-ENV-01 | 全局 | P2 | **DONE** | Agent | 对齐 requires-python 与运行时 3.13；CI 矩阵 |
| T-QC-02 | 质检 | P1 | **DONE** | Agent | 成图审核页：运行检查 + 导出报告接线；页成熟度 DONE |
| T-CI-01 | 全局 | P0 | **DONE** | Agent | CI 安装系统 GDAL；修复 3.12/3.13 依赖失败 |
| T-CI-02 | 全局 | P0 | **DONE** | Agent | 钉死 gdal 绑定到系统 libgdal 版本 |
| T-DATA-03 | 数据 | P1 | **DONE** | Agent | 导入 QThread 竞态：GUI 线程安全收尾 + 测试签名 |
| T-CI-03 | 全局 | P0 | **DONE** | Agent | CI pytest timeout；facade-only imports；取消挂起 run |
| T-HOME-01 | 首页 | P1 | **DONE** | Agent | 工作流步骤按工程证据推断；活动卡证据回退；sync 进 active run |
| T-SEIS-02 | 地震 | P1 | **DONE** | Agent | Auto-Tie 信号接通 SeismicView：current_seismic_trace + 合成道叠加 |
| T-MAP-04 | 编图 | P1 | **DONE** | Agent | hit_test 跳过隐藏图层；Qt item 路径同步过滤 |
| T-MAP-05 | 编图 | P1 | **DONE** | Agent | 演示草稿幂等：replace demo + 折叠历史重复；用户图保留 |
| T-PATH-01 | 全局 | P1 | **DONE** | Agent | resolve_project_path 禁止相对路径 ``..`` 逃出工程目录 |
| T-UI-01 | 数据 | P2 | **DONE** | Agent | 预览栏按钮文案对齐整列隐藏（阅读器+属性） |
| T-MAP-06 | 编图 | P2 | **DONE** | Agent | snap 候选忽略隐藏图层；图层可见性变更 invalidate 缓存 |
| ISS-DOM-01 | 制备 | P0 | **DONE** | Agent | WellTable/WellTableRow + FactorMapTask 适配 |
| ISS-ALG-01 | 制备 | P0 | **DONE** | Agent | MAD z* + 砂地比 R_s 约束 QC |
| ISS-DOM-02 | 制备/编图 | P0 | **DONE** | Agent | ConstraintLayers/Line（break/direction） |
| ISS-ALG-03 | 制备 | P1 | **DONE** | Agent | IDW 消费 break fault_polylines |
| ISS-ALG-02 | 制备 | P0 | **DONE** | Agent | 方向加权趋势面 + UI「方向趋势」 |
| ISS-DOM-03 | 编图/制备 | P0 | **DONE** | Agent | ContourDraft 等值线初稿 + 推送 map lines |
| ISS-MAP-01 | 编图/制备 | P0 | **DONE** | Agent | UI 生成等值线初稿（制备+factor shelf） |
| ISS-PREP-01 | 制备 | P0 | **DONE** | Agent | WellTable 面板 + 插值 QThread Worker |
| ISS-DOM-04 | 质检 | P0 | **DONE** | Agent | VersionSet 专家定稿 + 审核页按钮 |
| ISS-E2E-01 | 全局 | P0 | **DONE** | Agent | 单因素全链路契约测试 |
| ISS-QC-01 | 质检 | P1 | **DONE** | Agent | run_basic_qc 六规则：层位/相带/几何/井/等值线/井表QC |
| ISS-QC-02 | 质检 | P1 | **DONE** | Agent | issues 空间字段 + issue_layer_geojson + 表「定位」列 |

**锁定任务（本回合）：** 无

---

## 2. 数据对象字典（跨页面流转）

| 对象 | 定义位置 | 生产者 | 消费者 | 格式/契约 | 状态 |
|------|----------|--------|--------|-----------|------|
| **ProjectDocument** | `project/models.py` | 新建/打开/样例 bootstrap | 全页 `update_state` | `.paleo.json` | **稳定** |
| **ResourceItem** | models | import/scanner | Data/Viz/Prediction | path+type+format+summary | **稳定**；需 project_path 完善 |
| **ExportArtifact** | models | export_service / record_export | Data/Review | 相对 path + format | **可用** |
| **StratigraphicFramework** | models | 格架页编辑/保存 | 制备/编图/run | target_horizon+scheme | **可用**；下游绑定 map/factor |
| **FactorMapTask** | models | 制备页 / IDW 插值 | 编图 factor shelf | sample_points + grid_z + metrics | **可用**；批量生成接通 engine |
| **PredictionTask** | models | mock adapter / bind assets | 测井/地震/可视化 | input_refs, results | **mock 为主** |
| **PaleoMapDocument** | models | 编图 / compile_map_draft | 可视化/质检/导出 | facies/wells/lines/labels | **稳定**；view_state 可回写 center/scale |
| **MapReferenceLayer** | models | ReferenceLayerService(GDAL) | 编图 snap | source_path+crs+external | **稳定**；offline/ready 按文件存在 |
| **QualityReport** | models | run_basic_qc | 质检页/dashboard | issues+status | **可膨胀** |
| **VizRef / VizPayload** | `viz/models.py` | VizAdapter | Visualization hosts | kind+engine handles | **稳定** |
| **WellLogData** | geoviz_well_log | load_las_preview | WellLogHost/Canvas | curves+depth | **引擎单一真相** |
| **SEGY volume / path** | geoviz_seismic | SeismicLoader / load_segy | SeismicHost/View | path优先有界 volume | **已对齐预算** |
| **PreparedPreview** | geoviz contracts | GeoVizEngine.prepare | Data reader / EnginePreviewHost | kind backends | **稳定** |
| **Topology / rings** | map_edit_api + scene | 编图编辑 | save_draft → document | coordinates lists | **稳定** |

### 关键数据流（目标闭环）

```
[数据] ResourceItem ──► [测井/地震预测] PredictionTask.input_refs
                              │
                              ▼
[制备] FactorMapTask ──► [编图] factor_shelf + PaleoMapDocument
                              │
[格架] target_horizon ────────┤
                              ▼
[可视化] VizRef ──► hosts / GeoVizEngine
                              │
                              ▼
[质检] QualityReport + ExportArtifact ◄── export_service / 编图草稿
```

---

## 3. 依赖与 Geo-Stack

| 库 | 用途 | 集成点 |
|----|------|--------|
| PySide6 | GUI | AppShell, all pages |
| Pydantic v2 | 工程模型 | ProjectDocument |
| GDAL (osgeo) | 参考层 CRS/矢量/栅格预览 | mapping/reference_layers.py |
| shapely | 多边形 merge/split | mapping/map_edit_api.py |
| rasterio | GeoTIFF 预览 | preview path |
| lasio / segyio | LAS/SEGY | geoviz packages + exporters |
| numpy/scipy | 网格/数值 | engine plots/seismic |
| PyOpenGL/pyqtgraph | 地震 3D | geoviz_seismic |
| map_edit_core (opt) | C++ 编辑热路径 | native/ |

**明确不在栈内：** MapLibre / OpenLayers / PostGIS / geopandas（桌面 Qt + 本地文件，非 Web 地图）。

---

## 4. 风险与约束

1. **未提交改动大**：workbench + geoviz dirty；需 `T-COMMIT-01`。  
2. **双栈历史债**：编图 workbench editor vs paleo_map EditEngine；长期统一。  
3. **专业页 mock 重**：预测/制备算法未完全产品化。  
4. **地层对比缺页**：产品愿景 #4 需新建或升格「连井」为一级导航。  

---

## 5. 执行日志（Agent 必更）

| 时间 | 动作 | 结果 |
|------|------|------|
| 2026-07-16 | Phase 1 侦测 | 架构拓扑见 §0；9 页索引确认 |
| 2026-07-16 | Phase 2 看板创建 | 本文件 AGENT_TASK_BOARD.md |
| 2026-07-16 前会话 | I/O+VIZ+Review 修复 | 见 task_plan Phase 22–25；测试 66 passed 聚焦套件 |
| 2026-07-16 | T-DATA-02 | DataPage.project_path 贯通 import/rescan/export；41 passed 聚焦 |
| 2026-07-16 | T-COMMIT-01 | 提交 push workbench + geoviz 子模块 |
| 2026-07-16 | T-QC-01 + T-FLOW-01 | QC upsert；e2e 数据流契约；VizAdapter 相对路径解析 |
| 2026-07-16 | T-MAP-02 | save_draft 合并 view_state；load 恢复；演示草稿 dirty Save/Discard/Cancel；14 tests |
| 2026-07-16 | T-MAP-03 | MapReferenceLayer.external；refresh_status offline；panel 标注；工程 load 回写；28 tests |
| 2026-07-16 | T-VIZ-03 | view_export_capabilities；连井 export_composite / 古地理 professional figure；Tab 门控 SVG/PDF；21 tests |
| 2026-07-16 | T-PREP-01 | factor_interpolation IDW/SciPy；批量生成接线；编图 shelf 闭环；26 tests |
| 2026-07-16 | T-SEQ-01 | stratigraphy apply/bind；目标层位可编辑；保存同步 run/map/factor；16 tests |
| 2026-07-16 | T-SEIS-01 | 属性/模式/Auto-Tie→SeismicView；运行预测+发送编图；19 tests |
| 2026-07-16 | T-WELL-01 | LAS 绑定+岩性/相道 merge；导出 PNG/SVG/PDF；发送制备；21 tests |
| 2026-07-16 | T-ADP-01 | PaleoMapAdapter 拒绝假 pdf/svg；仅 geojson |
| 2026-07-16 | T-STRAT-01 | 新页「地层对比」idx5；CrossWell 多井+预测相；导航 10 页 |
| 2026-07-16 | T-ENV-01 | requires-python >=3.12,<3.14；CI 矩阵 3.12+3.13；geoviz 同步 |
| 2026-07-16 | T-CI-01 | apt libgdal-dev + GDAL_CONFIG；prefer-binary 安装 |
| 2026-07-16 | T-QC-02 | 审核页 run_qc / 导出 JSON 报告；18 tests |
| 2026-07-16 | T-CI-02 | gdal==$(gdal-config --version) 约束；避免 3.13 sdist |
| 2026-07-16 | T-DATA-03 | 导入线程 GUI 收尾，修复 import_finished 丢失 |
| 2026-07-16 | T-CI-03 | CI --timeout=60；geoviz facade 补 IDW/相模型导出 |
| 2026-07-16 | T-CI-04 | mock project_path/confirm；raster 无 gdal_array；signal timeout；CI 3.12+3.13 green |
| 2026-07-16 | T-HOME-01 | home_workflow_steps + infer_status；activity 证据回退；app 全路径接线 |
| 2026-07-16 | T-SEIS-02 | SeismicView 连接 auto_tie_requested/synthetic_changed；demo 井日志种子；20 tests |
| 2026-07-16 | T-MAP-04 | hit_test_at / _feature_item_at 仅可见图层；export 仍含隐藏要素；30 tests |
| 2026-07-17 | T-MAP-05 | compile_map_draft 幂等 replace；稳定 id；折叠 legacy 重复 demo；26 tests |
| 2026-07-17 | T-PATH-01 | ProjectPathError；相对路径 confinement；open 失败提示；viz adapter 同步；41 tests |
| 2026-07-17 | T-UI-01 + T-MAP-06 | 预览栏文案；snap 跳过隐藏层；39 focused tests |
| 2026-07-17 | ISS-DOM-01/ALG-01 | WellTable + MAD/砂地比；PROJECT_PLAN/ISSUE_BOARD；25 tests |
| 2026-07-17 | ISS-DOM-02/ALG-03 | ConstraintLayers + IDW fault 接线；30 tests |
| 2026-07-17 | ISS-ALG-02 | directional_trend + 方向趋势 method；50 tests |
| 2026-07-17 | ISS-DOM-03 | ContourDraft + extract_contour_lines facade；23 tests |
| 2026-07-17 | ISS-MAP-01 | 制备/编图 UI 等值线初稿；27 tests |
| 2026-07-17 | ISS-PREP-01 | WellTablePanel + async FactorPrepareWorker；14 tests |
| 2026-07-17 | ISS-DOM-04 | VersionSet finalize + 专家定稿 UI；15 tests |
| 2026-07-17 | ISS-E2E-01 | factor map e2e contract WellTable→定稿；2 tests |
| 2026-07-17 | ISS-QC-01 | 扩展 QC 规则 + 15 tests；push f91ff0b |
| 2026-07-17 | ISS-QC-02 | IssueLayer geometry/ref + GeoJSON；19 tests |

---

## 6. 操作门禁

```
BEFORE code:  Read AGENT_TASK_BOARD.md §1 → lock one TODO row → set WIP
AFTER code:   Run targeted pytest → set DONE/BLOCKED → append §5 log
NEVER:        Edit business without board lock; claim success without terminal evidence
```
