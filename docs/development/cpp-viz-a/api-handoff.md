# VIZ-A API 交接说明（B/E 线）

本线（A：LAS/WLE 收敛与测井绘制差量）向并行线提供的公开契约。所有 API 均在
`origin/main` 的既有 WLE SDK（f845e7ab）之上构建——**B 线不需要依赖本分支的未合并
实现**：B 消费的 WLE 基座（多井面/覆盖/深度变换）全部在主线 SDK 中已存在。

## E 线（P-A 数据/预览页挂载）

E 负责把 `ui_pages_preview`/`ui_pages_data` 挂进主程序。A 提供的真实注册/加载 API：

1. **LAS 预览（注册表内建，无需 E 做任何事）**
   `pwb::ingest::preview::build_preview(ResourceRef, PreviewSettings, project_root?, sibling?)`
   （`libs/ingest/include/pwb/ingest/preview/registry.hpp`）——`.las` 与
   `type=="well_log"` 的 fallback 分支已产出 `mode="well_log"` 的真预览
   （summary_rows=井名/曲线数/采样点、曲线表、前 100 行数据表、截断警告），
   与 `LazySummaryResult` 字段一一对应（`LazyVisualizationTabs::load_summary`）。
2. **能力安装（进程级，一次性）**
   `pwb::ingest::preview::install_wle_las_preview_provider()`
   （`pwb/ingest/preview/las_wle_bridge.hpp`，target `Pwb::IngestLasWle`，仅在
   viewer 构建中存在）。不安装时 registry 返回诚实 "LAS 预览不可用：WLE LAS
   解析内核未接入" message——E 的页面应把 message mode 当不可用态呈现，不要当错误。
   主程序已由 A 的 `pwb::app::viz_a::install`（`apps/paleo_workbench_platform/viz_a_install.*`，
   `PWB_WITH_VIZ_A`）安装；E 的页面装配无需重复调用。
3. **可运行 example**：`pwb-well-log-consumer`（viewer 配置默认构建，
   `libs/visualization/src/well_log/examples/well_log_consume.cpp`）+ 新增
   `viz_a.las_preview_wle` 测试展示注册表端到端消费方式。

## B 线（cross-well / well tie）

1. **剖面基座（主线 WLE，直接用）**：
   `welllog::WellLogSession`（`welllog/session/session.hpp`）——
   `SetWellLayoutCommand`/`WellPlacement`（井位布局）、`compose_multi_well_scene`
   （`welllog/scene/scene.hpp:949`）、`SetSharedDepthViewportCommand`（多井深度联动）、
   `DepthTransform`+`SetDepthTransformCommand`（datum 变换）、
   `AlignWellsToMarkersCommand`（按层位拉平，对应 geoviz datum_shift）、
   `CrossWellOverlay`（`session.hpp:121-141`）+`SetCrossWellOverlaysCommand`（井间相关线/带，对应
   connection_overlay 的 horizon 线/相带四边形基座）、
   `SetSurfaceHorizontalViewCommand`/`prepared_surface_scene()`（水平虚拟化）。
   参考测试：SDK 内 `unified_surface_test/multi_well_surface_test/depth_transform_overlay_test`。
2. **井曲线数据**：B 的加载走主线 WLE `LasSourceAdapter::parse`（`welllog/io/las.hpp`）
   或本线 worker seam（见下）；两路字节一致。
3. **岩性图案/颜色**（本分支新增，B 可选依赖）：`pwb::viz::pattern_id_for/
   facies_color_for/make_pattern_definition`（`pwb/viz/well_log_patterns.hpp`）——
   中文名→图案 id/底色的冻结表与模糊匹配 + WLE `PatternDefinition` 构造。
   若 B 在 A 合并前开发，可先冻结同一 Python 源（pattern_map.py）自行转录，
   合并时以 A 的实现为准收敛。
4. **worker seam（本分支新增）**：`pwb::ui_workers::make_wle_load_fn()`
   （`pwb/ui_workers/wle_load.hpp`，target `Pwb::UiWorkersWleLoad`）——返回
   UI-04 `WellLogLoadFn`，payload 为 `WleDocumentPayload`（`shared_ptr<const WellLogDocument>` + 诊断计数，`pwb/ui_workers/wle_load.hpp`）。
   B 的 correlation/dtw worker 需要井数据时按同模式注入。

## 依赖声明

- 本分支不修改 WLE SDK；发现 SDK 问题时走独立 worktree/PR + gitlink 依赖记录。
- 本分支不改 E 的总页面装配、不加 B 范围的 cross-well 实现。
- lis/dlis/format716（WLE 有 io 面）不在 geoviz parity 范围，未桥接、未迁移。
