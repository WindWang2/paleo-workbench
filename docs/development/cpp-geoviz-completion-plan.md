# geo-viz-engine 剩余 C++ 化计划（CONV-VIZ 线，细化主计划 M8/M10 的 viz 部分）

基线：`main` @ `83eac12e`（2026-09-19，含 UI-03–UI-07 转换浪潮与 swarm 审查 #1380–#1392）。
目标口径：与主计划一致——**以用户流程验收**衡量完成度（C++ 主程序能打开→解析→显示→交互→导出该可视化能力），不以行数折算。行数仅用于排期与盘点。

## 0. 为什么需要本计划

`geo-viz-engine/`（独立 Python 引擎，约 5.8 万行产品码）的 C++ 化已有大量落地，但分散在
M1–M3、CONV-GEO3D、UI-04/07 等批次里，剩余部分缺一张统一的收口图。本文档：

1. 冻结**现状基线**（哪些已迁移、**主程序接线到什么程度**、证据在哪）；
2. 盘点**剩余量**（逐模块、逐行数、逐批次去向）；
3. 定义 **V1–V6 六个收口批次**的范围、落点、主程序接线点、验收门与依赖；
4. 声明风险与硬前置（含 swarm 审查发现的 P1 并发问题、WLE SDK 收敛决策）。

## 1. 现状基线（已完成，不重复实现）

> 证据链：各批次 ledger（`docs/development/cpp-geoviz-3d/`、`cpp-seismic-viewer/`、
> `cpp-seismic-native-stack/`）+ 主计划进度记录 + 主程序 guard 宏实测。

### 1.1 能力 → C++ 落点

| geoviz 能力 | Python 源 | C++ 落点 | 状态 |
|---|---|---|---|
| 地震属性计算 | `geoviz_seismic/attributes*.py` | `libs/seismic_attributes`（5.4k 行） | ✅ M1/E 线，oracle 对账 |
| SEG-Y 读取 | `geoviz_seismic/loader.py` 等 | `libs/seismic_io`（2.1k 行） | ✅ M3，逐样本对冻结 oracle |
| 地震 2D 切片视图 | 旧 geoviz seismic panel 语义 | `libs/seismic_viewer`（native_no_python_origin） | ✅ CPP-D v3 |
| 3D 场景运行时（相机/场景对象/拾取/剖切/GL viewport） | `geoviz_seismic/renderer_3d.py`、`scene_objects.py`、`gl_clipping.py` | `libs/geo3d_viz`（4.1k 行） | ✅ CONV-GEO3D，27/27；真 GL 像素验证未做（如实） |
| geomodel 科学核 | `viz/geomodel/*` | `libs/geomodel`（CONV-12/22） | ✅ 复用 |
| 井 log 宿主壳/轨道布局/文档计划/**LAS 解析** | `geoviz_well_log` 宿主部分 | **WLE SDK**（`well-log-engine/`，外部 SDK，io 覆盖 las/lis/dlis/format716）+ `libs/visualization` 适配器（`Pwb::VisualizationWellLog`，94 处 `welllog::` 调用的薄适配） | ✅ 已存在但 **opt-in**（见 1.2）；ingest/ui_workers 未复用（见 V1） |
| 井 log 加载 worker（取消/迟到丢弃语义） | `ui/pages` worker | `libs/ui_workers/well_log_load` + `viz_resolve` | ✅ UI-04；**load_fn 是 seam，解析核未接**（见 V1） |
| XML 井曲线预览 | `geoviz_well_log/xml_preview.py` | `libs/ingest/preview/well_log_xml_preview` | ✅ 大部；余量随 V1 收口 |
| 预览页面管线（表格/图像/PDF/媒体/JSON/切片/GeoTIFF） | `geoviz` 门面 + previews | `libs/ui_pages_preview`（6.6k 行）+ `ingest/preview` registry | ✅ UI-07（lib 级；主程序接线见 1.2） |
| plots 计算核（等值线/插值/CRS/因子） | `geoviz_plots/{contour_draft,interpolation,crs,factor}` 计算半 | `libs/mapping_kernel`、`factor_host` + `ui_workers/{contour_draft,factor_prepare}` | ✅ 冻结案例全过 |
| 井间 worker + DTW 核 | `geoviz_cross_well` 计算半 | `ui_workers/{correlation_load,dtw_propagation}` + `libs/well_science/dtw` | ✅ 计算半；渲染本体未迁（见 V3） |
| 古地理图/2D 地图 | `geoviz_paleo_map` + `geoviz_map` | QGIS 原生栈（`ui_map`、`ui_widgets/qgis`、`mapping_bind`、`native/*` 扩展） | 🔀 架构性替代，归 V10/wayfinder 拓扑编辑线，**不入本线** |
| Python 产品原地加速 | — | `native/{grid_render,layer_model,seismic_3d,well_log}_core` + 引擎仓 `native/map_edit_core` + WLE 的 python 绑定 | ✅ 服务 Python 产品线，随 M12 一起退役 |

### 1.2 主程序接线现状（`apps/paleo_workbench_platform`）

| viz 面 | 主程序接线 | 编译 guard | 在默认集成门禁中？ |
|---|---|---|---|
| QGIS 画布/图层树/约束/阶段/因子 dock | ✅ 已挂（`main_window` 成员） | `PWB_BUILD_PLATFORM` | ✅ |
| 地震 2D dock（`SeismicSliceWidget`）+ SEG-Y 导入 | ✅ 已挂（`seismic_dock_`/`importSegyDialog`） | `PWB_WITH_SEISMIC_VIEWER` | ✅ |
| 3D geomodel dock | ✅ 已挂（`geo3d_dock_`） | `PWB_WITH_GEO3D_VIZ` | ❌（默认 OFF） |
| 井 log dock（`WellLogTrackPanel` + WLE 宿主，含 `loadLasIntoDock`） | ✅ 已挂，但依赖 `Pwb::VisualizationWellLog` target | `PWB_SCIENCE_BUILD_VIEWER`（默认 OFF）→ `PWB_WITH_WELL_LOG` | ❌（门禁只开 `PWB_BUILD_SCIENCE`，未开 VIEWER） |
| 数据/预览页面（`ui_pages_data`/`ui_pages_preview`/`ui_workers`） | ❌ **零接线**（apps/ 无引用；UI-04/06/07 是 lib-ready） | 无 guard（未消费） | ❌ |

**由此得出的两个接线前置（本计划显式依赖，不自己兜底）**：

- **P-A（预览/数据页接线）**：V1 的"`.las` 产出真预览"与 V6 的"数据面板出图"，其用户可见验收依赖 `ui_pages_preview`/`ui_pages_data` 挂进主程序——该接线属主计划 M10/CONV-26 面板簇。接线前，本线验收以 lib 级测试（`ui_pages_preview_tests` 等）+ example 为准，并在 ledger 如实标注。
- **P-B（well-log 门禁口径）**：井 log 链的用户可见验收依赖 `PWB_SCIENCE_BUILD_VIEWER=ON` 进入 `run-integrated-gate.sh`（或至少进入本线专用验证脚本）。是否纳入默认门禁是独立决策（SDK 依赖 + Qt 6.8+ 约束），本计划只要求：V2 开工前定口径，不定则以 opt-in 构建验证。

### 1.3 Python 主产品关联（改动边界）

- Python 主产品（`paleo_workbench`）经 `geoviz` 门面、`native_backend.py`（扩展发现 + 纯 Python 回退）、WLE python 绑定继续使用 geo-viz-engine，**直至 M12 切换**；本线所有改动不得破坏该路径（C++ `ingest/preview` registry 是 C++ 应用专用，改 LAS 分支不影响 Python 侧）。
- 本线开工期间 geoviz 对应模块进入行为冻结（bug 修复除外），oracle 以冻结版本为准。
- Python 侧文件迁移后加 docstring 标注：`legacy reference`（行为冻结源）或 `oracle-only`。

## 2. 剩余量盘点（本线负责，净约 2.3 万行 + 审计项约 3.1k）

> 口径说明：行为数含 glue/config；V1/V2 经 WLE SDK 收敛后，**实际新写 C++ 量会显著小于**对应 Python 源行数（见各批决策门）。

| # | 模块 | Python LOC | 关键文件 | 去向批次 |
|---|---|---|---|---|
| R1 | LAS 预览 + xml_preview 余量 | ~1.1k | `las_preview.py`(620)、`las_parser.py`(74)、`xml_preview.py` 余量(≤368) | **V1** |
| R2 | 井 log 绘制核与场景 | ~5.4k | `renderer/*`（canvas 525/curve_track 357/track_base 191/overlay 174/downsample 131/depth_ruler 128/interaction 140）、`scene/*`（≈1.1k）、`section/*`（section_canvas 308/inter_well_link 88/datum_transformer 42）、`tracks/image_track`(95)、`qpainter_builder`(180)、`pattern_map`(142)、`chart_engine`(144)、`connection_overlay`(134)、`painter_sync_manager`(36)、`robust_scale`、`well_log_view`(182)、`export_qpainter`、`location_map`、`image_preview_dialog`、`models`/`config` | **V2**（先过 WLE 重叠决策门） |
| R3 | 井间对比剖面 | ~3.8k | `geoviz_cross_well/*`（canvas 640、formation_preview 280、picks_model 272、report_export 228、auto_section_planner 172、tops_model 133；dtw_engine 复用 `well_science/dtw`）+ `geoviz_well_log/cross_well_widget.py`(603) | **V3** |
| R4 | 井震标定（well tie） | ~1.3k | `geoviz_well_tie/*`（synthetic 190、calibration 178、canvas 155、auto_tie 140、report_export 139 等 13 文件）；synthetic_points worker 已有 | **V3** |
| R5 | 井震联合 3D 剩余 | ~4.9k | `well_seismic_3d/*` 剩余（package 6061 − joint_widget 直通 API 1134）：`scene.py`(1390)、`segy_survey`(518)、`profile_2d`(351)、`well_geometry`(293)、`survey`(201)、`registration`(182)、`time_map_2d`(173)、`fence`(145)、`depth_transform`(115)、`color_scales`(108)、`probe`/`volume_access`/`models` | **V4** |
| R6 | 地震 2D 边角（产品路径） | ~1.9k | `profile_vd`(1259，VD 变密度剖面)、`profile_wiggle`(290)、`horizon`(243)、`crossplot`(56)、`colorbar_widget`(51)、`isosurface`(26) | **V5** |
| R6a | 地震基础件（待审计） | ~3.1k | `chunked`(881)、`workers`(577)、`preview_widget`(528)、`vram_cache`(353)、`chunked_worker`(276)、`lod`(189)、`cache`(180)、`gpu_ops`(154)、`profile_widget`(168)、`seismic_view` | **V5 审计门** |
| R7 | plots 绘制本体 | ~3.5k | `chart/`(1849)、`surface/`(902)、`fence/`(136)、`analytics/`(79)、`factor/` 绘制半 | **V6** |
| R8 | stratal/colormap 差量 | ~0.7k | `stratal.py`(310) 对照 `ui_workers/stratal` 核覆盖差；`colormap.py`(358) 与 `seismic_viewer/color_maps` 对照补差集 | **V5** |

**不入本线**（如实声明）：`geoviz` 门面 + `geoviz_common`（2.7k，C++ 侧已有架构性替代管线，门面本身只服务 Python 产品，随 M12 退役）；`geoviz_paleo_map`/`geoviz_map`（8.7k，QGIS 替代线 + V10 拓扑编辑进行中）；`plots/map_edit`（1.9k，同前）；`web_dist`/archive（死代码）；`gpu_ops` 的 GPU 路径（先 CPU parity，见 V5）。

## 3. 批次计划

通用约定（每批一律遵守，不再逐批重复）：

- 一个批次 = 一个 branch/worktree + 一份 ledger（`docs/development/cpp-viz-vN/`，含 scope-ledger 与迁移说明，格式沿 CONV-GEO3D）。
- 纯核先行：Qt-free 计算核 → 冻结 Python oracle 对账 → Qt 组件接线（沿 M1–M3 方法论）。
- oracle：新增 `tools/oracle/generate_viz_*_fixtures.py`，冻结值自 Python 源精确转录，**必须含负面 self-check**；M11 的 oracle 退役在对应批次完成时同步执行。
- 验收门：新增 ctest 全绿 ×2 + 既有回归不降级 + `scripts/cpp-migration/run-integrated-gate.sh` 通过（含 MALLOC 审计；资源约束 -j2/-j3，编译 0 警告 -Wall -Wextra -Wpedantic）。
- **主程序接线**：每批声明接线点与 guard 宏；接线未进默认门禁的（P-A/P-B 前置未决），以 opt-in 构建 + lib 测试验收并在 ledger 如实标注。
- worker 接线一律走主程序既有 `JobCenter`/`JobOwner`（queued 回 GUI），不自建线程通道。

### V1 — LAS 路径收敛（消除双轨，不新写解析器）

- **前提修正（相对旧版计划）**：C++ 侧**已有** LAS 解析——WLE SDK `LasSourceAdapter::parse`（`well-log-engine/src/io/las.cpp:155`），且主程序 well-log dock 已消费（`main_window.cpp:1913 loadLasIntoDock` → `WellLogHostWidget::load_las`，`well_log_host_widget.cpp:604`）。双轨缺口在 **ingest 预览线与 ui_workers 线**：`ingest/preview/registry.cpp` 的 LAS 分支返回 "ModuleNotFoundError" parity 消息，`ui_workers/viz_resolve.cpp:127` 返回"无法解析 LAS 井数据"占位。
- **范围**：把 WLE 的解析结果桥接进 (a) `ingest/preview` 的 LAS 预览（替换 ModuleNotFoundError 分支，行为对齐 `las_preview.py` 的预览构建）；(b) `ui_workers/well_log_load` 的 `load_fn` seam（注入真解析）。`las_preview.py` 的预览组装逻辑（曲线选择/统计/截断）为 Qt-free 核。
- **对账门（新增）**：WLE parser vs lasio 行为差异 oracle——以 `las_preview.py`+lasio 输出冻结 fixture（含变体：多 section、缺曲线、坏行、深度倒序、非 ASCII），WLE 差异逐条裁决（改适配层或修 fixture 口径并记录）。WLE 的 lis/dlis/format716 超出 geoviz 范围，不对账、不迁移，如实声明。
- **验收**：`ui_pages_preview` lib 测试对 `.las` 产出真预览（非 message result）；opt-in 构建下主程序 well-log dock 载 LAS 出轨道（既有路径回归）；fail-closed 不静默丢行（对照 #1386 教训）。
- **主程序接线**：无新增（消费既有 dock + 待接线预览页，见 P-A）。
- **依赖**：无。

### V2 — 井 log 绘制核（先过 WLE 重叠决策门）

- **决策门（先决，产出记录进 ledger）**：WLE SDK 已含 `render_gl`/`scene`/`qtwidgets`/`export_vector`/`export_raster`/`export_table`/`session`——与 R2 的 renderer/scene/export 高度重叠。逐模块判定：**采用 WLE**（多数预期）/ **补适配缺口** / **自绘补齐**（仅 geoviz 特有行为，如 `pattern_map` 岩性填充、`location_map`、`connection_overlay`、`chart_engine` 特化）。决策依据 = 与 `geoviz_well_log` 冻结行为 oracle 的差距清单，避免移植出第二套绘制栈。
- **范围**（决策门后收缩）：Qt-free 半（downsample、robust_scale、track 布局计算）+ 差距清单补齐 + `section/*`（井剖面 canvas，WLE 无直接对应）。
- **验收**：布局计算以几何 spec oracle 冻结；渲染 offscreen smoke（grab 非空 + 关键像素断言）；导出与 Python 端像素容差对账（容差在 ledger 声明）。
- **主程序接线**：well-log dock（`PWB_WITH_WELL_LOG`）；**P-B 口径在此批开工前定**（是否把 `PWB_SCIENCE_BUILD_VIEWER` 纳入门禁）。
- **依赖**：V1（曲线数据链完整）；决策门。

### V3 — 井间对比与层位标定（cross-well + well tie）

- **范围**：R3 + R4 → **扩展现有 `libs/visualization`**（Qt-free 半：picks/tops 模型、auto_section_planner、标定/合成计算；Qt 半：剖面 canvas、相关带、报告导出；复用 V2 场景原语）。`dtw_engine` 不重写，接 `libs/well_science/dtw`。
- **验收**：picks/tops 编辑回路（增删改→持久化→重开还原）；DTW 对比对 `generate_dtw_fixtures.py` 既有 oracle；合成记录标定数值核冻结 oracle；报告导出非空。
- **主程序接线**：新增 cross-well dock/页（挂 `main_window`，guard 宏随批定义，进默认门禁）。
- **依赖**：V2。

### V4 — 井震联合 3D 场景

- **范围**：R5 → `libs/geo3d_viz` 扩展：survey/segy_survey（体加载复用 `libs/seismic_io`，不重写读取器）、well_geometry、fence/probe、registration、time_map_2d、depth_transform、color_scales、`scene.py` 联合场景组装；接线 CONV-GEO3D 预留的 `SceneTransform` seam（其 out-of-scope 在本批收回）。
- **验收**：井+震联合场景 offscreen smoke（GL-less 诚实降级路径全功能）；state JSON 存取复用 `workspace_controller` 七键 schema。
- **主程序接线**：`geo3d_dock_` 扩展（`PWB_WITH_GEO3D_VIZ`）；体 tile 加载走 `JobCenter`/`JobOwner`。**硬前置 #1380/#1381**（见 §5）。
- **依赖**：`seismic_io`/`geo3d_viz`（已就绪）。

### V5 — 地震 2D 边角 + 基础件审计

- **前置审计门（先审后动）**：R6a 逐项判断是否已被 `seismic_io + slice_controller + tile_cache + job_runtime + seismic_slice_preview_widget/seismic_viewer` 等价覆盖（`preview_widget`/`seismic_view`/`profile_widget` 预期已替代）；已覆盖 → 标 legacy reference 不迁；未覆盖 → 仅迁缺口。审计结论写进 ledger，避免重复建设。
- **产品路径**：R6 + R8 → `libs/seismic_viewer`/`ui_pages_preview` 扩展（`seismic_slice_preview_widget` 已有，补 wiggle/VD/horizon 呈现）；`colormap.py` 对照补齐差集；`stratal.py` 与 `ui_workers/stratal` 核对覆盖差；`gpu_ops` 只保证 CPU parity（GPU 路径明确不迁，降级诚实）。
- **验收**：VD/wiggle 切片渲染 offscreen 断言；horizon 拾取/编辑回路；crossplot 产出。**`PreviewKind` 能力清单收口（如实版）**：well_log（V1/V2 后 ✅）、seismic_2d（✅ 已有）、xy_scatter（本批补）、surface（V6）、time_depth（V3）；**formation_tops 无预览呈现**——C++ 只有解析器（`ingest/well_tops.cpp`，消费方是 `prediction/postprocess` 编图管线），预览呈现归属本批裁决：补做或显式声明"由编图管线消费、不做预览页"。
- **主程序接线**：`seismic_dock_`/预览页扩展；profile 走 worker 的部分**硬前置 #1380/#1381**。
- **依赖**：`seismic_attributes`/`seismic_viewer`（已就绪）。

### V6 — plots 绘制本体（含 surface）

- **前置决策门**：chart/surface 的 C++ 承载选型——QPainter 自绘（与 V2 绘制原语复用，推荐，无新依赖）vs 引入第三方图表库（Qwt/QCharts，增依赖与许可评审）。决策记录进 ledger 后开工。
- **范围**：R7 → `libs/ui_pages_preview`/新 `libs/viz_charts`：chart 系列、surface 渲染、fence 图、analytics 汇总、factor 绘制半（计算半已迁）。
- **验收**：数据面板对 factor/surface 资产出图（截图非空 + 数据点抽验）；既有 `contour_draft/factor_prepare` worker 的呈现端接通（依赖 P-A）；matplotlib 特性（对数轴/双轴/图例）逐项以 oracle 冻结或显式降级声明。
- **主程序接线**：数据/预览页（P-A 前置）。
- **依赖**：V2（绘制原语）；决策门；P-A。

## 4. 排序与预估

推荐顺序 **V1 → V2 → V3 → V4 ∥ V5 → V6**（V4 与 V5 无相互依赖，可并行开 worktree；V6 在 V2 后任意时点按决策门插入）。

| 批次 | Python 源 | 预估新写 C++* | 备注 |
|---|---|---|---|
| V1 | ~1.1k | ~0.8k | 桥接 + 预览组装核，**不新写解析器** |
| V2 | ~5.4k | 0.5k–5k（决策门后定） | WLE 重叠度决定 |
| V3 | ~5.1k | ~5k | cross-well + well tie |
| V4 | ~4.9k | ~5k | 联合 3D |
| V5 | ~1.9k + R8 0.7k（+审计项） | ~3k | 含审计门 |
| V6 | ~3.5k | ~4k | 含选型决策门 |

\* 按既有批次 1.1–1.3× 经验粗估（V2 除外，见决策门），**非承诺**；每批过门以验收为准。

## 5. 硬前置与风险（如实）

1. **#1380/#1381（P1，catalog store 无跨线程序列化）**：约束 **V4（体 tile 发布）与 V5（属性 profile 发布，即 #1381 的确切路径）**的 worker→store 接线，必须先修复；V1/V3 的加载与绘制是纯文件/UI 路径，不触碰 store，不受此约束（除非后续把"导入落库"纳入）。
2. **#1382/#1383（asset_view UB）**：任何资产表面板/预览接线前修复（接线即触发的地雷）。
3. **接线前置 P-A/P-B**（§1.2）：预览/数据页未挂主程序、well-log viewer 不在默认门禁——用户可见验收受制于 M10/CONV-26 的接线进度，本线不兜底、如实标注。
4. **WLE 收敛风险**：V1 对账门若发现 WLE 与 lasio 行为分歧大，适配成本可能上升；V2 决策门若判定自绘比例高，则 V2 逼近原估上限。两门都在批次最前端，早暴露。
5. **GL 像素验证缺口**（CONV-GEO3D 遗留）：V4 沿用 offscreen GL-less 诚实降级 + 编译级验证；真 GL smoke 需有 GL 的环境补跑一次，未跑前在 ledger 如实标注。
6. **绘制像素对账的容差口径**：QPainter/WLE 与 matplotlib 反走样/字体渲染天然有差，容差与豁免项必须在各批 ledger 显式声明，不默认全绿。
7. **资源约束**：编译 -j3 上限、门禁 -j2（沿 CONV-GEO3D 约定）；本机无 QGIS SDK 时平台 app 不做本地构建验证，lib + tests + example 全量本地验证；WLE 需 Qt 6.8+（P-B 决策输入）。

## 6. 与其他线的关系

- 主计划 `cpp-conversion-main-plan.md`：本文件细化其 **M8**（"viz 其余，2 万行分期"）并衔接 M10（UI 面板接线 = P-A）与 M11（oracle 退役）。
- **science_suite/WLE SDK 线**（`libs/science_suite`，`PWB_SCIENCE_BUILD_VIEWER`/`PWB_SCIENCE_VIEWER_TESTS`）：V1/V2 的解析与绘制基座；SDK 版本升级与 P-B 门禁决策在该线协调。
- V10/wayfinder 拓扑编辑线（#1278–#1283）：paleo_map/geoviz_map 的归属，与本线零交集。
- 审查线：#1380–#1392 为本线的前置修复清单；V 批次实现中新增的审查发现按现行 issue 流程提交。

## 进度记录

- 2026-09-19：计划建立（基于 83eac12e 基线的现状盘点与 swarm 审查结论）。
- 2026-09-19（同日，rev2）：按 review 修正——补主程序关联（§1.2/§1.3、各批接线点、P-A/P-B 前置）；发现并纳入 WLE SDK 既有 LAS/绘制栈，V1 改为收敛双轨、V2 加重叠决策门；修正 R2/V3/V5 行数（R2 补 section/tracks 等 ~740 行；V3 汇总 4.5k→5.1k；V5 拆 R6/R6a 并点名 preview_widget/seismic_view 入审计）；formation_tops 声明改为"解析已有、预览未做、归属待裁"；#1380/#1381 硬前置收窄至 V4/V5；V3 落点定为扩展 `libs/visualization`；通用约定补 MALLOC 审计。
