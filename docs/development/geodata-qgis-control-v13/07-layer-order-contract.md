# 07 — Layer Order Contract（W-K，V13）

## 1. 单一来源（既有，V13 补测试钉死）

`QgisMapStack::mirrorTreeOrderTopFirst()` = QgsLayerTree 全树 DFS，
是 canvas==tree==legend==layout 顺序的唯一来源
（`native/qgis_render_bridge/src/map_stack_service.cpp:2975`）；
`layoutMapLayerOrder()` 是其 bottom-first 反转（QgsLayoutItemMap::setLayers）。

## 2. V13 契约测试矩阵（tests/test_order_contract_v13.py + domain contracts）

| 契约 | 测试 | 腿 |
|---|---|---|
| 领域期望树 DFS == mirror_tree_order_top_first（组模式） | TestNativeGroupedOrderParity.test_domain_tree_order_equals_native_tree_walk | qgis |
| layout 应用序 == 树顶序反转（同一来源另一半） | 同上 | qgis |
| 信封 write→apply 往返组结构+组间序保真 | test_envelope_roundtrip_preserves_grouped_order | qgis |
| flatten_for_render 是 fallback 规范投影（top-first DFS；反转=画笔堆叠序；不丢未入树层） | TestDegradedProjectionContract | 纯 |
| order_key 经 state.tree 持久 roundtrip 保真（observe→plan→persist→reload→plan 同序） | TestOrderKeyRoundtrip | 纯 |
| legend filter_layers 保持镜像层序（自下而上） | TestLegendFilterOrderContract | 纯 |

V11/V12 既有 parity（flat 推送反转、面板==树==反转装配、fallback 标注
后置、组模式不动镜像序）全部保留，未改动。

## 3. 排序合并语义（既有 + 确认）

系统默认带（ROLE_BANDS + 模板序锚定）+ 用户 reorder（观察序→
assign_keys_for_order 的 LIS 保键最小扰动）+ stage 切换（只动组
物化/显隐，**不动顺序**）+ 保存/重开（tree dict + envelope 双载体，
域树重建覆盖 envelope 平铺序）——V13 测试验证闭环后无新增合并规则。

## 4. 遗留缺口（诚实）

- 原生侧标注顺序无独立断言（fallback 已有 test_label_order_v12；
  native PAL 顺序由 QGIS 引擎内定，无跨引擎一致性可断言）；
- CompositeDocument.set_project 全链（envelope 应用+域树重建覆盖后
  canvas 终序）未做端到端断言——桥级信封往返 + 域级 roundtrip 分别
  钉死，中间 glue 由 test_qgis_layer_groups/#1154 防回归覆盖。
