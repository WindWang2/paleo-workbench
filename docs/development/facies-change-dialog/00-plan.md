# 编辑期换相弹窗（facies change dialog）— 开发方案

> 目标（用户原话）：**编辑支持弹窗更换相**——弹窗是相的列表，支持选择，然后
> 确定，这样就可以更换相图 feature 的特性/label。
> 本文是方案；`01-implementation-record.md` 是实施记录（TDD 证据）。

## 1. 现状（已读代码）

| 能力 | 位置 | 现状 |
| --- | --- | --- |
| 三字段写要素 | `composite_editing.apply_facies_selection(layer_id, feature_id, selection)` | 只支持**单个**要素；经 `ensure_layer_session` 拿会话 |
| 会话获取 | `composite_editing.ensure_layer_session` | **原生会话打开时直接拒绝**：「该图层处于原生编辑会话——请先保存或回滚编辑」 |
| 右键换相 | `composite_document._build_facies_context_menu` / `_open_facies_context_menu` | 扁平 QMenu（相名 + 勾选当前值）+ 「级联选择…」兜底 |
| 级联对话框 | `facies_selector.FaciesSelectionDialog`（`FaciesCascadeSelector` 三级下拉） | 绘制完成/检查器/属性表共用；**不是列表形态** |
| 选区批量 | `composite_document.assign_facies_to_selection` | 逐个要素弹一次对话框（N 个要素 = N 次弹窗） |
| 分类样式刷新 | `composite_document._refresh_facies_layer_style` | 读 `layer.edit_session` 或 Python 真源——**原生会话期间读到的是未提交的旧真源** |
| 编辑脏态 | `composite_editing.tool_context_inputs`：`dirty = session is not None and session.is_dirty` | **原生会话没有 Python 会话 → dirty 恒为 False** → 保存/回滚按钮恒灰 |
| 桥 | `map_stack_service` 有 `add/split/merge/fault_cut/reshape/restore_mirror_snapshot` | **没有属性写 op**：原生缓冲里改不了属性 |

## 2. 缺口（本次要补的四件事）

1. **G1 编辑期写不了相**：原生编辑会话（当前主路径）下 `ensure_layer_session`
   直接拒绝 → 换相在编辑中不可用。用户要的正是「编辑支持」。
2. **G2 没有列表弹窗**：现入口是 QMenu 扁平列表 + 三级下拉；用户要**
   列表 + 选择 + 确定**的对话框形态，并且要能一次改**整个选区**。
3. **G3 保存/回滚恒灰**：原生会话的未提交修改不进 `dirty`，
   `_rule_save_edits` / `_rule_rollback` 要求 `ctx.dirty` → 恒不可用
   （用户报的「保存是灰色的」）。
4. **G4 样式/标注不跟随**：原生会话期间分类样式由 Python 真源推导，
   换相后图面颜色/label 不会更新。

## 3. 方案

### 3.1 桥（`native/qgis_render_bridge`）

新增两个 mirror 面（都在已有 `EditingLayerFor(doc_id)` 域内，走
`beginEditCommand/endEditCommand` 一宏，可撤销、随 commit 落盘）：

* `set_mirror_feature_attributes(doc_id, feature_ids_json, attrs_json) -> error`
  按宿主 id 列表定位 fid，逐字段 `changeAttributeValue`（`convertCompatible`
  与 merge 同规），一宏可撤销；成功后 `triggerRepaint()`，并广播
  `edit_gesture`（宿主手势台账，undo/redo 语义与其它镜像编辑一致）。
* `mirror_layer_dirty(doc_id) -> bool`（`QgsVectorLayer::isModified()`）
  原生缓冲是否有未提交修改——`dirty` 的第二权威。

能力 manifest 增 `mirror_attribute_write`；宿主用
`callable(getattr(stack, ...))` 探测（与 `bridge_supports` 同规），旧桥
**诚实降级**：换相弹窗给出「当前桥不支持编辑期属性写入（请重建
qgis_render_bridge）」而不是静默失败。

### 3.2 宿主控制器

* `NativeEditSessionController.set_feature_attributes(layer_id, feature_ids, values)`
  → 桥 op；`pending_changes(layer_id)` → 桥 dirty（无 op 时 None = 未知）。
* `CompositeEditController.apply_facies_selection(layer_id, feature_ids, selection)`：
  参数放宽为**序列**（单串等价单元素，向后兼容）；路由：
  1. 原生会话打开 → `native_editing.set_feature_attributes(...)`；
  2. 否则 → `ensure_layer_session` + `session.change_attribute`（现状语义）。
  返回 `(ok, reason)`，写成功后 `content_changed.emit(layer_id)`。
* `tool_context_inputs.dirty` 并入原生脏态：
  `dirty = 会话脏 or native_editing.pending_changes(layer.id)`。

### 3.3 UI

* 新 `facies_selector.FaciesChangeDialog`（列表形态）：
  - `QLineEdit` 搜索 + `QListWidget` 相列表（`taxonomy.names(anchor_level)`）；
  - 当前值预选、`Current` 标记；亚相/微相沿用 `FaciesCascadeSelector`
    作为可选细化（折叠区，默认收起——用户要求的就是「相的列表」）；
  - 摘要行「将修改 N 个要素」；确定/取消（Esc = 取消）。
  - `selection()` 返回 `{facies, sub_facies, micro_facies, level}`（与
    `apply_facies_selection` 同契约）。
* 入口（同一实现，零分叉）：
  1. 画布右键要素 → 「更改相…」→ 弹窗；
  2. 属性表/检查器「指定相带…」→ 弹窗（**整个选区一次**，不再 N 次）；
  3. 工具栏/调色板新工具 `change_facies`（相带图层 + 有选中要素才可用）。

### 3.4 刷新

换相后：Python 路径照旧 `_refresh_facies_layer_style`；原生路径由桥
`triggerRepaint` 即时重绘，宿主按**镜像读回**（`readback_features`）推导
分类样式重推（新增分支，避免用未提交的 Python 真源）。

## 4. 测试计划（先写测试）

1. `tests/test_facies_change_dialog_v12.py`
   - 对话框：列表来自词表、当前值预选、搜索过滤、取消不产生选择、
     `selection()` 与控制器契约一致、单选/多选摘要文案。
   - 宿主批量：`assign_facies_to_selection` 只弹**一次**对话框并把选择
     写到全部选中要素（monkeypatch `exec`）。
   - 工具登记：`change_facies` 在 registry/evaluator/help 三处同源，
     门禁（相带图层 + 选区）判词正确。
2. `tests/test_facies_change_native_v12.py`
   - 原生会话路由：`apply_facies_selection` 调桥 op（假 stack 记录调用参数）；
   - 旧桥降级：无 op → `(False, 原因)` 且原因自曝「重建 qgis_render_bridge」；
   - `dirty`：原生 `pending_changes=True` → `save_edits`/`rollback` 可用
     （回归用户报的「保存是灰色」）；
   - 样式刷新走镜像读回分支。
3. 桥侧（真机）：复用既有 `-m qgis` 用例模式，验证
   `set_mirror_feature_attributes` 改属性 → `mirror_features_json` 读回新值、
   undo 可撤销、`mirror_layer_dirty` 从 False→True→(commit 后)会话关闭。

## 5. 验收

* 编辑中（原生/Python 两种会话）对选中要素弹窗换相，**确定即生效**：
  属性、图面分类色、label 同步更新，且可 Ctrl+Z 撤销、保存后落盘；
* 保存/回滚在原生会话有未提交修改时**不再恒灰**；
* 旧桥/回退画布下不静默失败，给出可执行的原因；
* 目标测试全绿，且不与既有 V10/V12 契约测试冲突。
