# 01 — 目标架构与概念映射

```text
QgsProject（MapSession 独占）
  └─ QgsLayoutManager                        ← LayoutAuthority 封装
      └─ QgsPrintLayout = 唯一版式权威
          ├─ QgsLayoutItemMap (+grid)        ← main_map / inset_map
          ├─ QgsLayoutItemLegend             ← legend / facies_legend / well_legend
          ├─ QgsLayoutItemScaleBar           ← scale_bar
          ├─ QgsLayoutItemLabel              ← title / subtitle / text / metadata / datasource / time_credits / strat_labels
          ├─ QgsLayoutItemPicture            ← north_arrow / image / logo
          ├─ QgsLayoutItemShape              ← neatline / 装饰框
          ├─ QgsLayoutItemAttributeTable     ← 表格类
          ├─ PwbLayoutSlotItem（自定义注册）  ← stat_chart / colorbar / timescale / profile / fault_symbols / lithology_legend
          └─ QgsLayoutAtlas                   ← 批量制图
持久化：layout XML（writeLayoutXml）→ ProjectDocument.root()["layouts"]（syncLayoutsOnSave seam）
Paleo 保留：slot 语义、地质模板元数据、数据绑定、provenance —— 全部是 QgsLayout 之上的薄层
```

## 概念映射表（自研 → QGIS public API）

| 自研概念 | QGIS 承载 | 备注 |
|---|---|---|
| page / paper / orientation | `QgsLayoutItemPage::setPageSize`（pageCollection） | A5–A0 同表 |
| item id | `QgsLayoutItem::setId/uuid` | id 可重名，uuid 唯一 → slot 寻址用 uuid |
| position/size(mm) | `attemptMove(QgsLayoutPoint mm)/attemptResize(QgsLayoutSize)` | |
| rotation | `QgsLayoutItem::setItemRotation` | |
| z-order | QGraphicsItem zValue（`layout->addLayoutItem` 保序 + view 提升/置底命令） | undo 走 QUndoStack |
| visible/locked | `setVisibility/setLocked` | |
| main map frame | `QgsLayoutItemMap` + `setFrameEnabled`/background | |
| grid/graticule | `QgsLayoutItemMapGrid`（annotation/zebra/DMS） | 旧 geographic 强制 QGIS 的行为保留 |
| legend | `QgsLayoutItemLegend`（linked map + sync mode + filter） | 不再构造第二份 flattened legend |
| scale bar | `QgsLayoutItemScaleBar` | |
| north arrow | `QgsLayoutItemPicture`（NorthArrow SVG，layout_export 现有物化逻辑复用） | |
| label/title | `QgsLayoutItemLabel` | html 子集对齐现有 title 行为 |
| picture/image | `QgsLayoutItemPicture` | |
| shapes/arrow | `QgsLayoutItemShape` / `QgsLayoutItemPolyline+marker` | |
| tables | `QgsLayoutItemAttributeTable`/ManualTable | |
| charts（专业） | `PwbLayoutSlotItem`（QPainter 绘制 series：pie/donut/histogram/rose/line/scatter/hbar） | QGIS 原生 Chart item 是 layer/expression 驱动，不适配域统计序列 |
| colorbar/timescale/profile/fault_symbols/lithology_legend | `PwbLayoutSlotItem`（kind 化绘制） | |
| templates | QgsPrintLayout 代码构造 + writeLayoutXml(QPT) + Paleo metadata | builtin（代码）/ project（工程内）/ user（用户保存）三层 |
| preview | QgsLayoutExporter→QImage（96dpi） | 与导出同源 |
| export pdf/svg/png | QgsLayoutExporter | 统一唯一 |
| atlas | QgsLayoutAtlas | Paleo 提供 coverage/命名/过滤 |
| undo/redo | QgsLayoutUndoStack→QUndoStack | |
| selection/interaction | QgsLayoutView + QgsLayoutViewToolSelect | 公共 gui |
| item 属性面板 | `QgsGui::layoutItemGuiRegistry()->createItemWidget` | 公共 gui（QGIS 4.x 下沉） |
| slot 语义 | layout custom property `pwb/item_slots`（uuid→slot JSON） | 4.2 无 item 级 custom property |

## 模块落点

新增（libs/qgis，target pwb_qgis）：
- `layout_slots.hpp` — slot 词汇 + attach/query helpers
- `layout_authority.hpp/.cpp` — LayoutAuthority（manager 封装、序列化/恢复、dirty）
- `layout_migration.hpp/.cpp` — legacy Composition → QgsPrintLayout（一次性、幂等）
- `layout_templates.hpp/.cpp` — 10 个原生地质模板构造器 + 元数据
- `layout_slot_item.hpp/.cpp` — PwbLayoutSlotItem 自定义 item（注册进 QgsApplication::layoutItemRegistry）
- `layout_export_service.hpp/.cpp` — 持久 layout 的导出/预览/atlas（QgsLayoutExporter）
- `layout_editor_widget.hpp/.cpp` — QgsLayoutView 宿主（rulers+items+属性面板+undo 工具栏）

退休：`layout_service.cpp`（删）、`composition_layout_service.cpp`（产品路径退役）、closure install 双引擎回落（删 composer 主路径）、ui_seqviz CompositionPanel/composition_replay（删）、layout_compose_panel 自绘 preview（改真实 layout 渲染）。
保留冻结：mapping_document composer oracle 测试、layout_export oracle 测试、native bridge pybind legacy。
