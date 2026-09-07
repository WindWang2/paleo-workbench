# 04 — Implementation Notes（实现笔记）

按模块记录「改了什么 / 在哪 / 为什么这样改」。行号以本分支最终状态为准。

## 1. 新契约模块（纯 Python，无 Qt）

| 模块 | 内容 |
|---|---|
| `paleo_workbench/mapping/capability_model.py` | `QgisCapabilitySnapshot`（status/reason/native_tools/geometry_ops/dialogs/features + `feature()/native_tool()/geometry_op()/capability_flags()`）、`LayerCapabilitySnapshot`（§8 十三项能力，逐项 `(available, reason)`）、`probe_qgis_capability()`（try-import + manifest 解析，旧桥→degraded）、`snapshot_stable_hash()`（EditDelta 溯源摘要） |
| `paleo_workbench/mapping/tool_context.py` | `ToolContext` frozen dataclass（goal §3 全字段 + `can_previous/next_extent`、`hidden_by_stage_profile`）、`build_tool_context(controller_state, ...)` 采集器 |
| `paleo_workbench/mapping/tool_availability.py` | `ToolAvailability`、`TOOL_IDS`（30 工具）、`evaluate_tool/evaluate_all`；gate 链 `_canvas_gate → _layer_gate → _writable_gate → _role_gate → _editing_gate → …`（粗→细，原因展示最根本阻断） |
| `paleo_workbench/mapping/edit_delta.py` | `EditDelta`（goal §6 字段 + `related_feature_ids` 扩展）、`delta_from_command()`（12 种 EditCommand → 8 种归一操作映射）、`geometry_hash()`、`DELTA_JOURNAL_LIMIT=1024` |

## 2. 会话层（`vector_layer.py`，最小侵入）

- `VectorEditSession.__init__`：+`session_id`（uuid4）、`delta_journal`、`_delta_order`、`_delta_source_tool`、`_pending_deltas`、`qgis_capability_token="unavailable"`。
- `_record()` 尾部挂 `_record_delta(command)`；`begin/end/destroy_edit_command` 维护 pending 扁平化（compound 的成分 delta 全保留，销毁的 compound 丢弃 delta）。
- `edit_source(tool_id)` context manager：native 工具 commit 路径标注 `<tool>(native)`，鼠标 fallback 路径 `<tool>(python-fallback)`。
- `rollback_changes()` 清空 delta journal（回滚 = 编辑从未落地）。
- undo/redo 不产生 delta（历史导航非新编辑）。

## 3. 工作站接线

- `composite_editing.py`：
  - `tool_context_inputs()`：ToolContext 宿主侧采集（图层/会话/选集/门禁/split-merge-reshape ready/捕捉拓扑/current_tool）。
  - `_open_session()` 单点开 session + 注入 `qgis_capability_token`；`start_editing`/`ensure_layer_session`/`import_layer_features`/`repair_layer_geometries` 全部改走它。
  - `_propagate_shared_vertex()`：VertexTool `on_vertex_committed` 接线（基线断线修复），只向门禁放行图层传播。
  - `_make_reshape_applier()`：桥 `geometry.reshape` → `SetGeometryCommand`。
  - `activate_tool()`：+reshape 分支（applier 为 None 时拒激活保持当前工具）；VertexTool 装配带传播钩子。
  - `_push_snapping_config()`：endpoint/intersection 能力门控下推（`_bridge_snapping_features()` 读 manifest features）。
  - split/merge/repair/domain_import 全部 `edit_source` 标注。
- `composite_document.py`：
  - `__init__`：`_qgis_capability = probe_qgis_capability()` + token 注入；measure/identify 信号连接（鸭子类型，fallback 画布无信号自动跳过）。
  - `_build_tool_context()`：controller inputs + raw/stage 细分（role_of 判 RAW；gate 拒绝且非 RAW → stage_locked）+ extent 历史 + stage hidden 集。
  - `_sync_action_state()`：`evaluate_all → apply_availability`（替代 update_state + split 特例 + checked 回写三段散落逻辑——单一权威）。
  - `_stage_hidden_edit_actions()` + `apply_stage_tool_profile()` 委托（可见性单权威）。
  - `_on_measure_updated()`（椭球 m/km vs 地图单位格式化）+ `_on_native_identified()`（Python 权威记录组装 → Identify Results 面板）。
- `map_action_controller.py`：+`reshape` checkable 动作/label；`apply_availability()`（enabled+visible+checked+reason tooltip/statusTip；`update_state` 保留给编图页宿主）。
- `map_status_bar.py`：+`measure` 标签与 `set_measure()`（独立于 update_state——指针频率事件不与状态刷新耦合）。
- `map_tools.py`：docstring fallback 声明；`ReshapeTool`（native-only，无鼠标路径）；capture/move/vertex 的 finish（python-fallback）与 commit_*（native）双路径 edit_source 标注。

## 4. native 桥（C++）

- `bindings.cpp`：模块级 `capability_manifest()`（contract_version=2；native_tools/geometry_ops/dialogs/features 四张编译期注册表，与 setMapTool/geometry.def 的同步义务由 `test_qgis_v7_authoring` 钉住）；geometry 子模块 +`validate`（返回 py::list[{where,message}]）/`reshape`；mapstack +`set_measure_callback`；版本 0.2.17a0→0.3.0a0。
- `edit_tools.{hpp,cpp}`：`PwbMeasureTool : PwbEditPickTool`（复用 snapOrRaw/Esc；左键采点/右键完成/Esc 取消；QgsDistanceArea 按画布 CRS+工程椭球自动椭球/平面测算；QgsCsException 落平面并如实标注 ellipsoidal=false；`measuring()` 供 nativeToolBusy）。
- `map_stack_service.{hpp,cpp}`：setMapTool +`measure` kind（display 模式放行）；`measure_tools/measure_callbacks` 表 + 孤儿坟场 + shutdown/reap/destroy 全链回收；`nativeToolBusy` 覆盖测距；`parseSnappingTypes` +`endpoint`（LineEndpoint）；`setSnappingConfig` +`intersection_enabled`→`setIntersectionSnapping`。
- `geometry_service.{hpp,cpp}`：`geometry_validate`（QgsGeometry::validateGeometry GEOS 引擎逐错误；非 const API 取副本）+ `geometry_reshape`（reshapeGeometry，NothingHappened→明确报错）。

## 5. 拓扑（`topology.py`）

- `TopologyService._bridge_validate_fn()`（桥 `geometry.validate` 探测，失败→None）；`_validate_geometry_detailed()` QGIS 优先、Shapely 回退；`validate()` 双引擎均不可用时返回 `validator_unavailable`（原 `shapely_unavailable` 语义泛化）；环闭合检查保留（Paleo 语义层）。
- `repair_invalid_geometry`（Shapely 兜底）不变——`geometry_service.make_geometry_valid` 的 QGIS 优先路由不变。

## 6. 测试

- `tests/test_authoring_contracts.py`：契约层 61 用例（快照/上下文/全矩阵状态机/不变量/EditDelta 纯函数与会话集成）。
- `tests/test_workstation_authoring_kernel.py`：工作站集成 9 用例（context 构建/原因通道/dirty 门/RAW 锁/fallback 溯源/split 标注/拓扑传播/门禁过滤/token 注入）。
- `tests/test_v7_stability_probes.py`：稳定性/性能探针 12 用例（evaluator 复杂度比、journal 上界、1k/10k/100k 规模、100x 激活循环、50 层切换、10k 选集语义）。
- `tests/test_qgis_v7_authoring.py`：QGIS 标记（PALEO_REQUIRE_QGIS=1 腿）：manifest 权威/派生一致性、validate/reshape、原生测距激活与回调、display 模式、endpoint/intersection 下推。

## 7. vendored QGIS（third_party/qgis）

- `CMakeLists.txt`：`include(CheckFunctionExists)` 提升（Windows 硬错误修复）。
- `platform/windows/rc/version.rc.in`：从上游 final-4_2_0 原样补回。
- UPSTREAM.md 记录两处补丁。
