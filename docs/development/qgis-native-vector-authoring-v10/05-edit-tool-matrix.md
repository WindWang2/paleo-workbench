# 05 — Edit Tool / Capability Matrix（V10）

分类词汇（与 goal 对齐）：

- `AVAILABLE_QGIS` — vendored QGIS 4.2 公开 API 提供且已由 bridge 接入，生产执行
- `EXISTING_PWB_NATIVE` — 薄 QGIS-native 工具已实现（自研 MapTool，非 app 层链接）
- `EXISTING_PWB_FALLBACK` — Python fallback 已实现（shapely/纯 Python）
- `PARTIAL` — 部分实现（注明缺口）
- `MISSING` — 无实现
- `UNSUPPORTED_BY_QGIS_BUILD` — 本 vendored 构建不暴露所需 API
- `NOT_REQUIRED` — 地质工作流判断不需要（记录理由）
- `DEFERRED` — 记录在案的延后项（引用来源决策）
- `V10-NEW` — 本轮新增

## A. 矩阵

| 能力 | V9 状态 | V10 状态 | 执行路径 / 证据 |
|---|---|---|---|
| navigation（pan/zoom/extent） | AVAILABLE_QGIS | 不变 | kind pan/zoomIn/zoomOut；`QgsMapToolPan/Zoom` |
| selection（click/rectangle + modifiers） | EXISTING_PWB_NATIVE + FALLBACK | 不变 | `PwbSelectTool`（QgsMapToolSelectionHandler）；fallback `SelectTool`/`RectangleSelectTool` map_tools.py |
| select all / invert / clear | PARTIAL（VectorLayer API 有，工具面未接） | **V10-NEW** COMPLETE | controller edit_command 扩展 + 工具面动作 |
| point capture | EXISTING_PWB_NATIVE + FALLBACK | 深化 | `QgsMapToolDigitizeFeature` addPoint；scratch + CRS 守卫 |
| line capture | 同上 | 深化 | 同上 addLine |
| polygon capture | 同上（fallback 自动闭合） | 深化 | 同上 addPolygon |
| capture 过程反馈（当前坐标/段长/总长/闭合预览） | PARTIAL（measure 有，capture 无回传） | **V10-NEW** | digitize `digitizing` 过程回调（流式 points/total） |
| Backspace 撤销上一捕获顶点 | 未验证 | **V10** 验证/补 | QgsMapToolCapture 键盘语义测试 |
| capture 中途切层/切阶段/会话关闭 | PARTIAL（无系统测试） | **V10** 测试 | lifecycle 压力测试 |
| vertex move（drag） | EXISTING_PWB_NATIVE + FALLBACK | 修复 | `PwbVertexTool`；ring 闭环不变量修复 |
| vertex insert | MISSING（session API 无人调用） | **V10-NEW** NATIVE | `PwbVertexTool` 双击段上 → `vertex_inserted` → session.insert_vertex |
| vertex delete | 同上 | **V10-NEW** NATIVE | `PwbVertexTool` Delete on hover → `vertex_deleted` → session.delete_vertex |
| hover vertex marker | MISSING | **V10-NEW** | `PwbVertexTool` canvasMoveEvent 就近顶点 marker |
| multi-vertex selection / segment move | MISSING | DEFERRED | QGIS vertex tool 深交互；地质工作流收益低（记录于 11） |
| ring-aware / multipart-aware vertex path | PARTIAL（未系统审计） | **V10** 审计+测试 | `[ring,v]` / `[part,v]` / `[part,ring,v]` 对抗测试 |
| Z/M 保持 | NOT_REQUIRED | 不变 | 系统 2D（`_point()` 构造期降维，全局一致） |
| feature move | EXISTING_PWB_NATIVE + FALLBACK | 不变 | `PwbMoveTool` 原始 dx/dy（无 snap，记录） |
| reshape | EXISTING_PWB_NATIVE（native-only by design） | 完善门禁+测试 | digitizer addLine → `geometry.reshape` → set_geometry |
| split（polygon by line） | BOTH（QGIS engine + shapely） | 属性继承审计+测试 | `geometry_command("split")` |
| merge（polygons union） | BOTH | 属性策略审计+测试 | `geometry_command("merge")` |
| delete selected | COMPLETE | 不变 | session.delete_feature |
| duplicate selected | MISSING | **V10-NEW** | controller edit_command("duplicate_selected") → add_feature |
| add ring（内环） | PARTIAL（session API 无人调用） | **V10-NEW** | 捕获环 → session.add_ring（QGIS validate 校验） |
| delete ring | 同上 | **V10-NEW** | 选择含内环面要素 → 最近内环节点定环 → session.delete_ring |
| add part | MISSING | **V10-NEW** | 捕获部件 → bridge `geometry.add_part` → session |
| delete part | MISSING | **V10-NEW** | 部件选择（pick part）→ bridge `geometry.delete_part` → session |
| move part | MISSING | **V10-NEW** | 部件平移（翻译 part 坐标）→ session |
| multipart→singlepart（explode） | PARTIAL（几何库函数无 session 写入） | **V10-NEW** | split_feature 命令（属性继承） |
| singlepart→multipart（collect） | 同上 | **V10-NEW** | merge_features 命令（collect 不 dissolve） |
| geometry repair | BOTH | 不变+测试 | make_valid → set_geometry |
| rotate / scale feature | MISSING | DEFERRED | V8 D4 拒绝（地质语义 + RAW-lock 冲突），沿用 |
| copy/paste（要素剪贴板） | MISSING | DEFERRED | duplicate 已覆盖主场景；跨层粘贴语义需单独设计（11） |
| snapping（vertex/segment/midpoint/endpoint/intersection/参考层/容差/像素单位） | EXISTING（AdvancedConfiguration 下推） | 不变 | `set_snapping_config`；QgsSnappingUtils 执行 |
| snapping feedback（marker + 匹配信息回传） | MISSING | **V10-NEW** NATIVE | `PwbSnapIndicator` + `snap_feedback` 回调 |
| grid snapping | PARTIAL（Python-only，不推送 QGIS，V7 08-4） | 不变 | fallback 路径专属 |
| self-snapping（捕获层自身参与） | 未验证 | **V10** 验证 | advanced config 含活动镜像层即含自身 |
| topological editing（捕获期） | AVAILABLE_QGIS（V9 下推） | 不变 | `QgsProject::setTopologicalEditing` |
| topology 传播 + compound undo | EXISTING（TopologyService） | 文档+测试 | propagate_shared_vertex + CompoundUndoGroup |
| measurement | EXISTING_PWB_NATIVE + FALLBACK（测地） | 不变 | `PwbMeasureTool` / pyproj.Geod |
| identify | EXISTING_PWB_NATIVE + FALLBACK 多层 | 不变 | `QgsMapToolIdentifyFeature` / identify_all |
| attribute 交互（表/编辑器/约束） | EXISTING（V9 W5） | 不变 | composite_attribute_table |
| undo / redo / rollback / commit | EXISTING | invariant 测试 | session undo/redo/rollback；compound 组 |
| tracing | MISSING | DEFERRED | V8 D4 |
| advanced digitizing（CAD 约束面板） | MISSING（隐藏 dock 仅构造断言） | DEFERRED | V8 D4 |

## B. 分路径细节（关键项）

### vertex 三操作（V10 后）

```
native:  PwbVertexTool
           press→pick+nearestVertex→drag（snap 跟随预览）→release→vertex_moved
           doubleClick on segment→vertex_inserted(path=插入位, x, y)
           hover→marker; Delete on hover→vertex_deleted(path)
         ↘ canvas_shim 适配 → map_tools.VertexTool.commit_vertex_{move,insert,delete}
             → 门禁 + edit_source(native) + 宏 + session.set_vertex/insert_vertex/delete_vertex
fallback: VertexTool 鼠标路径仅 move（维持 V7 §5 fallback 不扩张规则）
session:  ring 闭环维护（首/尾顶点变更联动闭合点）+ 最少顶点守卫
```

### ring / part / convert（V10 后）

```
add_ring:    polygon 捕获（digitizer）→ session.add_ring（≥3 点、自动闭合）
delete_ring: 面要素含内环 → pick 最近内环顶点定 ring_index → session.delete_ring
add_part:    捕获部件几何 → bridge geometry.add_part → session.add_part（QGIS 语义）
delete_part: pick 部件（部件含 pick 点）→ bridge geometry.delete_part → session
move_part:   部件平移 → session.move_part（复用 _translate 语义限定 part）
explode:     multipart 要素 → bridge multipart_to_singlepart → session.split_feature(replacements)
collect:     ≥2 同型单部件要素 → bridge singlepart_to_multipart → session.merge_features(collect)
```
