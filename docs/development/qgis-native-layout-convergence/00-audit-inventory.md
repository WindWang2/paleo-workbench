# 00 — Phase 0 审计台账（基线 192422c60）

日期：2026-09-23 · worktree `../paleo-qgis-layout` · branch `feat/qgis-native-layout-composer-framework`

## 自研编图栈现状（待收敛）

| 模块 | 内容 | 规模 | 产品角色 |
|---|---|---|---|
| `libs/mapping_document/src/composition.cpp` (+hpp) | `Composition/ComposerElement`：mm 平面几何 + z_index + properties/extras，schema_version=2 JSON | 315 行 | 旧版式权威（数据） |
| `libs/mapping_document/src/composition_session.cpp` | `CompositionEditSession` 自研命令/undo（move/scale/configure/z-order/lock，CommandStack） | 474 行 | 旧编辑会话 |
| `libs/mapping_document/src/composer_renderer.cpp` | `ComposerRenderer` 纯字符串 SVG 生成器（26 元素类型，Route3 dict-layer 矢量渲染） | 2596 行 | 旧视觉引擎 |
| `libs/mapping_document/src/composer_export.cpp` | `export_composition_page`：SVG 直写 + PNG/PDF 经 replay seam | 141 行 | 旧导出 |
| `libs/mapping_document/src/composer_templates.cpp` | 10 个内置专业模板（代码常量：element_definitions + style/data bindings） | 616 行 | 旧模板权威 |
| `libs/ui_seqviz` composition_panel/state/replay | `CompositionPanel`（表单式编辑，无画布交互）+ `make_composition_replay_seams`（QSvgRenderer/QPdfWriter Qt replay） | ~2000 行 | Stage 3 UI |
| `apps/.../layout_compose_panel.cpp` | `LayoutComposePanel` 轻量版式面板（QPainter 自绘 preview，`doc["map_chrome"]`） | ~400 行 | Stage 3 第二 UI 面 |
| `apps/.../closure_mapping_install.cpp` | 组图 composition-root：双引擎导出（QGIS 优先→composer SVG 回落）、live-canvas seams、provenance 台账 | 2433 行 | 平台接线 |

## QGIS 路径现状（待升格为权威）

| 模块 | 内容 | 现状 |
|---|---|---|
| `libs/qgis/src/layout_service.cpp` | 简化 LayoutSpec→瞬态 QgsPrintLayout→exporter | 与 spec executor 并存的第二实现；仅非 CONV_29 回退/自检/测试用 |
| `libs/qgis/src/composition_layout_service.cpp` | composition JSON→`layout_export::build_layout_spec`→`layout_spec_exec` | CONV-29 主链，仍是"composition 权威→瞬态 layout" |
| `native/qgis_render_bridge/src/layout_spec_exec.cpp` | 唯一 spec 执行器：map(grid)/legend(filter)/scalebar/north/picture/label/shape→QgsPrintLayout→QgsLayoutExporter | **layout 瞬态、从不持久化、不可编辑**（头注释明示） |
| `QgsLayoutManager` | — | **全 repo 零使用** |
| `MapSession` | 独占 `QgsProject`；项目保存走自研 ProjectDocument（`.paleo.json`），不走 QgsProject::write | layout 持久化需 seam |

## 项目持久化 seam 事实

- `save_open_project`（shell_project_actions.cpp:88-147）已有两个 "sync-on-save" 先例：`syncLayerControlOnSave()`、`syncConstraintGeometryOnSave()` → layout 同步采用同一模式（`syncLayoutsOnSave()`）。
- `ProjectDocument::root()` 是通用 JSON 树；新增 `layouts` 节 = 平台层 seam，不动 libs/project 内核（Prompt 3 边界）。

## vendored QGIS 4.2 API 事实（从头文件确认，2026-09-23）

- `core/layout/`：QgsLayout（`undoStack()`→QgsLayoutUndoStack→`stack()`=QUndoStack；`addLayoutItem/removeLayoutItem/itemById/setCustomProperty`）、QgsPrintLayout（`name/setName/writeLayoutXml/readLayoutXml/atlas()`）、QgsLayoutManager（`addLayout/removeLayout/printLayouts/layoutByName/writeXml/readXml/duplicateLayout`）、QgsLayoutExporter（exportToPdf/Svg/Image + 静态多文件变体）、原生 items：Map(grids)/Legend/ScaleBar/Label/Picture/Shape/Polygon/Polyline/Marker/AttributeTable/ManualTable/TextTable/**Chart**(QGIS 4.0+, layer/expression 驱动)/ElevationProfile/HTML/Group、**QgsLayoutItemRegistry::addLayoutItemType**（自定义 item 注册）。
- `gui/layout/`：**QgsLayoutView + 全套 view tools（select/pan/zoom/additem/editnodes/movecontent/temporary*）+ QgsLayoutRuler + item 属性 widget（map/legend/scalebar/shape/picture/label/chart/atlas/guide/page/attributeselection）全部公共 gui**（QGIS 3.x 时代在 app，4.x 已下沉）；`QgsGui::layoutItemGuiRegistry()->createItemWidget(item)` 返回 QgsLayoutItemBaseWidget（QgsPanelWidget）。
- **QGIS 4.2 无 item 级 custom property**（仅 QgsLayout::setCustomProperty）→ slot 元数据按 item uuid 存 layout 级 custom property `pwb/item_slots`（JSON），随 writeLayoutXml 序列化。
- 自定义 item 持久化虚函数：`writePropertiesTo/readPropertiesFrom`（qgslayoutitem.h 标准 hook）。
- atlas：QgsLayoutAtlas（setCoverageLayer/setEnabled/updateFeatures/beginRender/seekTo…）挂在 QgsPrintLayout::atlas()。

## 结论

QGIS 4.2 公共 API 面足以承载目标架构的全部 phase（含 GUI 编辑），无需移植 app-private 代码。旧栈可整体退休；`mapping_document` 的 composer 部分降级为冻结 oracle（测试专用）+ 迁移输入。
