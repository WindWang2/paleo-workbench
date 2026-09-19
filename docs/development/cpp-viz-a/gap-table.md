# VIZ-A 差距表：geoviz_well_log → WLE SDK → Workbench

基线：geo-viz-engine `@ 08851951`（行为冻结源）、well-log-engine `@ f845e7ab`（只读 SDK）、
PWB `origin/main @ 7290f727`。判定口径：**逐行为**（非按文件名），三值：
`直接复用`（WLE/PWB 既有实现，给出证据）/ `适配缺口`（WLE 有基座，本线补适配层并证明）/
`确认缺失须补`（无基座，本线补齐）或 `有依据排除`（给出排除依据，不无据剔除困难项）。

已存在不重写（本计划 §V1/V2 明确排除，PR #1359 已落地）：LAS 解析本体（WLE
`LasSourceAdapter`，`well-log-engine/src/io/las.cpp:155`）、WLE 渲染器/场景/export 栈
（`WellLog::RenderGL/Scene/QtWidgets/ExportVector/ExportPdf/ExportRaster/ExportTable/Session`）、
轨道布局/模板/游标/缩放（`pwb_visualization_well_log` 的 `well_log_track_layout`、
`WellLogHostWidget` 命令面，PR #1359）、PNG-SVG-PDF 导出适配（host `export_png/svg/pdf`）、
已迁移设置页（`WellLogTrackPanel` dock）、worker 生命周期（`libs/ui_workers` UI-04，PR #1375）。

## 1. 解析/数据链（V1）

| # | geoviz 行为（Python 源） | 判定 | 证据/落点 |
|---|---|---|---|
| A1 | LAS 头解析（版本/WRAP/DLM/井名/NULL/~C 定义/深度道判定，`las_preview.py:126-214`） | 直接复用 + 适配缺口 | WLE `las.cpp:155-417` 覆盖 VERS/WRAP/NULL/~C/深度道；**井名（`WELL.`）WLE 不提取**、DLM 逗号/制表分隔 WLE 不支持（`tokens_in` 只切空格/制表，`las.cpp:84-97`）→ 本线 bridge（`libs/ingest` LAS preview 专用文件）补头扫描 + DLM 归一 |
| A2 | 有效行统计（tokens≥列数、深度可解析/有限/非 null，`las_preview.py:98-125`） | 直接复用（口径差记录） | WLE 丢 short/long/坏值/坏深度行并出诊断（`las.cpp:270-363`）；Python 的 `≥` 口径（长行算有效）vs WLE 长行丢弃 → 对账裁决 R3（见 reconciliation.md） |
| A3 | null sentinel（默认 -999.25；`isclose(atol=1e-6)` 判定，`las_preview.py:77-78`） | 直接复用（口径差记录） | WLE 从 `~W NULL.` 精确读、无默认值、`==` 精确比较（`las.cpp:220-226,286-321`）→ 裁决 R4 |
| A4 | 深度倒序/重复/混合 | 直接复用（口径差记录） | WLE 单调升/降均可（方向入 `SamplingAxis.direction`），混合方向整体 invalid（`adapter_common.hpp:92-108`）；重复深度保留不诊断 → 裁决 R5/R6 |
| A5 | 曲线元数据（mnemonic/unit/description，`~C` 顺序含深度道） | 直接复用 | WLE `parse_curve_definition`（`las.cpp:132-151`）保留 mnemonic/unit/display_name；bridge 重组含深度道的原序表 |
| A6 | 重复 mnemonic 消歧 `_{n}`（`las_preview.py:406-430`） | 确认缺失须补（预览不需要；轨道层已有等价） | 轨道层 index-based 重名安全键已在 PR #1359 `well_log_track_layout` 落地；ingest 预览表按原 mnemonic 呈现（与 Python 预览一致，无渲染缓存键问题）→ 不补，记录依据 |
| A7 | 多 section（`~O`/`~P`） | 有依据排除 | WLE 归 `LasSection::none` 忽略（`las.cpp:193-194`）；lasio 保留但 `las_preview` 从不展示；预览无行为差 → 不补 |
| A8 | Unicode 路径/井名 | 直接复用 | WLE parse 收 `string_view` 无 IO；宿主 QFile/QString/UTF-8 字节流处理（host `well_log_host_widget.cpp:604` 先例）；bridge 沿用 |
| A9 | 预览组装（曲线选择/摘要行/曲线表截断/数据表 100 行 `%.4f`/NaN 显示/警告拼接，`well_log_parsers.py:46-152`） | 确认缺失须补 | ingest registry LAS 分支现为固定 `ModuleNotFoundError`（`registry.cpp:221-241`）→ 本线 `libs/ingest/src/preview/las_preview.cpp` + WLE bridge target |
| A10 | XML 井曲线预览余量（`xml_preview.py` 区间挖掘/颜色/单位推断） | 有依据排除（本线范围） | C++ `well_log_xml_preview.cpp` 已覆盖 SpreadsheetML/WITSML 主路径（UI-07）；区间挖掘（岩性/地层 worksheet）属绘制数据链，无预览页消费差异记录；本线不动，E 线预览页接线时如需再立项 |

## 2. 绘制核（V2）

| # | geoviz 行为 | 判定 | 证据/落点 |
|---|---|---|---|
| B1 | 曲线轨道渲染（canvas/curve_track/track_base） | 直接复用 | WLE `Scene`（`ScenePresentationBuilder` add_track/add_scale/add_curve_layer，`scene.hpp:382-410`）+ `RenderGL` + `WellLogView`（PR #1359 已消费）；PR #1359 `well_log_document_plan` 12 案例 parity |
| B2 | 岩性图案 pattern_map（38 中文名→pattern id + ~110 中文名→色，模糊子串匹配，`pattern_map.py`；`pattern_engine.py` SVG tile brush） | 适配缺口 | WLE 有 `PatternDefinition`/受限矢量基元（`scene.hpp:195-235`）与 `IntervalLayerSpec.semantic_filter`/`IntervalSemantic::lithology`（`document.hpp:416-438`）；**缺中文岩性→图案/颜色映射数据与模糊匹配** → 本线 `viz_a_pattern_map`（Qt-free 表+匹配+WLE PatternDefinition 构造），视觉容差在 ledger 声明 |
| B3 | 位置图 location_map（`location_map.py`，200×200 井位小地图） | 有依据排除（无消费方） | 全仓 src/主产品零消费（仅定义）；井位平面图产品路径由 QGIS 栈（`ui_map`）承担 → 不迁，依据=消费方审计 |
| B4 | 连接覆盖 connection_overlay（井间相关四边形，`connection_overlay.py`） | 直接复用（B 线消费） | WLE `CrossWellOverlay`（horizon_line/correlation_band，`session.hpp:121-143`）+ `SetCrossWellOverlaysCommand` + `append_surface_overlay_geometry`（`scene.hpp:955-978`）；任意折线走 `add_custom_layer`；归 V3/B 线（本线只记录） |
| B5 | 特化图表 chart_engine（`chart_engine.py`，ECharts/QWebChannel） | 有依据排除（旧栈） | ECharts/WebEngine 渲染栈，src/ 主页面零消费（仅 tests）；V6/E 线图表选型另议（QPainter 自绘 vs 第三方）→ 不迁，依据=消费方审计+技术栈替代决策门 |
| B6 | 剖面 section（section_canvas/inter_well_link/datum_transformer） | 直接复用（WLE 多井面）+ 适配留给 B | WLE 统一多井 surface：`SetWellLayoutCommand`/`compose_multi_well_scene`（`scene.hpp:948`）、`DepthTransform`（`scene.hpp:43-113`）、`AlignWellsToMarkersCommand`（`session.hpp:97-117`）；geoviz 的 Bezier 平滑 horizon 线/相带四边形由 correlation_band/surface overlay 基座承担；**B 线直接用主线 WLE API，不依赖本分支**（api-handoff.md 说明） |
| B7 | 图像轨道 image_track（岩心照片段+占位框；FMI 数据类无渲染，`tracks/image_track.py`） | 适配缺口（照片段） | WLE `ImageSource`（按深度注册/dpi/宿主解码，`document.hpp:405-414`）+ `ImageLayerSpec` + `ImagePyramid`（ADR 0042）；本线补 `CorePhotoSegment→ImageSource` 映射说明；FMI 渲染 Python 侧本就未实现（死数据面）→ 不补，依据=行为本不存在 |
| B8 | 深度尺 depth_ruler（`renderer/depth_ruler.py` + `track_base.nice_depth_interval`） | 直接复用 | WLE `axis_ticks.hpp:30-70` 头注释明确与 Desktop `depth_ruler.py` parity（`nice_axis_ticks/format_axis_tick_label/ticks_for_secondary_axis`）；导出侧 `ExportPageSpec.show_depth_ruler` |
| B9 | 降采样 downsample（min-max 每bin两点+缺口首样本，`renderer/downsample.py`） | 直接复用（轨道）+ 适配缺口（预览） | 轨道：WLE `CurveLodPyramid`（层次包络 ADR 0015）+ `WellLogView` 内建；预览：las_preview 的 min-max binning 语义（NaN 排名 +inf、必含最深行）在 ingest 预览核心对齐（Python 预览数据表实为前 100 行原样，binning 只进渲染数据 → 预览侧不迁 binning，记录依据） |
| B10 | robust_scale（P2-P98 ± 5% + GR/RHOB/NPHI 预设 + 倒置回退，`renderer/robust_scale.py`） | 确认缺失须补 | WLE 仅 `AutoRangeTrackScaleCommand` 全量 min/max（`track_commands.hpp:164-171`），无分位/预设 → 本线 `viz_a_robust_scale`（Qt-free）+ Python oracle |
| B11 | 十字线/信息面板 overlay（`renderer/overlay.py` bisect 插值取值） | 直接复用 | WLE `WellLogView` hover/click pick（`pick_curve/pick_fill`）+ `SetCrosshairCommand`；PR #1359 host 深度游标双向已接 |
| B12 | qpainter_builder 轨道编排（固定轨道序/合并组/CURVE_META 颜色） | 直接复用（PR #1359 等价） | `well_log_track_layout`（3 曲线合并上限、GR 保证默认、per-curve linear/log+颜色、版本化模板 JSON `pwb.well_log_track_template/1`）+ `well_log_document_plan` 分组相带；geoviz 的中文默认轨道序属模板内容，模板 JSON 已版本化可表达 |
| B13 | export_qpainter（SVG/PDF/PNG） | 直接复用 | WLE `SvgExporter`/`PaginatedSvgExporter`/`PdfSceneExporter`/`RasterExportJob`；host `export_png/svg/pdf`（PR #1359） |
| B14 | painter_sync_manager（多画布深度联动） | 直接复用 | WLE 单 document 多井共享 viewport：`SetSharedDepthViewportCommand`（`session.hpp`）；PR #1359 host zoom/pan/viewport 命令 |
| B15 | well_log_view（滚动条=深度视窗语义） | 直接复用 | WLE `WellLogView` 内建 viewport/zoom；PR #1359 已验 |
| B16 | image_preview_dialog（岩心照片放大框） | 有依据排除（无消费方） | src/主产品零消费（仅 tests）；WLE 侧无对应件；产品内图像放大由通用预览页承担 → 不迁，依据=消费方审计 |
| B17 | models/config（pydantic 数据契约/ECharts 配置） | 直接复用（等价 DTO） | PR #1359 `well_log_document_plan` Workbench DTO + `parity_snapshot_json` 字段级 parity；config.py/configs/ 服务 ECharts 旧栈 → 随 B5 排除 |

## 3. 接线（V1/V2 与 P-A/P-B）

| # | 缺口 | 判定 | 落点 |
|---|---|---|---|
| C1 | ingest LAS 分支固定 `ModuleNotFoundError`（`registry.cpp:221-241`） | 确认缺失须补 | `registry.cpp` LAS 分支（VIZ-A 块）→ provider 化；缺 SDK 时诚实 capability unavailable |
| C2 | `viz_resolve.cpp:127` "无法解析 LAS 井数据" 占位（load_fn seam 无生产实现） | 确认缺失须补 | `libs/ui_workers` 加载适配专用文件（VIZ-A）+ 主程序 JobCenter/JobOwner 注入 |
| C3 | well-log dock 同步 `load_las` 之外的异步加载路径（解析离 GUI、取消、迟到丢弃） | 确认缺失须补 | app `viz_a_install`（本线）+ `make_well_log_load_job_spec`（既有） |
| C4 | P-B：`PWB_SCIENCE_BUILD_VIEWER`/`PWB_SCIENCE_VIEWER_TESTS` 不在任何默认门禁 | 确认缺失须补 | `scripts/cpp-migration/run-viz-a-gate.sh`（本线专用，不重写资源 gate 本体）；默认门禁覆盖差异在脚本头声明 |
| C5 | E 线（P-A）需要真实注册/加载 API 与可运行 preview example | 适配缺口 | ingest registry `build_preview` + provider 安装函数 + `pwb-well-log-consumer` example 既有；api-handoff.md 交接 |

## 4. 复用/排除汇总

- 复用不动：WLE 全栈（parse/scene/renderGL/qtwidgets/export×4/session/table）、PR #1359 适配层（host/layout/plan/panel）、UI-04 worker 核心（#1375）、UI-09 页簇（#1394）。
- 本线新增：ingest LAS 预览核心+bridge、ui_workers WLE load 适配、visualization pattern_map/robust_scale、app viz_a_install、tests/cpp/viz_a、tools/oracle/generate_viz_a_*、run-viz-a-gate.sh。
- 排除（依据见上表）：A7 多 section 展示、A10 XML 区间挖掘（E 线再议）、A6 预览侧消歧、B3 location_map、B5 chart_engine、B16 image_preview_dialog、B7 FMI 渲染、lis/dlis/format716（WLE 有、geoviz parity 无此范围——`las_preview.py` 只读 LAS）。
