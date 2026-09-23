# 02–10 — Phase 台账（实施记录）

每 phase 一节，完成时回填证据（build/test 结果、删除清单、LOC 变化）。

## 02 — Phase 1：QgsLayout 成为持久化权威
- [x] LayoutAuthority：create/list/duplicate/remove + 序列化（writeLayoutXml→ProjectDocument root["layouts"]）/恢复（幂等，migration version）
- [x] slot 元数据随 layout custom properties 持久化
- [x] legacy Composition → QgsPrintLayout 迁移器（10 模板全量 + unknown element 诚实处理 + 幂等标记）
- 状态：**已完成**（详见 11-evidence.md）

## 03 — Phase 2：Stage 3 直接编辑真实 QGIS Layout
- [x] LayoutEditorPanel：QgsLayoutView + QgsLayoutRuler + select/pan/zoom 工具 + item 列表 + 公共属性 widget 宿主 + undo/redo
- [x] 自研 CompositionEditSession/CompositionPanel 从产品路径删除
- 状态：**已完成**

## 04 — Phase 3：Native Layout Items 替换自研元素
- [x] Map/Legend/ScaleBar/Label/Picture/Shape 原生化（迁移器 + 模板构造器）
- [x] PwbLayoutSlotItem（QPainter 域绘制：stat_chart 各型/colorbar/timescale/profile/fault_symbols/lithology_legend），注册 QgsApplication::layoutItemRegistry
- 状态：**已完成**

## 05 — Phase 4：模板迁移到 QGIS Layout Template
- [x] 10 个专业模板 = 原生 QgsPrintLayout 构造器（slot 标注 + metadata）
- [x] builtin（代码）/project（随工程持久化）两层；用户模板 = 工程 layouts 的自然持久化（save 即存）
- 状态：**已完成**

## 06 — Phase 5：Paleo 专业槽位（不保留第二元素模型）
- [x] `pwb/item_slots`（uuid→{slot,template_id,domain_role,binding_id,kind,properties}）
- [x] 数据更新只改对应 QgsLayoutItem（binding 应用器）
- 状态：**已完成**

## 07 — Phase 6：Export 统一 QgsLayoutExporter
- [x] LayoutExportService：持久 layout 的 PDF/SVG/PNG/preview/atlas 单路导出
- [x] composer SVG/Qt replay 从产品主路径删除（冻结 oracle 保留）
- [x] layout_service.cpp 删除；composition_layout_service 产品退役
- 状态：**已完成**

## 08 — Phase 7：Atlas/批量制图
- [x] QgsLayoutAtlas 包装：coverage layer + 过滤 + 文件名表达式 + 多文件导出
- 状态：**已完成**

## 09 — Phase 8/9：Style 一致 + Undo/Dirty
- [x] layout map 层序 = MapSession::layerIdsTopFirst（与 canvas 同源）；legend 读真实 layer tree
- [x] undo/redo = QUndoStack；dirty = stack isClean 追踪 + syncLayoutsOnSave 纳入工程保存
- 状态：**已完成**

## 10 — Phase 10：Stage 3 业务闭环
- [x] closure_mapping_install 重接线：LayoutEditorPanel + 原生模板菜单 + 新导出服务 + provenance 台账保留
- [x] 无 dict-layer 主图、无第二 visual scene、无导出时重建 layout
- 状态：**已完成**
