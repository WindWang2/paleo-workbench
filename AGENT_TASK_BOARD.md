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
| **Python pin** | pyproject `>=3.12,<3.13` — host may run 3.13 (env drift risk) |
| **Nav** | 9 pages, `QStackedWidget` + IconRail index 0–8 |

### Page index map (product ↔ code)

| Idx | Product name (tokens) | User goal label | Page class | Maturity |
|-----|----------------------|-----------------|------------|----------|
| 0 | 首页 | 1 项目总览 | `HomePage` | **DONE** |
| 1 | 数据 | 2 数据 | `DataPage` | **DONE** (A/B/C + I/O enrich) |
| 2 | 测井预测 | 4 地层·单井相 | `WellLogPredictionPage` | **PARTIAL** |
| 3 | 地震预测 | 5 地震·地震相 | `SeismicPredictionPage` | **PARTIAL** |
| 4 | 层序格架 | 3 格架 | `SequenceFrameworkPage` | **PARTIAL** |
| 5 | 可视化 | 6 可视化 | `VisualizationPage` | **DONE** (hosts + engine align) |
| 6 | 制备 | 7 数据制备 | `PreparationPage` | **PARTIAL** |
| 7 | 编图 | 8 地理图制作 | `MappingPage` | **DONE** (editor V1) |
| 8 | 成图审核 | 9 质检 | `ReviewExportPage` | **PARTIAL** |

**Gap vs ideal “地层对比”:** multi-well correlation product lives in **engine** `CrossWellCanvas` + viz 连井 tab; **no dedicated 地层 page** — needs task T-STRAT-*.

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
| T-MAP-03 | 编图 | P1 | **TODO** | Agent | 参考层 offline 状态；`MapReferenceLayer.external` 字段 |
| T-QC-01 | 质检 | P1 | **DONE** | Agent | QC upsert + active_quality_reports for dashboard |
| T-VIZ-03 | 可视化 | P1 | **TODO** | Agent | SVG/PDF 按钮按 Tab 能力门控；连井/古地理专用导出 API |
| T-ADP-01 | 适配器 | P2 | **TODO** | Agent | PaleoMapAdapter 禁用假 pdf/svg 或接引擎出图 |
| T-PREP-01 | 制备 | P1 | **TODO** | Agent | 单因素真实插值链路对接 engine plots/IDW；与编图 factor shelf 闭环 |
| T-SEQ-01 | 格架 | P1 | **TODO** | Agent | 层序方案持久化加深；与预测/编图 target_horizon 双向绑定 |
| T-STRAT-01 | 地层(新) | P1 | **TODO** | Agent | 产品缺口：地层对比页 = 多井 + tops + DTW；复用 CrossWell engine |
| T-SEIS-01 | 地震 | P1 | **TODO** | Agent | 地震相工作流：属性/层位/Auto-Tie 信号接通 SeismicView |
| T-WELL-01 | 测井 | P1 | **TODO** | Agent | 单井相：岩性/相道/导出；绑定真实 LAS 资源非仅 mock |
| T-FLOW-01 | 全局 | P0 | **DONE** | Agent | test_e2e_dataflow_contract.py 覆盖资源→…→导出契约 |
| T-ENV-01 | 全局 | P2 | **TODO** | Human/Agent | 对齐 requires-python 与运行时 3.13；CI 矩阵 |

**锁定任务（本回合）：** 无（T-MAP-02 已完成）。

---

## 2. 数据对象字典（跨页面流转）

| 对象 | 定义位置 | 生产者 | 消费者 | 格式/契约 | 状态 |
|------|----------|--------|--------|-----------|------|
| **ProjectDocument** | `project/models.py` | 新建/打开/样例 bootstrap | 全页 `update_state` | `.paleo.json` | **稳定** |
| **ResourceItem** | models | import/scanner | Data/Viz/Prediction | path+type+format+summary | **稳定**；需 project_path 完善 |
| **ExportArtifact** | models | export_service / record_export | Data/Review | 相对 path + format | **可用** |
| **StratigraphicFramework** | models | 格架页 | 制备/编图/预测 | target_horizon, boundaries | **浅** |
| **FactorMapTask** | models | 制备页 / pipeline | 编图 factor shelf | parameters.sample_points | **UI 有、算法弱** |
| **PredictionTask** | models | mock adapter / bind assets | 测井/地震/可视化 | input_refs, results | **mock 为主** |
| **PaleoMapDocument** | models | 编图 / compile_map_draft | 可视化/质检/导出 | facies/wells/lines/labels | **稳定**；view_state 可回写 center/scale |
| **MapReferenceLayer** | models | ReferenceLayerService(GDAL) | 编图 snap | source_path+crs | **路径有**；offline 弱 |
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

---

## 6. 操作门禁

```
BEFORE code:  Read AGENT_TASK_BOARD.md §1 → lock one TODO row → set WIP
AFTER code:   Run targeted pytest → set DONE/BLOCKED → append §5 log
NEVER:        Edit business without board lock; claim success without terminal evidence
```
