# 02 — Current Editing Flow（V10 基线）

一条编辑从指针事件到持久化的完整链路，及各分支。

## A. Native 主路径（bridge 可用时，生产路径）

```
用户指针/键盘事件
  → QgsMapCanvas → QgsMapTool（PwbVertexTool / PwbMoveTool / PwbSelectTool /
      PwbMeasureTool / QgsMapToolDigitizeFeature / QgsMapToolIdentifyFeature）
  → 工具内交互（pick / snap / rubber band 预览；零数据变更）
  → 完成手势 → callback(action, payload_json)   [alive_token 守卫 + GIL acquire]
  → canvas_shim.py 回调适配（commit_geometry / commit_vertex_move /
      commit_move / commit_selection / native_identified / measure_*）
  → map_tools.py 工具控制器 commit_*
      · 会话门禁（feature 在 session？层可编辑？）
      · edit_source("tool(native)") 溯源标记
      · begin/end_edit_command 宏（一个手势 = 一个 undo 单元）
  → VectorEditSession 命令（EditCommand before/after 快照）
      · _working 变更 + undo_stack + revision bump + EditDelta
  → content_changed 信号 → composite_document 120ms 防抖
  → snapshot_layers()（changes_since 增量：只取 touched ids）
  → qgis_mirror.mirror_snapshot_to_stack（ledger 判 delta/全量）
  → C++ upsert_mirror_layer（provider delete+re-add 变更要素）
  → refresh_canvas
```

不变量：**QGIS 侧零持久化数据变更**；镜像层只读；scratch 捕获层
`startEditing` 但不落盘；完成几何经回调进 session 才算数。

## B. Python fallback 路径（无 bridge / headless 测试）

`map_tools.py` 状态机 + `map_interaction.py`（`FeatureSpatialIndex` cell 索引 +
`SnappingService`）→ 同一 `VectorEditSession` commit 入口。规则（V7 §5）：
**fallback 不获得 native 路径没有的专业能力**（ReshapeTool 无鼠标方法即此规则
的体现）。V10 新增的 native 能力（vertex insert/delete、snap feedback）不回填
fallback（记录于 11-known-limitations）。

## C. 几何命令路径（split / merge / repair / V10 新增 ring/part/convert）

```
geometry_command / edit_command（composite_editing.py 单入口，执行前 re-gate）
  → vector_operations.py 调度（bridge 可用？）
      · QGIS: geometry_service.py → bridge geometry.*
      · fallback: geometry_operations.py（shapely，engine 披露）
  → 纯 GeoJSON 结果 → session.split_feature / merge_features / set_geometry ...
  → 同 A 的镜像刷新链
```

## D. 拓扑传播路径

```
vertex move 宏关闭后（map_tools._commit_vertex，V8 M3 review-2 P0 次序）
  → TopologyService.propagate_shared_vertex
      · 容差匹配跨层共享顶点（O(全部顶点) 扫描，仅提交时一次）
      · 为被传播层惰性开 session，逐点 set_vertex
  → CompoundUndoGroup 注册（原点命令对象身份 + 传播命令）
  → undo/redo 端点（composite_editing.edit_command /
      mapping_page._on_action_command_requested）先查 pending_compound
  → undo_compound：全组原子回滚（冲突扫描 + revision guard 线性 redo）
```

QGIS `topologicalEditing` 只影响**捕获期** digitizer 行为（共享边界跟随），
共享顶点传播权威仍是 `TopologyService`——两层同向，无双真源（V9）。

## E. 提交/回滚/持久化

```
save_edits: topology gate → session.commit_changes()
  → VectorLayer._commit（data_revision+1）
  → constraints_sync（线约束合并/面环收割 + content_fingerprint）
  → sync_to_project（committed features → UserVectorLayer 记录）
  → MapAuthoringDocument.edit_history += audit_history()
rollback_edits: session.rollback_changes()（journal/delta 整段作废）
flush_edit_sessions: 项目保存前强制落盘或显式拒绝（#1126）
```

## F. V10 对链路的改动面

1. `set_vertex`/`insert_vertex`/`delete_vertex` 增加**闭环 ring 不变量维护**
   （session 层，native+fallback 同时受益）。
2. 新回调 `vertex_inserted`/`vertex_deleted`/`snap_feedback`（同 A 链路接入，
   同样的 alive_token/门禁/宏/溯源纪律）。
3. ring/part/convert/duplicate 走 C 几何命令路径（新 session 命令类型
   `add_part`/`delete_part`/`move_part`/`duplicate_feature`，delta 映射
   replace_geometry / create_feature）。
