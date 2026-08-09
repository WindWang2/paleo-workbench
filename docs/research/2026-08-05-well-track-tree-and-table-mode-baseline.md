# Research: 主机现状与 ADR 0022/0024 对数据树与表格模式的约束

**Issue:** [#332](https://github.com/WindWang2/paleo-workbench/issues/332) (wayfinder research; map [#331](https://github.com/WindWang2/paleo-workbench/issues/331))  
**Date:** 2026-08-05  
**Scope:** Primary sources only — `well-log-engine/apps/wellplot-desktop/well_log_workstation/`, `docs/adr/0022*`, `docs/adr/0024*`, related ADRs 0014/0015, `CONTEXT.md` Well Log sections, `well-log-engine` table/selection public surface.
**Status:** Research complete (findings only; no product code).

## Question

在现有 WellPlot Desktop 与相关 ADR 下，实现「每井数据树 + 图/表切换」时，哪些模型、API 与决策已经锁死、哪些是缺口？

---

## 1. 职责边界（已落地主机模型）

### 1.1 `workspace_tree` — 工区目录树（井/图件级，非数据树）

| 项 | 现状 |
|---|---|
| 位置 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py` · `_refresh_tree` |
| 节点 kind | `workspace` → `wells_folder` / `plots_folder` → leaf `well` / `plot` |
| 井节点载荷 | `{kind, id, path}` — 仅目录 id 与相对 LAS 路径 |
| **不展示** | 曲线助记符、采样轴、数据源、图道可见性、样点规模 |

树只服务 **工区 catalog 导航**（选中井、双击打开图件）。选中井时更新 `_selected_well_id` 并刷新 tops 列表，**不**展开井下曲线。

引用：`shell.py` `_refresh_tree`（约 L2513–2579）；`workspace.py` `WellCatalogEntry` / `PlotCatalogEntry`。

### 1.2 `track_list` — 当前图版图道列表（布局编辑，非数据源树）

| 项 | 现状 |
|---|---|
| 位置 | `shell.py` 右栏 `TrackList` + `_refresh_track_list` |
| 数据源 | 活动 `HostPresentation.tracks`（`BoundTrack`） |
| 可编辑 | `visible`、`scale_min/max/mode`（曲线道） |
| 持久化 | `PlotDocument.track_overrides`（schema v5，`plot_document.py`）→ `track_overrides_snapshot` / `apply_track_overrides` |

**语义锁定：** 图道可见性是 **图版/图件布局属性**，不是「井数据树勾选曲线是否进入文档」。隐藏图道只影响 `HostPresentation.visible_tracks` 与画布/导出，不从 `ImportedWellDocument` 移除曲线。

### 1.3 `apply_template` / `HostPresentation` / `BoundTrack`

编译链（`template_model.py`）：

```text
PlotTemplate (JSON, schemaVersion)
  + ImportedWellDocument (host curves + single depth[])
  → apply_template()
  → HostPresentation
       tracks: list[BoundTrack]
         role: depth | curve
         layers: BoundCurveLayer (mnemonic, color, values, null_mask)
         visible, width_fraction, scale: ScaleSpec
```

| 类型 | 职责 |
|---|---|
| `PlotTemplate` | 版本化图版定义（内置 `templates/*.json`）；按 mnemonic 别名绑曲线 |
| `apply_template` | **编译** 模板+井数据 → 运行时布局；缺 depth 道时自动插入 |
| `HostPresentation` | **单井** 多图道布局的 UI 所有权对象（`well_document_id`、depth、tracks、header） |
| `BoundTrack` | 图道运行时实例；`visible` 默认 true；与引擎 `ScenePresentation` 平行，直至完全绑定 C++ |

壳层入口：`shell.apply_template_to_well` — 加载 session 井文档、应用内置模板、恢复 `track_overrides`、刷新 `multi_track_canvas` / 可选 `WellLogView`。

**锁定：** 图道内容由 **图版 mnemonics 匹配** 决定；未匹配的 LAS 曲线 **静默不进图**，也不出现在树中。图版未绑定任何曲线时 `apply_template_to_well` 报错。

### 1.4 双画布路径（图模式基线）

| 路径 | 角色 |
|---|---|
| `MultiTrackCanvas` | 主机默认 QPainter 多图道；共享深度窗 pan/zoom；层位拾取 |
| `engine_bridge` + `WellLogView` | 可选；`submit_multi_track` 将 host presentation 提交引擎 |

注释明确：主机画布是「直到 Python 完整绑定引擎 multi-track 之前」的主显示面（`multi_track_canvas.py` 头注释；`engine_bridge.py`）。

**当前无** 主机侧「图/表」主视图切换控件或表格面板。

---

## 2. ADR 0022 — 表格模式硬约束（不可违背）

来源：`docs/adr/0022-virtualized-table-projections.md`（accepted）+ 引擎实现契约  
`well-log-engine/include/welllog/table/table_projection.hpp`、  
`well-log-engine/include/welllog/qtwidgets/table_model.hpp`、  
`well-log-engine/docs/table-and-export.md`。

| # | 硬约束 | 规格含义 |
|---|---|---|
| T1 | **按需虚拟化** | `TableProjection` / `TableModel`：行数 O(1)，单元格按需读 raw buffer；禁止全表物化到 QVariant 矩阵 |
| T2 | **同轴宽表** | 共享同一 Sampling Axis 的曲线 → `Depth \| Curve...` 一表 |
| T3 | **异轴默认分表** | 不同 Sampling Axis **禁止** 按数组下标拼接、按浮点深度自动 join、自动插值到第一条曲线、用 Display Depth 替换 Reference Depth |
| T4 | **不隐式重采样** | Resampled Table **仅** 在用户明确选择目标轴 + 插值方法（及缺测/外推策略）后生成，且元数据标识为 Derived/Resampled |
| T5 | **独立对象表** | 区间 / 层位 / 注释保持独立表（引擎 `TableKind` 已预留；Phase A 仅 curves） |
| T6 | **多井按井组织** | 默认按井分工作表组 |
| T7 | **表格读原始样点** | 复制/导出读 raw BufferView，**永不** LOD 包络点 |
| T8 | **Null / 单位 / Reference Depth** | Null = 空单元格（非哨兵字符串）；保留单位与 Reference Depth 类型 |
| T9 | **导出首期** | XLSX、XML、CSV；选区复制同时提供 TSV + HTML Table |
| T10 | **剪贴板上限** | `default_clipboard_cell_limit = 250_000`；超大选择不在 GUI 线程构造巨型字符串，改提示导出 |

引擎已交付：`TableProjection` + `TableProjectionBuilder`、Qt `TableModel`（Phase A curves）、`slice()` 服务选区导出。  
**主机缺口：** WellPlot Desktop 尚未接线 `TableModel` / 表视图 / 图↔表切换；Python 绑定曾刻意推迟 `TableModel` 生成（见 `docs/research/2026-08-03-welllogengine-python-bindings-225.md`）。

---

## 3. ADR 0024 — 图↔表联动硬约束（不可违背）

来源：`docs/adr/0024-shared-semantic-selection.md` +  
`well-log-engine/include/welllog/session/session.hpp`（`SelectionState` / `SetSelectionCommand` / `SetRowSelectionCommand`）+  
`table_model.hpp` Phase B 选区 API。

| # | 硬约束 | 规格含义 |
|---|---|---|
| S1 | **Session 单一持有** | `WellLogSession` 持有 Selection Set；每文档一条选择状态 |
| S2 | **语义身份** | 以稳定井/文档 id、**Sampling Axis**、Reference Depth Range、半开 `[first_row, last_row)`、**Document Revision** 表达 |
| S3 | **禁止像素语义** | **不** 保存屏幕坐标、Display Depth 或 LOD 包络点作为选区真源 |
| S4 | **双向联动** | 图上范围选择 ↔ Table Projection 行范围；`TableModel.set_session_selection_source` + `refresh_session_selection` / `set_row_selection` |
| S5 | **复制读原始样点** | 与 T7 一致 |
| S6 | **修订安全** | 追加尽量保持选择；无法安全映射的替换 **显式失效** 并发布事件（`valid=false` / `selection_invalidated`） |
| S7 | **高频悬停限频** | 在 C++ 内合并限频，避免逐鼠标事件跨 Python 边界 |

当前主机 `MultiTrackCanvas` 的交互是深度 pan/zoom 与层位拾取，**无** 接入 Session Selection Set。引擎 `WellLogView` 支持 Ctrl+drag 深度范围选择（`SetSelectionCommand`）。图/表双视图规格必须把联动锚在 **引擎 Session 选区**，而非主机自建像素选区。

---

## 4. 导入文档如何挂到「井」下；是否有「数据源」层

### 4.1 主机现状（LAS 路径）

```text
workspace.json
  wells[]: WellCatalogEntry { id, name, path, lng, lat, crs }
wells/<well_id>/<file.las>          # import_las_into_workspace 复制
HostSessionStore._docs[well_id]     # ImportedWellDocument
  document_id == catalog well_id    # 稳定 join
  depth: ndarray                    # 单深度轴
  curves: [ImportedCurve...]        # 整文件曲线（首道当深度）
```

引用：`las_import.py` `import_las_into_workspace` / `ImportedWellDocument`；`session_store.py` `ensure_well_loaded`（缺会话则从 `entry.path` 重解析 LAS）。

| 问题 | 结论 |
|---|---|
| 树是否挂曲线？ | **否** — 仅井名叶子 |
| 是否有「数据源」catalog 节点？ | **否** — 只有 `path` 字符串指向单个 LAS 相对路径 |
| 多文件/多源并入一口井？ | **未建模** — 一口 catalog 井 ↔ 一个 LAS 文件路径 |
| 多采样轴？ | **主机否** — 单 `depth[]`；长度不一致时截断/填 NaN 并诊断（非独立轴） |
| 引擎侧 | **有** 一等公民 `SamplingAxis` + 每曲线 `sampling_axis_id`（ADR 0005 文档与渲染分离；TableProjection 按轴分表） |

### 4.2 领域词汇（CONTEXT.md）— 规格应继承

- **Whole-File Log Import**：打开文件时导入全部可用曲线数据集；不同采样轴各自保留，不因曲线名或相邻深度隐式合并/重采样。  
- **Canonical Curve Instance / LIS Data Run**：多数据集、多轴身份在引擎/导入规格中已定义；**主机 LAS 路径尚未实现多轴文档模型**。  
- **Log Source Adapter（ADR 0005）**：引擎只消费 `WellLogDocument`；格式解析在 io 适配器。主机目前自有 `lasio` 适配，与引擎 `LasSourceAdapter` **并行**，尚未统一。

### 4.3 「数据源」层概念

| 层 | 主机 | 引擎 |
|---|---|---|
| 工区 catalog 井 | ✅ `WellCatalogEntry` | ❌（主机职责） |
| 文件/逻辑数据源 | ⚠️ 仅 `path` 字段 | io 适配器产出 Document |
| Sampling Axis | ❌ 扁平 depth | ✅ |
| Curve 实体 | 助记符字符串 | ✅ EntityId + axis |
| 图版绑定 | mnemonic 别名 → BoundTrack | ScenePresentation layers |

**缺口：** 产品目标「数据源下可再挂多井道」在主机 **无** 持久化模型与树节点；引擎 Document 已能表达多轴多曲线，但宿主 catalog / 会话未暴露「源 → 轴 → 曲线」树。

---

## 5. 性能相关实践与规模假设

### 5.1 引擎验收基线（ADR 0014）

参考工作站（8 核 / 32 GB / Iris Xe 级 / 4K）：

- 20 口井、100 可见图道、200 曲线  
- **单曲线最多 50 万点**、总计最多 **1 亿** 标量采样、10 万离散对象  
- 稳态交互 P95 ≤ 16.7 ms；UI 线程单次阻塞 ≤ 8 ms  
- 引擎新增内存峰值 ≤ 原始曲线缓冲 50%；不得把全部原始数据复制到 GPU  

### 5.2 引擎 LOD（ADR 0015）

- 分块层次 M4/Min-Max 包络；按 Display Depth 像素密度选级  
- 视口只上传选中包络点；**表格永不使用 LOD 点**（与 0022 一致）  
- 交互主路径不做逐视口全量扫描或 LTTB  

### 5.3 主机当前实践（临时、不满足引擎基线）

| 路径 | 做法 | 文件 |
|---|---|---|
| `MultiTrackCanvas` 绘制 | 固定 `step = max(1, n // 2000)` 均匀抽稀 | `multi_track_canvas.py` ~L424 |
| Qt 导出 paint | `step = max(1, n // 2500)` | `export_plot.py` ~L181 |
| 表格 | 无主机实现 | — |
| 引擎画布 | 正式 envelope LOD（有 welllog 时） | engine scene |

ADR 0052 已记录：宿主 Qt paint 曲线抽稀 **无 LOD 包络**，是已知临时缺口。

### 5.4 表格性能含义（规格侧）

- 百万行表靠 **虚拟化按需读**，不靠预构建 DataFrame。  
- 剪贴板 ≤ ~25 万 cell；更大必须走文件导出。  
- Excel 单表 ≤ 1,048,576 行；超限拆连续工作表（`table-and-export.md` §5.1）。

---

## 6. 不可违背清单（后续 grilling 锁点）

规格与原型 **不得** 违背：

1. **表格 = 文档修订的投影**，与图形共享 Entity / Reference Depth / Null / 单位；不共享像素或 LOD 点（ADR 0022 + `table-and-export.md` §1）。  
2. **异轴默认分表**；任何跨轴对齐必须是用户显式 Resampled Table（0022 T3–T4）。  
3. **Selection Set 语义化**，由 Session 持有；图↔表双向联动；失效可观察（0024 S1–S6）。  
4. **复制/导出读原始样点**，永不读 LOD（T7/S5）。  
5. **虚拟化 TableModel**；禁止为整井曲线构建全量 QStandardItem/DataFrame 进 UI 线程（T1）。  
6. **图道布局（HostPresentation/BoundTrack）与井数据（ImportedWellDocument / WellLogDocument）分离**；勾选「显示」改布局/可见层，不改源文档身份（主机已用 track_overrides 体现）。  
7. **整文件导入 + 不隐式重采样/合并轴**（CONTEXT Whole-File Log Import）。  
8. **规模叙事对齐 ADR 0014**（50 万点/曲线、1 亿总量级）时，交互路径必须走引擎 LOD/TableProjection，而非主机 `n//2000` 抽稀。  
9. **引擎不拥有产品树 IA / 工区文件**（ADR 0011 / 既有 research #215）；数据树是 **主机** 规格。

---

## 7. 开放缺口清单（grilling / 规格待决）

| ID | 缺口 | 备注 |
|---|---|---|
| G1 | **每井数据树 IA** | 树目前只到井级；需定义节点：数据源 / 采样轴 / 曲线 / 非标量井道（成像等） |
| G2 | **「数据源」持久化模型** | catalog 仅 `path`；多 LAS/LIS 段/多文件并井未定义 |
| G3 | **主机多采样轴文档** | `ImportedWellDocument` 单 depth；与引擎 Document / 0022 分表不对齐 |
| G4 | **可见性真源** | 图道 `track_overrides.visible` vs 未来「曲线勾选显示」vs 图版绑定 — 合并规则未定（map #331 Not yet specified） |
| G5 | **未绑入图版的曲线** | 如何进树、如何「勾选后自动生成/扩展图道」、宽度/颜色算法 |
| G6 | **图/表主视图切换** | 无 UI；TableModel 未进宿主；Python 绑定 TableModel 状态需确认 |
| G7 | **主机 Selection 接线** | MultiTrackCanvas 无 Session 选区；双路径（host paint vs WellLogView）如何对等 |
| G8 | **层位/区间表** | `TableKind::intervals|markers` 预留未建；tops 在主机 `tops_model` 侧 |
| G9 | **勾选状态持久化位置** | 工作区 / 图件 / 独立显示配置（map 已列） |
| G10 | **性能路径选择** | 表模式强制引擎投影；图模式是否强制 WellLogView（弃用 n//2000） |
| G11 | **导入身份与归一化** | CONTEXT 中 Imported Log Identity / 归一化配置；主机 lasio 路径未落地指纹与 resform-compatible 全规则 |
| G12 | **连井是否复用同一井内数据树** | map Not yet specified |

---

## 8. 建议 grilling 输入顺序

1. 锁定 **数据树信息架构**（G1）与 **可见性 vs 图版**（G4/G5）— 否则无法写可实施规格。  
2. 锁定 **表格模式 = 引擎 TableProjection + Session Selection**（不可违背 §6），再定宿主切换 UX（G6/G7）。  
3. 明确 **单轴 LAS MVP vs 多轴 Document** 分期（G2/G3）— 影响树深度与 0022 分表是否首期可见。  
4. 将 ADR 0014 规模写进验收句，排除主机均匀抽稀作为正式交互路径（G10）。

---

## 9. 关键源索引

| 主题 | 路径 |
|---|---|
| 工区树 / 图道列表 / apply | `well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py` |
| 模板编译 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/template_model.py` |
| 工区 catalog | `well-log-engine/apps/wellplot-desktop/well_log_workstation/workspace.py` |
| LAS 导入 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/las_import.py` |
| 会话文档 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/session_store.py` |
| 图件持久化 / track_overrides | `well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py` |
| 主机画布 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/multi_track_canvas.py` |
| 引擎桥 | `well-log-engine/apps/wellplot-desktop/well_log_workstation/engine_bridge.py` |
| 领域词 | `CONTEXT.md` § Well Log Visualization |
| 表格 ADR | `docs/adr/0022-virtualized-table-projections.md` |
| 选区 ADR | `docs/adr/0024-shared-semantic-selection.md` |
| 性能/LOD ADR | `docs/adr/0014-…`, `docs/adr/0015-…` |
| 表格设计书 | `well-log-engine/docs/table-and-export.md` |
| TableProjection API | `well-log-engine/include/welllog/table/table_projection.hpp` |
| TableModel API | `well-log-engine/include/welllog/qtwidgets/table_model.hpp` |
| Selection API | `well-log-engine/include/welllog/session/session.hpp` |
| 既有引擎缺口研究 | `docs/research/2026-08-03-welllogengine-gaps-for-workstation.md` |
