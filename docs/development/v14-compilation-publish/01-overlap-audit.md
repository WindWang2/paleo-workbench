# 01 — Overlap Audit（V14-COMPILATION-PUBLISH vs 当前 main 与并行线）

复核日期：2026-09-21（base `412d8baf`）。

## 与 open PR 的重叠矩阵

| 并行租约 | 重叠点 | 判定 |
|---|---|---|
| #1434 (`fix/open-issues-batch`) | `workflow_graph`/`curve_expr`/`polygonization`/`ui_data_core`/`mirror_snapshot`/`map_chrome_painter` overlay 缓存/CI | **零触碰**。本线若改 `map_chrome_painter.cpp` 仅 additive 具名块（实际计划不改）。 |
| #1435 (final-closure) | 根 CMake/cmake 模块/app_context | 仅 additive 具名 `BEGIN/END V14-COMPILATION-PUBLISH` 块。 |
| #1436 (residual-conversion) | **`libs/closure_workflow/map_compile.*`（编图管线 draft+production 移植）**、`python_json`、`ui_canvas/qt/fallback_map_backend`、`interchange/exporters`、`job_runtime` 治理 | **map_compile 禁止重复实现**——本线聚焦：输入集 freeze 动作、fusion grid seams 生产实现、map_product 阶梯接线、版式/模板/预览/导出/QA/发布。若 #1436 先合并：直接 `compile_map_draft/production` 消费；本 PR 不依赖其合并（map_compile 编图动作本线以 optional seam 声明，main 上无该函数时不接线编图 draft 菜单——诚实降级）。`python_dumps` 同理不复制：本线用既有 `python_dumps_sorted`/`dump_json_python_compatible`。 |
| #1437 (V14-QGIS-CONTROL / Prompt3) | `libs/workspace/**`、`mapping_document` 树/持久化文件、`ui_widgets/src/qgis/**`、`native/qgis_render_bridge/**` | 本线在 `mapping_document` **只新增文件**（composer_templates/renderer/export），不改其已有 .hpp/.cpp（#1437 的 map_document/workspace 改动零冲突）。层序只消费 main 已有 `MapSession::layerIdsTopFirst()`。`layout_spec_exec` 不改（其已消费 order hook）。 |
| V14-CONSTRAINT-FACTOR (Prompt4) | `mapping_kernel`/`factor_host`/`closure_science` factor 路径 | 零触碰。factor 参考卡片（§13）只消费 project/catalog 中的 factor products 数据，不复制 compute。 |
| V14 主线 Prompt2（Stage3 UI shell） | 面板布局 | 本线提供 content/provider/widgets（descriptor 模型 + 数据服务），不做 shell 布局。 |

## main 既有权威（禁止重建清单 → 复用方式）

| 权威 | 本线复用方式 |
|---|---|
| `MapCompositionDocument`（mapping_document/composition） | 模板/渲染器/导出全部以 `pwb::mapping_document::Composition` 为输入，无第二文档模型 |
| `CompositionEditSession`（#1412） | 模板物化经 `CompositionFactory`；预览刷新经 session 修订号 |
| `MapSession::layerIdsTopFirst()`（Prompt3 canonical order） | 预览图例提取与导出 legend 的唯一顺序源（经 host seam 注入） |
| `layout_export` spec 构建 + `layout_spec_exec` 执行器 | 导出编排优先 QGIS 原生路径；composer SVG 引擎是**新增的诚实回退**（修订 D-03，见 02） |
| `catalog` 深核（apps/closure_catalog_service） | 经新增 `workflow_runtime::CatalogRepository` 适配器桥接，不建第二目录 |
| `closure_review` review 流水 | provenance sink 生产实现挂接其既有 seam（`QcProvenanceSink`/`VersionFinalizeSink`），双轨 QC 不合流（超范围，登记） |
| `MapProduct` 生命周期（closure_workflow/map_product.cpp） | 仅接线，不改阶梯语义 |
| `document_io` 原子写 | composer SVG 导出复用同一原子写模式 |

## 本线新增文件（不与任何租约冲突）

- `libs/mapping_document/include/pwb/mapping_document/composer_templates.{hpp}` + `src/composer_templates.cpp`
- `libs/mapping_document/.../composer_renderer.hpp` + `src/composer_renderer.cpp`
- `libs/mapping_document/.../composer_export.hpp` + `src/composer_export.cpp`
- `libs/closure_workflow/.../grid_seams.{hpp,cpp}`（decode + live 解析）
- `libs/closure_review/src/cartographic_rules.{hpp,cpp}`（15 规则移植）
- `apps/paleo_workbench_platform/closure_compilation_service.{hpp,cpp}`（新 install 模块）
- 对应 tests + `tools/oracle/generate_composer_*_fixtures.py` + fixtures

## 共享文件改动策略

- 根 `CMakeLists.txt`：仅具名块（新增测试电池/源回填），与 #1435/#1437 同款 additive 模式。
- `apps/paleo_workbench_platform/closure_mapping_install.cpp`：`BEGIN/END V14-COMPILATION-PUBLISH` 具名块（seam 注入处）。
- `libs/ui_pages_mapedit/src/map_factor_shelf.cpp`：仅连接既有悬空信号（additive）。
- 各 CMakeLists：additive 行。
