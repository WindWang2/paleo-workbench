# 11 — Layout / Legend Order (V11)

## 1. 单一顺序来源

`mirrorTreeOrderTopFirst()`（全树 DFS，`QgsLayerTree::layerOrder` 语义，
含组内图层）——画布（tree bridge 同源）、图例（手动克隆树剪枝）、布局
导出（map 图层集 = 该走查反转）共用。`mirror_order_top_first`（root-only）
保留给 legacy 平铺 order 事件。

## 2. P0 修复

布局导出曾只走查 root children——组内图层从导出地图中静默消失。现用
全树走查（含组），顺序与画布按构造一致（平价测试：含组布局导出 + 树序
断言）。

## 3. 顺序约定统一

快照组装序自下而上（fallback 画笔后绘在上）；桥平铺推送约定 top-first。
`qgis_mirror` 显式反转后推送——原生平铺画布与 fallback 对同一快照堆叠
一致（平价测试钉死最上层）。组模式下顺序 = 树走查（plan order keys）。
legend `filter_layers` 显式覆盖保留（opt-in）。
