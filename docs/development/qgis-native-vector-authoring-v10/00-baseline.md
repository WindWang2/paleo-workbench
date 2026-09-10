# 00 — Baseline（V10）

执行时间：2026-09-11。基线 `origin/main = 3b0e2ba2`（V9 三 PR
#1248/#1249/#1251 + SVG 图案 #1250 全部合入；open PR = 0，open issue = #1230
（CI P2，慢速真实数据族门禁——按 V10 规则本地验证即 gate，不为本轮改架构）。
worktree：`../paleo-workbench-qgis-vector-authoring-v10`，分支
`feat/qgis-native-vector-authoring-v10`。

## A. 运行时状态

- **Open PR：0**；最近合并 #1248 (QGIS Geological Authoring V9)、#1249
  (Interpretation Workbench V9)、#1250 (SVG 沉积相图案)、#1251 (Adaptive UI V9)。
- **并行 worktree**：v7 系 3 + v8 系 3 + v9 系 2，全部已合并，无未合并提交，
  与本分支无冲突面。
- **测试环境**：本 worktree 自建 `.venv`（Python 3.12.13 + PySide6 6.8.3 +
  pybind11 3.1.0），桥增量构建复用
  `paleo-workbench/.worktrees/qgis-native-authoring-v7/.../build/qgis-vendor`
  （`PALEO_QGIS_REUSE_VENDOR=1` + `PALEO_QGIS_BUILD_DIR`，Qt 前缀
  `C:/deps/Qt/6.8.0/msvc2022_64`）。运行入口 `scripts/run_qgis_env.py`
  （v8 配方：vendor bin → PySide6 单 Qt loader 规则）。
- **vendored QGIS = 4.2.0**（`final-4_2_0`，直接检入 `third_party/qgis`，
  4 个已记录 patch；`WITH_PYTHON=OFF`——全系统无 `qgis.core` Python 导入，
  真实 QGIS 路径一律走 pybind 扩展 `qgis_render_bridge`）。

## B. 已交付基线（禁止重做）

| 来源 | 已交付 | 证据 |
|---|---|---|
| V7 #1236 | capability manifest（编译期唯一真源）、ToolContext、45 工具 canonical evaluator、native identify/select/measure、reshape（native-only）、endpoint/intersection snapping 下推、QGIS-first validate、EditDelta 审计流 | `mapping/capability_model.py`、`tool_context.py`、`tool_availability.py`、`edit_delta.py` |
| V7 #1237 | GeologicalLayerSpec V2、geometry facade（15 bridge ops + shapely 回退 + engine 披露）、增量 mirror 发布 ledger | `mapping_workspace/geological_layer_spec.py`、`mapping/geometry_operations.py`、`qgis_mirror.py` |
| V8 #1238 | provider fields_json→QgsFields/约束/编辑控件、跨图层 compound topology undo、duplicate-GIS 收敛、行指示器、legend filter、QTimer lifecycle 守卫 | `qgis_layer_schema.py`、`topology.py`、`map_stack_service.cpp` |
| V8 #1239/#1240 | 科学工作流版本化约束、context control plane、命令面板 | `ui/workstation/*` |
| V9 #1248 | ToolContext v3（CRS/scale facts、manifest-derived availability、blocking_task）、topology_error_count 运行时缓存 + QGIS topologicalEditing 下推、crs_contract 单一 CRS 权威、per-role snapping profiles、属性表消费 provider schema、role→CaptureSpec 捕获语义、digitize CRS 守卫 | `tool_context.py`、`topology.py`、`crs_contract.py`、`mapping_workspace/snapping_profiles.py`、`capture_spec.py` |
| V9 #1249/#1251 | mapping-stage 收敛、mock 相面预测、adaptive dock 框架 | `mapping_workspace/*`、`ui/workstation/*` |

### 会话/事务权威（现状，V10 不重建只加固）

`VectorEditSession`（`mapping/vector_layer.py:319`）：

- 命令模式（`EditCommand` before/after 快照，12 个子类）+ 宏
  （`begin/end_edit_command` → 单层 compound undo 单元）+ 跨图层
  `TopologyService.CompoundUndoGroup`（身份匹配 pop/push-back，线性 redo 守卫）。
- 修订日志（`JOURNAL_LIMIT=1024`，`changes_since` 增量镜像协议）+
  `EditDelta` 前向审计流（1024 滑窗；undo/redo 不产生 delta——by design）。
- 已接入 session 的操作：add_feature / delete_feature / move_feature /
  set_vertex / set_geometry(reshape/repair) / change_attribute / split_feature /
  merge_features / add_ring / delete_ring / insert_vertex / delete_vertex
  （后两者**仅有 session API，无生产调用方**）/ topology 传播 set_vertex /
  domain import add_feature。

### Native 工具面（现状）

`edit_tools.cpp`（薄 QGIS MapTool，app 层 QgsVertexTool 不可链接的裁剪重实现）+
`map_stack_service.cpp`：

- `PwbVertexTool`（vertex **move** only）、`PwbMoveTool`（feature move，原始
  dx/dy 无 snap）、`PwbSelectTool`（QgsMapToolSelectionHandler，
  click/rectangle + QGIS modifier 语义）、`PwbMeasureTool`（QgsDistanceArea 椭球/
  平面）、`QgsMapToolDigitizeFeature` 捕获（point/line/polygon，scratch 层
  `__pwb_capture_scratch`，CRS 守卫，hidden CAD dock 仅为构造断言）、
  `QgsMapToolIdentifyFeature`（构造期钉住 currentLayer）。
- 回调全部 `alive_token_` weak 守卫 + dead-canvas 墓碑 + 孤儿回调坟场；
  镜像层只读（provider 级 delete+re-add 增量刷新），scratch 是唯一
  `startEditing` 的层且不落持久化。

## C. 本轮基线审计结论（6 个并行 subagent 深审 + 主 agent 复核）

### C1 — V10 入场缺口（本方向要做的）

1. **闭环 ring 不变量破坏（P1 正确性缺陷）**：`set_vertex`
   （`vector_layer.py:495`）替换单坐标，不维护 GeoJSON ring 首=尾闭合。
   native 拖动 ring 首顶点（`[r,0]`）或闭合重复点（`[r,N-1]`）后权威几何
   ring 不闭合（RFC 7946 违规）。`nearestVertex` 的严格 `<` tie-break 只缓解
   hover 恰在重复点上的情形。`insert_vertex`/`delete_vertex` 同样无闭合维护。
2. **vertex insert/delete 无 canvas 触发路径**：session API 存在，但
   workstation 无任何调用（legacy 场景有自己的非 session 路径）。
   `PwbVertexTool` 只有 move。无 native hover marker、无双击插点、无 Delete 删点。
3. **ring/part 操作无工具面**：`add_ring`/`delete_ring` 仅 session API +
   tests；无捕获环/删环交互。part 操作（add/delete/move part、multipart↔
   singlepart 编辑命令）完全缺失（仅几何库函数，无 session 写入方）。
4. **duplicate feature 缺失**；split 属性继承 / merge 属性策略未审计未测试。
5. **snapping feedback 缺失**：无 snap marker、无匹配信息（层/要素/顶点 vs
   边/距离）回传宿主。QGIS desktop 的 QgsSnapIndicator 属 app 层不可链接。
6. **capture 过程反馈与生命周期边界**：段长/总长回传？Backspace 撤销上一
   顶点在中断言用的 CAD dock 隐藏时是否可用未验证；中途切层/切阶段/会话关闭
   的取消路径无系统测试。
7. **选择面不完整**：`select_all`/`invert_selection` 在 `VectorLayer` 有 API，
   workstation 工具面未接（待复核）。

### C2 — 审计确认无需重做/保持现状

- 事务链完整性：无 Python 直改 QgsVectorLayer 的路径（grep 零命中）；
  唯一 sanctioned 写路径 = C++ mirror upsert（provider 级）+ scratch 捕获层。
  legacy `map_edit_scene.py` 是并行第二编辑面，但已降级为
  validator/migration mirror（mapping_page 显式 demote），V10 只记录不扩张。
- ToolContext 收集链无 O(features) 热点（frame-level、O(layers) 封顶）；
  topology validate 只在有限刷新点跑。
- 生命周期工程（alive_token/墓碑/坟场/pin-before-unset）V7-V9 已加固，
  V10 补新回调路径的等价测试即可。

### C3 — 已知遗留（沿用既有记录，本轮不翻案）

- undo 栈无界（V7 08-14，接受）；EditDelta 1024 滑窗（V7 08-11，by design）；
  compound 组强引用至 256 逐出（V8 08-5）；`canvas_destination_crs` 在
  worktree 配方下 proj.db 缺失返回 ""（V9 09-1）；measure 工具 project-CRS
  角落（V9 09-3）；命令面板缺 split/merge/reshape（context-control-plane
  08-1）。详见 11-known-limitations.md。

## D. 硬排除（沿用）

- 100GB seismic 全链路零接触（测试只用 mock/synthetic/小型 fixture）。
- 不重建 vendored QGIS（复用 v7 worktree 构建产物）。
- 不做第二套 GIS 内核 / 第二 evaluator / 第二 role 表 / 第二 canvas 渲染系统。
