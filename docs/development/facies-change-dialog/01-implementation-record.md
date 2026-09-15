# 编辑期换相弹窗 — 实施记录

方案见 [`00-plan.md`](00-plan.md)。本文记录**实际落地**的改动、证据与遗留。

## 1. 用户诉求 → 落地对照

| 诉求 | 落地 | 证据 |
| --- | --- | --- |
| 「弹窗是相的列表，支持选择，然后确定」 | `FaciesChangeDialog`（搜索框 + `QListWidget` 相列表 + 亚/微相细化行 + 确定/取消；当前值预选、显示「将修改 N 个要素」） | `tests/test_facies_change_dialog_v12.py`（5 例） |
| 「编辑支持」换相 | 编辑权威双轨路由：原生会话 → 桥 `set_mirror_feature_attributes`（镜像缓冲、一宏可撤销）；否则经门禁开/取 Python 会话 | `tests/test_facies_change_native_v12.py`、`tests/test_qgis_mirror_attributes_v12.py` |
| 「更换相图的 feature 的特性 label」 | 换相后按图层**实际字段名**解析（`facies` / `facies_name`）重推分类样式与标注字段；原生路径由桥 `triggerRepaint` | 同上；`_refresh_facies_layer_style` 字段解析分支 |
| 顺手修掉的真缺陷（用户先前的「保存是灰色的」） | `dirty` 并入原生缓冲脏态（桥 `mirror_layer_dirty`）→ 保存/回滚在原生编辑期不再恒灰 | `test_native_pending_changes_feed_dirty_fact` |

## 2. 代码改动

### 2.1 桥（`native/qgis_render_bridge`）

* `map_stack_service.hpp/.cpp`
  * 新 `setMirrorFeatureAttributes(doc_id, feature_ids_json, attrs_json)`：
    按宿主 id 解析 fid → `beginEditCommand("Change attributes")` → 逐要素
    逐字段 `changeAttributeValue`（`convertCompatible`，未见字段跳过）→
    `endEditCommand` → `triggerRepaint` → 广播 `edit_gesture`
    （宿主手势台账/撤销语义与 merge/split/reshape 同规）。全字段都不匹配
    时返回可读错误；一个字段都没落上则 `destroyEditCommand`（不留半改缓冲）。
  * 新 `mirrorLayerDirty(doc_id)`：`QgsVectorLayer::isModified()`。
* `bindings.cpp`：两个 `.def` + manifest `features` 增
  `mirror_attribute_write` / `mirror_dirty_query`。
* 重建：`scripts\build-qgis-bridge.ps1 -Jobs 8` → `BRIDGE BUILD OK`
  （2026-09-15 14:18，`native/qgis_render_bridge/qgis_render_bridge.cp312-win_amd64.pyd` 更新；
  无仓库根影子 `.pyd`——脚本走 `uv pip install -e`）。

### 2.2 宿主

* `mapping/native_edit_session.py`：`supports_attribute_write` /
  `set_feature_attributes` / `pending_changes`（旧桥 → `None` = 未知，不虚构）。
* `ui/workstation/composite_editing.py`
  * `apply_facies_selection(layer_id, feature_ids, selection)`：单 id 与序列
    双签名；**字段解析** `facies_field_names()`（原生会话读**镜像 schema**，
    回落 Python schema + 要素属性键）→ `resolve_facies_field` 映射到图层
    真实字段；双权威路由（原生缓冲 / Python 会话）。
  * `tool_context_inputs()`：`dirty` 并入原生脏态；新增 `layer_is_facies` 事实。
* `mapping/tool_context.py`：`layer_is_facies` 字段 + 装配。
* `mapping/facies_taxonomy.py`：`FACIES_FIELD_ALIASES` +
  `resolve_facies_field(level, available)`——相族两种落盘名
  （template `facies` vs 角色 spec `facies_name`）的单一解析点。
* `ui/workstation/composite_document.py`
  * `_facies_features()`（原生会话读镜像缓冲——此前读未提交的 Python 旧态）、
    `_facies_level_values()`（字段名归一）、`_assign_facies_dialog_bulk()`
    （列表弹窗 + 整批写入 + 样式刷新）。
  * `assign_facies_to_selection()`：**整选区一次弹窗**（此前 N 要素 N 次）。
  * `_refresh_facies_layer_style()`：按真实字段名分类/标注，原生路径用镜像读回。
  * 画布右键相菜单：锚定级别列表 + 当前值（镜像事实）+「更改相…（列表弹窗）」。
  * 命令面新增 `change_facies` 处理（执行前过同一求值器）。
* 登记面同步：`tool_availability.TOOL_GROUPS/_RULE_TABLE/_rule_change_facies`、
  `action_registry`（write_tools / canvas_menu / 图标）、`tool_help`（名称 + 规格）、
  `map_action_controller._COMMAND_IDS`、新图标 `map/change_facies.svg`。

## 3. 关键发现（本机真桥实测）

1. **镜像 schema 与宿主 schema 字段名不同**：
   `initial-facies-draft-v2`（`geological_layer_spec`）用
   `facies_name/facies_id/source`，而 `create_layer(template="facies")` 的
   Geo_Template 用 `facies/sub_facies/micro_facies`。换相若假设其一，
   要么写不进镜像（`no matching field on layer: facies, ...`），要么标注不更新
   —— 现由 `resolve_facies_field` 按**实际权威**解析（原生 = 镜像 schema）。
2. **原生编辑期 Python 真源是旧态**：样式/当前值/读回一律走镜像
   （`readback_features`），否则换相后图面颜色与 label 会被 Python 旧值拉回。
3. **`dirty` 曾经恒 False**（只看 Python 会话）→ 原生编辑期保存/回滚恒灰，
   即用户报的「保存是灰色的」；已由 `mirror_layer_dirty` 修复。

## 4. 验证

```
tests/test_facies_change_dialog_v12.py      5 passed   （弹窗 + 选区批量 + 登记）
tests/test_facies_change_native_v12.py      6 passed   （双权威路由 + 旧桥降级 + 脏态）
tests/test_qgis_mirror_attributes_v12.py    8 passed   （真桥：写缓冲/一宏撤销/dirty/能力 flag/端到端用户故事）
回归：test_facies_taxonomy / test_render_presets_and_facies_menu_v12 /
      test_authoring_ux_v10 / test_topo_m1_native_editing / test_composite_editing /
      test_qgis_edit_chain_v12 / test_vertex_receipt_v12 / test_snapping_scope_and_hints_v12 /
      test_initial_facies_default / test_composite_qgis_canvas  —— 全绿
```

端到端用例 `test_host_change_facies_inside_native_session_end_to_end` 复刻用户
路径：相带草稿 → 开始编辑（原生）→ 选区 → 弹窗换相 → **镜像读回即新相** →
`保存编辑` 可用（dirty=True）→ 提交 → Python 真源对齐。

## 5. 顺手修正的既有测试

`tests/test_facies_taxonomy.py::test_facies_layer_auto_pattern_style_on_content_change`
在本机（桥已构建 → `start_editing()` 走原生会话，`layer.edit_session is None`）
是**基线既有失败**：原用例假设 Python 会话。改为走领域导入通道触发内容变更
（不开会话），语义不变（验「内容变更 → 分类样式刷新」），栈无关。

## 6. 遗留 / 后续

* 镜像 schema 与宿主 schema 的字段名分叉是**领域既有事实**（`facies_name`
  与 `facies` 并存），本轮的解析只覆盖换相路径；`_categorized_facies_style`
  的多数票回退仍在（读侧）。若要收敛为单一落盘名，需要一次跨
  `geological_layer_spec` / Geo_Template 的迁移（不在本轮范围）。
* 亚相/微相细化行对 `facies_name` 型图层不落盘（该 schema 无子级字段）——
  与 spec 一致（`level` 由图层类型隐含），弹窗仍可选定，写入时按可用字段裁剪。
* 属性表内联编辑在原生会话期仍不可用（同一 `ensure_layer_session` 语义）；
  本轮只开放了「换相」这条属性写入通道，其余属性编辑可照此模式扩展。
