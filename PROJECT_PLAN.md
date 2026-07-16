# PROJECT_PLAN — 地质与古地理综合绘图分析平台

> **Updated:** 2026-07-17  
> **Product:** paleo-workbench (PySide6 desktop) + geo-viz-engine (viz/math submodule)  
> **Protocol:** Phase1 diagnose → Phase2 plan files → Phase3 issue-driven build  

---

## 1. 页面完成度矩阵（规划 9 页 vs 实现 10 导航）

| # | 规划名称 | 代码页 | 类 | 完成度 | 说明 |
|---|----------|--------|-----|--------|------|
| 1 | 项目总览 | 首页 | `HomePage` | **90%** | 工作流证据推断已接通；活动卡有证据回退 |
| 2 | 数据 | 数据 | `DataPage` | **92%** | 三栏+预览缓存+导入导出；路径 confinement 已加固 |
| 3 | 格架 | 层序格架 | `SequenceFrameworkPage` | **75%** | 方案持久化+层位绑定；边界编辑深度不足 |
| 4 | 地层 | 地层对比 | `StratigraphyCorrelationPage` | **70%** | CrossWell MVP+相叠加；非完整连井解释工区 |
| 5 | 地震 | 测井预测 + 地震预测 | `WellLogPredictionPage` / `SeismicPredictionPage` | **72%** | 双入口；Auto-Tie 已接线；预测仍偏 mock |
| 6 | 可视化 | 可视化 | `VisualizationPage` | **80%** | 薄 host + engine；井震标定工作区缺独立 tab |
| 7 | 数据制备 | 制备 | `PreparationPage` | **62%** | IDW + WellTable/MAD 模型层就绪；UI 表格与方向约束仍缺 |
| 8 | 地理图制作 | 编图 | `MappingPage` | **65%** | 相带编辑器 V1+拓扑；**缺约束线/趋势面/等值线定稿流** |
| 9 | 质检 | 成图审核 | `ReviewExportPage` | **60%** | 基础 QC upsert；**缺 MAD/IssueLayer/版本定稿** |

**导航：** `IconRail` 10 项（测井/地震拆分）= 产品 9 域全覆盖 + 预测拆页。  
**入口：** `python -m paleo_workbench.main`（非 web）。

---

## 2. 核心数据对象字典（目标 10 对象 vs 现状）

| 目标对象 | 现状映射 | 生产者 | 消费者 | 状态 |
|----------|----------|--------|--------|------|
| **WellTable** | `WellTable` / `WellTableRow` + `project.well_tables` | 制备适配器 / QC | 插值 sample_points | **已建** ISS-DOM-01 |
| **QCReport** | `QualityReport` | `run_basic_qc` | 审核页 / 首页 | **部分**（规则过浅） |
| **ConstraintLayers** | `ConstraintLayers` on project | 制备/编图导入 | IDW / 方向趋势 | **已建** ISS-DOM-02 |
| **BreakLines** | `ConstraintLine(role=break)` → IDW faults | 约束层 | IDW | **已建** ISS-DOM-02/ALG-03 |
| **DirectionLines** | `ConstraintLine(role=direction)` + azimuth/a/b | 约束层 | 方向加权 | **已建模型**；算法 ISS-ALG-02 |
| **TrendSurface** | `FactorMapTask.parameters` 中 `grid_x/y/z` 碎片 | 制备 IDW | 编图 shelf 只展示任务 | **弱** → ISS-ALG-02 |
| **ContourDraft** | engine `SurfaceWidget` + contourpy 存在；workbench 未建草稿对象 | — | 编图修编 | **缺失** → ISS-DOM-03 |
| **IssueLayer** | `QualityReport.issues` 列表，非空间层 | QC | 审核 | **弱** → ISS-QC-02 |
| **EditLog** | `PaleoMapDocument.edit_history` 字段存在，编辑命令未稳定落盘 | 编图 undo | 定稿审计 | **弱** → ISS-MAP-02 |
| **VersionSet** | 无；`CompilationRun` 可作雏形 | 定稿 | 对比/回滚 | **缺失** → ISS-DOM-04 |

### 目标闭环（单因素图编图）

```
[数据] ResourceItem / WellTable
        │  MAD 异常检测 · 砂地比约束
        ▼
[制备] ConstraintLayers + Break/Direction lines
        │  方向加权趋势面 T(x,y)
        ▼
[制备] TrendSurface + ContourDraft(初稿)
        │  修编提示 IssueLayer
        ▼
[编图] ContourDraft 修编 + EditLog
        │  VersionSet 专家定稿
        ▼
[质检] QCReport + 导出 ExportArtifact
```

### 已通路径（MVP）

```
resources → prediction_tasks.input_refs → VizAdapter → hosts
factor_map_tasks (IDW grid) → mapping factor_shelf (展示)
paleomap_documents ↔ map edit scene ↔ save_draft
QualityReport upsert ↔ review page
```

---

## 3. 空间/数学算法就绪度

| 算法 | 公式/要点 | 代码位置 | 就绪度 |
|------|-----------|----------|--------|
| 异常检测 (MAD) | \(z^*=0.6745(x-\mathrm{median})/\mathrm{MAD}\) | `workflow/well_qc.py` | **90%** ISS-ALG-01 |
| 砂地比 | \(R_s=H_s/H_t,\ 0\le H_s\le H_t\) | `compute_sand_ratio` + WellTable | **85%** ISS-ALG-01 |
| 方向距离/权重 | \(d_i(\theta)=\sqrt{(u/a)^2+(v/b)^2}\), \(w=\exp(-d^2) q b\) | **无** | **0%** ISS-ALG-02 |
| 趋势面 | \(T=\sum w_i z_i/\sum w_i\) | IDW \(w=1/d^p\) 近似，各向同性 | **40%** |
| 断层屏障 IDW | `fault_polylines` | engine + workbench 接线 | **85%** ISS-ALG-03 |
| 等值线提取 | marching squares / contourpy | `geoviz_plots.surface` | **70%**（引擎侧） |
| 克里金 | UI 可选 | 映射为 SciPy linear | **Mock** |

---

## 4. 架构快照

| 维度 | 状态 |
|------|------|
| GUI | PySide6，AppShell 4 区，QStackedWidget 10 页 |
| 状态 | `ProjectDocument` (Pydantic) + `.paleo.json` |
| 子工程 | `geo-viz-engine/` 算法与控件库 |
| 路径安全 | 相对路径禁止逃出工程目录（T-PATH-01） |
| 测试 | 大量 pytest-qt；需 `QT_QPA_PLATFORM=offscreen` |

---

## 5. 阶段路线图

| 阶段 | 目标 | 关键 Issue |
|------|------|------------|
| **S0** | 诊断 + 看板落盘 | 本文件 / ISSUE_BOARD |
| **S1** | 领域模型：WellTable + 约束线 + ContourDraft + VersionSet 骨架 | ISS-DOM-01..04 |
| **S2** | MAD/砂地比 QC + 方向加权趋势面 + 断层屏障接线 | ISS-ALG-01..03 |
| **S3** | 制备页消费 WellTable；后台 Worker 插值 | ISS-PREP-01 |
| **S4** | 编图等值线草稿修编 + EditLog + 定稿 VersionSet | ISS-MAP-01..02 |
| **S5** | 质检 IssueLayer 空间化 + 全链路 e2e | ISS-QC-02, ISS-E2E-01 |

---

## 6. 工程约定

- UI 与重算解耦：插值/趋势面必须 `QThread` / worker，禁止阻塞 GUI。
- 生产 import 仅 `geoviz` facade（allowlist）。
- 业务改动前锁 ISSUE_BOARD 一行 WIP；完成后 pytest 证据 + DONE。
