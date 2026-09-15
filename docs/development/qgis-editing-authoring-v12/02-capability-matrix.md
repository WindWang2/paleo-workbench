# 02 — 能力矩阵：数字化工具条 · 捕捉工具条 · 顶点/拓扑编辑

分类词表沿用 V10（`docs/development/qgis-native-vector-authoring-v10/05-edit-tool-matrix.md`）：`AVAILABLE_QGIS` / `EXISTING_PWB_NATIVE` / `EXISTING_PWB_FALLBACK` / `PARTIAL` / `MISSING` / `DEFERRED` / `NOT_REQUIRED` / `V12-NEW`。

现状列 = **代码事实**（坐标可点开）；目标阶段列对应 05 的里程碑。

---

## 1. 数字化工具条（Digitizing toolbar）全量对齐

当前工具面只有 `TOOL_GROUPS["capture"] = (add_point, add_line, add_polygon)`（`paleo_workbench/mapping/tool_availability.py:148`）加 `geometry` 组（`:149-155`）。下表逐项对齐 QGIS 3.x 数字化工具条。

| QGIS 工具 | 现状 | 代码坐标 | 目标阶段 |
|---|---|---|---|
| 切换编辑 Toggle editing | EXISTING | `tool_availability.py:147`；`composite_document.py:2366-2377` | — |
| 保存编辑 Save edits | EXISTING | `tool_availability.py:147`；`composite_editing.py:1551-1586` | — |
| 取消/回滚 Cancel edits | EXISTING | `tool_availability.py:147`；`composite_editing.py:1824` | — |
| 撤销/重做 Undo/Redo | EXISTING | `edit_gesture_manager.py`；`native_edit_session.py:377-416` | — |
| 添加点/线/面 Add Feature | EXISTING_PWB_NATIVE | 桥 kind `addPoint/addLine/addPolygon`（`map_stack_service.cpp:4929`） | — |
| 添加部件 Add Part | EXISTING（native-only） | `tool_availability.py:153`；捕获环 → bridge `geometry.add_part` | — |
| 添加内环 Add Ring | EXISTING（native-only） | `tool_availability.py:153`；`canvas_shim.py` RingCaptureTool 路由 | — |
| 填充环 Fill Ring | **MISSING** | 全仓无 `fill_ring` | M5 |
| 删除环 / 删除部件 / 移动部件 | **PARTIAL**（API 面已实现，画布拾取 DEFERRED） | `_ring_and_part_commands(...)`（`composite_editing.py`）；V10 `05-edit-tool-matrix.md:42,44-45` | M5 |
| 添加圆弧/矩形/正多边形 | **MISSING** | 全仓无 `circular` / `add_rectangle`（`rectangle` 命中仅 `select_rectangle`） | M5 |
| 移动要素 Move Feature | EXISTING_PWB_NATIVE（无捕捉跟随，原始 dx/dy） | 桥 kind `move`（`map_stack_service.cpp:4962`）；`edit_tools.hpp` PwbMoveTool | M2 |
| 删除选中 Delete Selected | EXISTING | `tool_availability.py:152` | — |
| 旋转要素 Rotate Feature | **MISSING**（V8 D4 判 DEFERRED；本轮用户要求全功能 → 重开题） | — | M5（需决策 D4） |
| 缩放要素 Scale Feature | **MISSING**（同上） | — | M5（需决策 D4） |
| 简化要素 Simplify Feature | **MISSING** | 全仓无 `simplify`（`repair_geometry` 是有效化修复，不是简化） | M5 |
| 平滑 Smooth | **PARTIAL**（算法在 `geotopo_service.smooth_curve`，零生产调用方） | `mapping/geotopo_service.py` | M5 |
| 重塑要素 Reshape Features | EXISTING（native-only，单选门禁） | `composite_editing.py:2164-2180` | — |
| 分割要素 Split Features | EXISTING（QGIS 引擎 + 拓扑点） | `map_stack_service.cpp:3677-3701` | — |
| 分割部件 Split Parts | **MISSING** | 全仓无 `split_parts` | M5 |
| 合并选中要素 Merge Selected | EXISTING | `tool_availability.py:154`；`geometry_command("merge")` | — |
| 合并属性 Merge Attributes | **PARTIAL**（仅合并流程内的对话框） | `ui/workstation/merge_features_dialog.py:19,32` | M4 |
| 偏移曲线 Offset Curve | **MISSING** | — | M5 |
| 反转线方向 Reverse Line | **MISSING** | — | M5 |
| 修剪/延伸 Trim/Extend | **MISSING** | — | M5 |
| 旋转点符号 Rotate Point Symbols | **NOT_REQUIRED**（本系统点符号不做逐要素旋转；如需走数据定义旋转，已在 `style_codec` 支持） | `style_codec.cpp:325-396` | — |
| 剪切/复制/粘贴要素 | **DEFERRED**（V10 11-#6） | — | M5（需决策 D5） |
| 平移到选择 Pan to selection | **PARTIAL**（`layer_zoom` 是"缩放到图层"） | `tool_availability.py:158` | M4 |
| 顶点工具 Vertex Tool（当前层/全部层） | EXISTING_PWB_NATIVE（**当前不可用，见 01 D-A/D-B**） | 桥 kind `vertex`；`edit_tools.hpp:145-268` | **M0** |
| 捕捉几何到图层 Snap Geometries to Layer | **MISSING** | — | M5 |
| 捕捉/延伸到要素 Snap/Extend Features | **MISSING** | — | M5 |
| 追踪 Tracing | **PARTIAL**（C++ 完整实现 + Python setter，**无 UI 面**） | `map_stack_service.cpp:5345-5376`；`composite_editing.py:2394-2399` | **M1** |

## 2. 捕捉工具条（Snapping toolbar）全量对齐

| QGIS 项 | 现状 | 代码坐标 | 目标阶段 |
|---|---|---|---|
| 启用/停用捕捉 | EXISTING（工具条 toggle + 对话框） | `tool_availability.py:156`；`composite_panels.py:175-441`；C++ `setSnappingConfig` `map_stack_service.cpp:4706-4860` | — |
| 捕捉模式选择器（所有图层/当前图层/高级配置） | **PARTIAL**：模型有 `current_layer_only`，**无 UI**；且因为总是下发 `layers` 逐层表，QGIS 侧实际恒为 `AdvancedConfiguration` | `composite_editing.py:2304-2396`；C++ 分支 `4792-4799` | **M1** |
| 捕捉选项对话框（逐层模式/容差/单位/避免重叠） | **PARTIAL**：对话框有 enable/vertex/segment/容差/优先级，**无单位选择、无避免重叠项**；endpoint/intersection/midpoint 只有全局开关 | `composite_panels.py:175-441` | **M1** |
| 容差单位（像素/地图单位/厘米/毫米/英寸） | **PARTIAL**：C++ 硬编码像素 | `map_stack_service.cpp:4792`（`setUnits(Qgis::MapToolUnit::Pixels)`） | **M1** |
| 启用拓扑编辑 Enable topological editing | EXISTING（工具条 checkable；**同时**兼作保存期 Python 校验开关——与 QGIS 语义不同，见 04 D6） | `tool_availability.py:156`；`composite_editing.py:2420-2436` | — |
| 交点捕捉 Snap on intersections | EXISTING（对话框开关 → `config.setIntersectionSnapping`） | C++ `4803-4810`；manifest `snapping_intersection` 门 | — |
| **避免重叠 Avoid overlap（活动层 / 指定层）** | **PARTIAL**：逻辑+C++ 完整（`AllowIntersections/AvoidIntersections*`），**无任何 UI 面**；应用从不发 `layer_doc_ids`，`AvoidIntersectionsLayers` 分支不可达 | C++ `4748-4790`；`composite_document.py:2387-2393` 仅 handler | **M1** |
| 追踪 Tracing 开关 | **PARTIAL**：实现齐全，无工具条/对话框入口 | 同上 §1 | **M1** |
| 捕捉指示器 | EXISTING（`QgsSnapIndicator`） | `edit_tools.hpp:80-99` | — |
| 捕捉读数（层/类型/距离） | **PARTIAL**：`snap_feedback` 信号已发，**无消费方**（状态条不显示） | `canvas_shim.py:369, 320-323`；`composite_document.py:1214` | **M1** |
| 自捕捉 Self-snapping | **PARTIAL**：恒生效（活动层自分层表内），无开关无指示 | C++ `4811-4830`（活动层在逐层表内） | **M1** |
| 比例依赖捕捉 Scale-dependent | **MISSING**（`scaleDependencyMode` 从未设置） | — | M4 |
| 逐层捕捉优先级 | **PARTIAL**：对话框有列，**不下推 QGIS**，原生路径无效果 | `map_interaction.py:373-378` | M4 |
| 网格捕捉 | **PARTIAL**：Python 专有（回退栈），明确不下推 | `map_interaction.py:425-431`；`composite_editing.py:2309` | 记录项 |
| 参考层/井点捕捉 | EXISTING（`pwb/reference` 自动并入 vertex 捕捉） | C++ `4831-4843`；对话框复选框 | — |
| 捕捉参与层登记（图层右键「参与捕捉」） | EXISTING | `composite_document.py:548-553`；`qgis_mirror.py:983` | — |
| 顶点档位（当前层/全部层） | **PARTIAL**：实现有（M2），**无 UI 面** | `composite_editing.py:1742-1745`；C++ `set_vertex_edit_scope` | **M1** |
| 角色推荐捕捉档（12px/8px 等） | EXISTING | `mapping_workspace/snapping_profiles.py:28-122` | — |

## 3. 顶点工具与拓扑编辑（深度）

| 能力 | 现状 | 代码坐标 | 目标阶段 |
|---|---|---|---|
| 单节点拖动 | **PARTIAL**（v2 实现完整，但 Windows 上崩溃：01 D-A） | `edit_tools.cpp:1004-1042, 493-515` | **M0** |
| 共享节点联动（同层环 / 跨层） | EXISTING（M1/M2，单宏撤销、跨层入集） | `edit_tools.cpp:430-487, 800-850`；`tests/test_qgis_topo_m1_native_editing.py` | **M0**（修完 D-A 后回归） |
| 框选多节点 + 平移拖动 | EXISTING（phase2） | `edit_tools.cpp:517-620`；`tests/test_qgis_topo_phase2.py` | — |
| 段上双击插点 | EXISTING（native-only） | `edit_tools.cpp` insert 路径；`tests/test_qgis_v10_edit_tools.py` | — |
| Delete 删点（悬停语义） | EXISTING（连续 Delete 需重新 hover——V10 11-#3） | 同上 | M2 |
| 悬停高亮 | EXISTING | `edit_tools.cpp:1347+` `updateHoverMarker` | — |
| 拖动期捕捉跟随 | EXISTING（`snapOrRaw` 走 `QgsSnappingUtils`） | `edit_tools.cpp:252-258` | — |
| 段移动（segment move） | **MISSING**（V10 判 DEFERRED，phase2 只做了节点框选） | — | M2 |
| 移动要素的捕捉跟随 | **MISSING**（`PwbMoveTool` 原始 dx/dy） | V10 11-#6 | M2 |
| 拓扑点传播（vertex move / feature move / 新要素） | EXISTING | `edit_tools.cpp:753-798, 1141-1144, 1478-1490`；`map_stack_service.cpp:3562-3566` | — |
| 避免重叠裁切（拖动/捕获） | EXISTING（无 UI，默认开） | `edit_tools.cpp:725-745`；`composite_editing.py:691` | **M1** |
| 追踪（捕获期沿既有边） | EXISTING（无 UI） | `map_stack_service.cpp:5345-5376` | **M1** |
| 保存期拓扑门禁（零错误）+ 地质不变量 + 全或无 | EXISTING | `native_edit_session.py:204-332`；`topology_checker.py`；`geological_invariants.py:328-349` | — |
| 拓扑错误定位/跳转（检查器 → 画布） | **PARTIAL**（有 highlight 通道，QC hub 未接线——paleo-ui-workbench 04-#64） | `canvas_shim.highlight_features` | M4 |
| 共享弧重塑 / 断层切割 / DCEL 多边形化 | **PARTIAL**：C++ 与 `geotopo_service` 都有，**UI 不可达**（`fault_cut`/`boundaryReshape` 无 action 登记） | `tool_availability.py:137-169`（无 fault_cut）；`map_stack_service.cpp:4966, 5079` | M4 |
| 捕捉快照/恢复（工程级持久化） | EXISTING | `map_interaction.py:485-583` | — |

## 4. 联动矩阵（用户问的"联动"：工具 × 捕捉/拓扑/追踪/避免重叠）

| 工具 | 捕捉（`QgsSnappingUtils`） | 拓扑点传播 | 追踪 | 避免重叠 | 证据 |
|---|---|---|---|---|---|
| 添加点/线/面（digitizer） | ✅ | ✅（新要素 scatter） | ✅（tracer 注册即全体捕获工具生效） | ✅（捕获期裁切） | `map_stack_service.cpp:4929`, `:3562-3566`, `:5345-5376` |
| 顶点工具（拖动/插点） | ✅（`snapOrRaw`） | ✅（`addTopologicalPoints` + scatter） | n/a（非捕获工具） | ✅（move 路径） | `edit_tools.cpp:252-258, 754-757` |
| 移动要素 | ❌（原始 dx/dy，**无捕捉**） | ✅ | n/a | ✅ | V10 11-#6；`edit_tools.cpp:725-745` |
| 重塑 / 切分 / 合并 | ✅（digitizer / 引擎） | ✅（split 的 `topology_test_points`） | ✅ | ✅ | `map_stack_service.cpp:3677-3701` |
| 添加内环/部件 | ✅ | ✅ | ✅ | ✅ | `edit_tools.cpp` 路由 |

**联动不变量（本集要钉死的三条）**：

1. **单一权威**：捕捉/拓扑/追踪/避免重叠四态只有一个权威（`SnappingService` + `TopologyService` 开关），任何表面（工具条/对话框/命令面板/快捷键）改动都经同一 dispatcher（`composite_document._on_command_requested`）落权威再统一下推——现有实现已如此，**但** `avoid_intersections` / `tracing` / `vertex_scope` 只有 handler 没有表面，等于"半边联动"。
2. **会话前提**：所有编辑工具共享同一会话权威（原生 `SESSION_SET` / Python `edit_session`），工具激活门禁必须用同一份事实（`tool_availability._editing_gate`），**不得**出现"按钮亮着但画布侧无编辑目标"（正是 D-B 的形态）。
3. **呈现一致**：捕捉命中、拓扑点、拒绝原因都要在**同一状态通道**可见（状态条 + `commit_rejected` + `tool_operation`），不做无声死键（D-B2/D-B3）。

## 5. 本集不做的（记录理由）

| 项 | 理由 |
|---|---|
| Z/M 维度编辑 | 系统 2D（V10 `NOT_REQUIRED`） |
| QGIS app 层 `QgsVertexTool` / CAD dock 原样复用 | 不可链接；CAD 面板默认隐藏仅作构造断言 |
| RAW 保护层直接编辑 | 沿用保护约束（派生草稿路径不变） |
| 100GB 地震数据相关 | 硬排除 |
