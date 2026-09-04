# QGIS 原生地图栈 M3（原生编辑工具链：采点/顶点/移动/选择 + 捕捉 + 键盘路径）实施计划

> **Status: COMPLETE** — merged to main at `52550ee9`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 综合编修区的编辑工具链换为 QGIS 原生 `QgsMapTool` 承载——采点/线/面用 `QgsMapToolDigitizeFeature`（原生 rubber band 预览 + 内置 Backspace/Esc + 自动捕捉），选择/identify 用 `QgsMapToolSelect`/`QgsMapToolIdentifyFeature`，顶点编辑与要素移动用桥内薄封装工具；捕捉配置从 Python `SnappingService` 映射进 canvas 自带 `snappingUtils()`；**要素写入权威保持在 Python `VectorEditSession`**（命令模式/undo/持久化/修订日志全部不动），QGIS 原生工具只做输入与预览层。

**Architecture:** 混合架构（Iron Law：**QGIS 计算、Paleo 记录**）。C++ 桥内扩展 `mapstack` 子模块：① 每画布建隐藏 `QgsAdvancedDigitizingDockWidget`（`QgsMapToolCapture` 派生链构造有 `Q_ASSERT(cadDockWidget)`，永不 show）；② `setMapTool` 的 kind 枚举从 pan/zoomIn/zoomOut 扩展到 addPoint/addLine/addPolygon/select/identify/vertex/move；③ 采点工具 `setLayer` 指向**桥内私有 scratch memory 层**（按几何类型切换，不进 QgsProject、不写镜像层），`digitizingCompleted(QgsFeature)` 只取几何转 GeoJSON 回调 Python；④ 顶点/移动工具自实现薄 `QgsMapTool`（snapToMap 拾取 + 拖动 rubber band 预览，mouseRelease 时回调 Python 执行命令）；⑤ 捕捉经 `canvas->snappingUtils()->setConfig(QgsSnappingConfig)`，状态权威仍是 Python SnappingService。所有数据变更经绑定回调（gil_scoped_acquire，QTimer.singleShot marshal 回 GUI 线程）落 `VectorEditSession` 既有命令链，镜像 reconcile 自动把结果刷回 QGIS 画布。

**Tech Stack:** PySide6 (Qt6), pybind11, vendored QGIS 4.2 (`third_party/qgis`), shiboken6, pytest + pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`；**M1（70c9811e）与 M2（55fcb640）已完成并合并 main**

## Global Constraints

- 硬依赖：不依赖系统 QGIS；只允许 vendored 构建（`native/qgis_render_bridge/build/qgis-vendor/output`）。
- 不向 QGIS 官方 Python 绑定（sip/PyQt6）迁移；进程内只有 PySide6 一套绑定运行时。
- C++ 边界：**No QWidget crosses the boundary as a typed object**——控件以 `uintptr_t` 地址传递，Python 侧只经 `shiboken6.wrapInstance` 还原。
- 绑定暴露给 Python 的名字必须 snake_case；GIL 只在 `bindings.cpp` 处理（回调必须 `gil_scoped_acquire`）；`map_stack_service.cpp` 保持纯 Qt/C++（禁止 pybind11/Python.h include）。
- **Iron Law：编辑权威/undo 栈/修订日志留在 Python 侧**（`VectorEditSession` 命令模式）。QGIS edit buffer / `QgsMapLayer::undoStack()` 只作参考，不替代 Python undo 栈；镜像 memory 层永不进 QGIS 编辑模式。
- **M2 事故教训：destroyed 信号内销毁含 py::function 的 std::function 会 segfault**（GC_Del on shiboken 延迟删除链）——新增回调清理一律走孤儿坟场模式，延后到 shutdown/dtor 销毁。
- 重建命令：`cd /home/kevin/projects/paleo_project/main && PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation`（env var 与 `--no-build-isolation` 必须带，网络不可用）。
- 测试一律经 `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args> -q --basetemp=$(mktemp -d)`（offscreen）。全量跑必须 `--deselect tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`（offscreen 段错误）。判断成败看输出里 `N passed/failed` 行，不看管道末命令退出码。
- 画布底色白色（既有决定）；M1/M2 既有 API 的签名/语义不得破坏。
- 所有提交在 `/home/kevin/projects/paleo_project/main` 工作区进行（功能分支 + 合并回 main，分支合并后删除）。**绝不提交 `.superpowers/`**；不提交 symbology-style.db/user-history.db。

## 已核实的环境事实（侦察结论，执行时直接采信）

### QGIS 侧（符号均经 nm 验证在 libqgis_gui）

- `QgsMapToolDigitizeFeature`（`third_party/qgis/src/gui/maptools/qgsmaptooldigitizefeature.h:32`）可直接绑定：`setLayer(QgsVectorLayer*)` 钉图层；信号 `digitizingCompleted(const QgsFeature&)`（:69）/ `digitizingFinished()` / `digitizingCanceled()`——免子类化。Esc 键内置触发 digitizingCanceled；Backspace/Delete 删上一顶点（Capture 链内置）。
- `QgsMapToolIdentifyFeature`（`featureIdentified(QgsFeature)` 信号）、`QgsMapToolSelect`（since 4.2，8 种选择模式）可直接绑定。
- **不可用（APP_EXPORT，gui 库无符号）**：`QgsVertexTool`（app/ 3447 行，不移植）、`QgsMapToolMoveFeature`、`QgsMapToolAddFeature`——顶点编辑与要素移动必须桥内薄封装自实现。
- `QgsMapToolCapture` 派生链构造有 `Q_ASSERT(cadDockWidget)`：必须建隐藏 `QgsAdvancedDigitizingDockWidget(canvas, nullptr)`（永不 show）；它碰 `QgsGui::instance()->advancedDigitizingToolsRegistry()`（QgsApplication 已初始化，OK）。
- 捕捉：canvas 构造时自带 `QgsMapCanvasSnappingUtils`（`qgsmapcanvas.cpp:3311`）；只需 `canvas->snappingUtils()->setConfig(QgsSnappingConfig)`。`QgsSnappingConfig`：mode（AllLayers/AdvancedConfiguration）、tolerance（px）、type flag（Vertex/Segment/MiddleSegment/Centroid）、`IndividualLayerSettings` per-layer 覆盖（:128）。消费链内建于 `QgsMapToolAdvancedDigitizing`（isAutoSnapEnabled 默认 true → snapToMap）。
- `QgsMapCanvas::setMapTool` 单画布互斥（deactivate 旧→activate 新，`mapToolSet` 信号）；keyPressEvent 先给工具再方向键平移。
- 编辑态信号（本 M3 不用 QGIS 编辑模式，仅供状态参考）：`editingStarted/editingStopped`（qgsmaplayer.h:2198/2204）、`beforeCommitChanges/afterCommitChanges`。
- 撤销重做参考：`QgsMapLayer::undoStack()` → 标准 QUndoStack（qgsmaplayer.h:1555）——本 M3 不接管，Python undo 栈仍是权威。

### Python 侧现状

- 工具类在 `paleo_workbench/mapping/map_tools.py`（基类 MapTool :29-66，事件签名 `mouse_press(point, *, button="left", modifiers=())`；_CaptureTool :210 → session.add_feature :264；MoveFeatureTool :286；VertexTool :320）。装配在 `composite_editing.py` `activate_tool` :807-863。
- **核心缺口：QgisCanvasShim 不转发鼠标/键盘事件给 Python 工具**。shim 的 `set_map_tool_controller`（`canvas_shim.py` :333-386）monkey-patch `tools.set_active_tool`，按 tool_id 映射 `stack.set_map_tool(addr, kind)`——kind 只有 pan/zoomIn/zoomOut，其余回落 pan。C++ `QgisMapStack::setMapTool`（`map_stack_service.cpp` :1152-1176）只建 QgsMapToolPan/Zoom。
- 会话/undo：`paleo_workbench/mapping/vector_layer.py`——VectorEditSession 命令模式（EditCommand before/after 快照对 :122-149；AddFeature/DeleteFeature/MoveFeature/SetGeometry/SetVertex 等 :152-209），undo/redo :512-532，commit :534 / rollback :539，_journal+changes_since :322-347。revision 进快照 `(data_revision<<32)+session.revision`（composite_editing.py :1168）。
- 捕捉：`mapping/map_interaction.py` SnappingService :371-467（px 容差、vertex/segment/midpoint、per-layer 覆盖、井位参考点）+ FeatureSpatialIndex :157-368（修订键控缓存，会话副本即时可见）。对话框 composite_panels.py :113-279。
- 工具条：`map_action_controller.py`（12 互斥工具动作 :42-45；undo=Ctrl+Z / redo=Ctrl+Shift+Z / cancel=Esc :88-96；update_state :99-119）；状态回流 `edit_controller.action_state()` :1269-1289。
- 当前 QGIS 画布上采点预览/选中高亮/捕捉标记全无可视化（shim 存而不画 canvas_shim.py :315-316）——M3 用 QgsRubberBand/原生工具自带 rubber band 补齐。
- Esc 现状路径：QAction 快捷键 → command_requested → cancel_active_tool（composite_editing.py :1105-1107）。
- 编辑中要素会进镜像（truncate+addFeatures 整块替换，镜像 memory 层从不进 QGIS 编辑模式）。
- 测试基线：test_composite_editing.py(16)、test_composite_gis.py(~45)、test_map_tools.py、test_vector_edit_session.py、test_map_interaction.py、test_qgis_mapstack_tools.py + 3 个性能回归文件。

---

### Task 1: 隐藏 cadDock + 捕捉配置绑定

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp`（追加声明）
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（cadDock 创建 + snapping config）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（绑定）
- Test: `tests/test_qgis_snapping_config.py`（新建）

**Interfaces:**
- Consumes: M1 `QgisMapStack`（create_canvas / canvas_refs QPointer 机制）。
- Produces:
  - `set_snapping_config(canvas, config_json: str) -> None`（JSON 形如 `{"enabled": true, "mode": "all_layers"|"active_layer", "tolerance_px": 12.0, "types": ["vertex","segment","midpoint"], "layers": {"<doc_id>": {"enabled": true, "types": [...], "tolerance_px": 8.0}}}`；doc_id 经 M2 的 `pwb/doc_id` customProperty 解析成 QgsMapLayer；mode 映射 QgsSnappingConfig::AllLayers/ActiveLayer/AdvancedConfiguration（有 layers 键时强制 AdvancedConfiguration）；types 映射 VertexFlag|SegmentFlag|MiddleSegmentFlag）
  - `snap_to_map(canvas, x: float, y: float) -> dict`（经 `canvas->snappingUtils()->snapToMap(QPointF)`，返回 `{"matched": bool, "x":..., "y":..., "layer_doc_id": str, "vertex_index": int(-1 表示非顶点)}`——供 Python 侧与测试验证捕捉链生效）
  - 内部：`createCanvas` 时为每画布建隐藏 `QgsAdvancedDigitizingDockWidget`（成员 QPointer 持有，画布销毁自动随父子关系回收；**不可在 destroyed 信号里做带 Python 回调的事**——M2 教训）
- Python 侧 `paleo_workbench/ui/qgis_stack/canvas_shim.py`：`set_map_tool_controller` 装配处挂 SnappingService 状态变更 → `stack.set_snapping_config` 的映射函数（`_push_snapping_config()`，从 SnappingService 读 enabled/tolerance/types/per-layer 覆盖序列化为上述 JSON）。

- [x] **Step 1: 写失败测试**

```python
# tests/test_qgis_snapping_config.py
"""M3 Task 1: 捕捉配置下推 C++ canvas snappingUtils 并生效。"""
import json
import pytest

pytest.importorskip("PySide6")

_GEOJSON_POINTS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "P1"}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_snap_to_map_matches_vertex_within_tolerance(qtbot, stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _GEOJSON_POINTS)
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True, "mode": "all_layers",
        "tolerance_px": 20.0, "types": ["vertex"],
    }))
    # 画布中心即 (5,5) 顶点处；偏离少量像素仍应命中
    result = stack.snap_to_map(canvas, 0.499, 0.501)  # 地图坐标，接近顶点
    assert result["matched"] is True
    assert abs(result["x"] - 5.0) < 1e-6
    assert abs(result["y"] - 5.0) < 1e-6


def test_snap_disabled_returns_no_match(stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _GEOJSON_POINTS)
    stack.set_snapping_config(canvas, json.dumps({"enabled": False}))
    result = stack.snap_to_map(canvas, 0.499, 0.501)
    assert result["matched"] is False
```

- [x] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_snapping_config.py -v --basetemp=$(mktemp -d)`
Expected: FAIL（`AttributeError: set_snapping_config`）

- [x] **Step 3: 实现 C++**

```cpp
// map_stack_service.hpp 追加（类 public 区）：
  void setSnappingConfig(std::uintptr_t canvas, const std::string& config_json);
  std::string snapToMap(std::uintptr_t canvas, double x, double y) const;  // 返回 JSON

// map_stack_service.cpp 追加
#include <qgsadvanceddigitizingdockwidget.h>
#include <qgssnappingconfig.h>
#include <qgssnappingutils.h>
#include <QJsonDocument/QJsonObject/QJsonArray>（按桥内既有 JSON 惯例——若无惯例用 Qt JSON）

// Impl 追加成员：
//   std::unordered_map<std::uintptr_t, QPointer<QgsAdvancedDigitizingDockWidget>> cad_docks;
// createCanvas 尾部：cad_docks[addr] = new QgsAdvancedDigitizingDockWidget(canvas, nullptr); // 永不 show
// setSnappingConfig：解析 JSON → QgsSnappingConfig（project 级 setConfig + snappingUtils()->setConfig）
//   per-layer：QgsSnappingConfig::IndividualLayerSettings(layer, enabled, type, tolerance, ...)
// snapToMap：QgsPointLocator::Match m = canvas->snappingUtils()->snapToMap(QPointF(x,y) 转屏幕或用地图坐标重载);
//   返回 {"matched": m.isValid(), "x": m.point().x(), ...}；layer_doc_id 从 m.layer() customProperty 读
```

- [x] **Step 4: 运行确认通过 + Python 侧接线**

canvas_shim.py 增 `_push_snapping_config()`：从 controller 的 SnappingService 读状态序列化下推；SnappingService 状态变更处（对话框确认/菜单勾选）调用。SnappingService 自身**不删**（仍是状态权威；采点命中逻辑改由 QGIS 端完成，Python 端 SnappingService 用于配置持久化与非画布消费方）。

- [x] **Step 5: 回归**

Run: `run_env.sh tests/test_qgis_snapping_config.py tests/test_qgis_mapstack_tools.py tests/test_map_interaction.py -q --basetemp=$(mktemp -d)`
Expected: 全绿（test_map_interaction 是 Python 侧 SnappingService 纯逻辑，不受影响）

- [x] **Step 6: 提交** `m3(bridge): hidden cadDock + snapping config pushdown`

---

### Task 2: QgsMapToolDigitizeFeature 采点/线/面接入（几何回调 → VectorEditSession）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（digitize 工具 + scratch 层）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（tool_id → kind 映射扩展 + 几何回调落 session）
- Test: `tests/test_qgis_digitize_tool.py`（新建）

**Interfaces:**
- Produces:
  - `set_map_tool(canvas, kind)` kind 扩展：`"add_point"|"add_line"|"add_polygon"|"pan"|"zoom_in"|"zoom_out"`（既有 pan/zoom 不变；未知 kind 回落 pan 的既有行为保留）
  - `set_digitize_callback(canvas, callback) -> None`（`callback(status: str, geojson_geometry: str)`；status ∈ `"completed"|"canceled"`；completed 时 geojson_geometry 为 GeoJSON geometry 对象字符串，canceled 时为空串）
  - C++ 内部：每画布持有 3 个桥内私有 scratch memory 层（Point/LineString/Polygon，EPSG:4326，**不进 QgsProject、不进镜像**），`QgsMapToolDigitizeFeature` setLayer 指向对应 scratch 层；`digitizingCompleted` → 几何转 GeoJSON → callback。scratch 层仅用于告知工具几何类型/CRS，不写要素。
  - 镜像策略决定：**digitize 工具不 setLayer 到镜像层**（镜像只读、永不进编辑模式）；scratch 层方案绕开「QgsMapToolDigitizeFeature 是否要求 layer editable」的不确定性。实施时若发现 DigitizeFeature 对非编辑态 layer 有 assert，scratch 层调 `startEditing()` 也无所谓——它不落持久化。
- Python 侧 canvas_shim：tool_id 映射表扩展 `add_point→add_point` 等；`set_digitize_callback` 回调里：status==completed → 当前 VectorEditSession `add_feature(geometry)`（经既有 `_CaptureTool` 同款落点，复用 composite_editing 的 session 解析），status==canceled → 不变更数据只刷新工具条状态。Python 旧 `_CaptureTool` 的鼠标事件路径在 QGIS 画布模式下不再被调用（shim 本来就不转发鼠标事件），保留该类供 headless/测试与非 QGIS 路径。

- [x] **Step 1: 写失败测试**

```python
# tests/test_qgis_digitize_tool.py
"""M3 Task 2: 原生采点工具 digitizingCompleted 几何回调。"""
import json
import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_add_point_tool_emits_completed_geometry(qtbot, stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "add_point")
    # 模拟画布中心一次左键点击（QTest.mouseClick 经 wrapInstance 的 QWidget）
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    w = wrapInstance(canvas, QWidget)
    qtbot.addWidget(w)
    w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.rect().center())
    qtbot.waitUntil(lambda: len(events) >= 1, timeout=2000)
    status, geom = events[-1]
    assert status == "completed"
    g = json.loads(geom)
    assert g["type"] == "Point"
    assert abs(g["coordinates"][0] - 5.0) < 0.2  # 容差内
    assert abs(g["coordinates"][1] - 5.0) < 0.2


def test_escape_cancels_digitizing(qtbot, stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "add_line")
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    w = wrapInstance(canvas, QWidget)
    qtbot.addWidget(w)
    w.show()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.rect().center())  # 起第一个顶点
    QTest.keyClick(w, Qt.Key_Escape)
    qtbot.waitUntil(lambda: any(s == "canceled" for s, _ in events), timeout=2000)
```

- [x] **Step 2: 运行确认失败**（`set_digitize_callback` 不存在 / kind 不识别）

- [x] **Step 3: 实现 C++**

```cpp
// map_stack_service.hpp public 区追加：
  void setDigitizeCallback(std::uintptr_t canvas,
                           std::function<void(const std::string&, const std::string&)> callback);
// setMapTool 已有（:1152-1176），扩展 kind 分派

// map_stack_service.cpp：
#include <qgsmaptooldigitizefeature.h>
// Impl 成员：
//   struct DigitizeSlot { QgsVectorLayer* scratch; QgsMapToolDigitizeFeature* tool; };
//   std::unordered_map<std::uintptr_t, std::array<DigitizeSlot,3>> digitize_slots; // point/line/poly
//   std::unordered_map<std::uintptr_t, std::function<void(const std::string&, const std::string&)>> digitize_callbacks;
// 首次切到 add_* kind 时惰性建 scratch 层（memory provider, "Point?crs=EPSG:4326" 等，
//   名字 "__pwb_capture_scratch"，不进 QgsProject）+ 工具（cadDock 从 Task 1 成员取，
//   工具构造后 setLayer(scratch)，connect digitizingCompleted → 几何 asJson → callback("completed", json)，
//   digitizingCanceled → callback("canceled", "")）
// setMapTool 分派：add_point → canvas->setMapTool(slot[0].tool)，其余 kind 走既有 pan/zoom 路径
// 回调 marshal：digitizingCompleted 在 GUI 线程触发，但 callback 经 bindings.cpp 的
//   gil_scoped_acquire 包一层（与 M2 树回调同模式）； destroyed 清理走孤儿坟场（M2 教训）
```

- [x] **Step 4: 运行确认通过 + Python 接线**

canvas_shim.py：tool_id → kind 映射表加 add_point/add_line/add_polygon；装配 `set_digitize_callback`：completed → 经 controller 当前活动 session `add_feature`（geometry dict）；session 不存在时忽略并记日志（与既有 `_CaptureTool` 无会话行为一致）。canceled → `action_state` 刷新。

- [x] **Step 5: 回归**

Run: `run_env.sh tests/test_qgis_digitize_tool.py tests/test_qgis_snapping_config.py tests/test_qgis_mapstack_tools.py tests/test_map_tools.py tests/test_vector_edit_session.py tests/test_composite_editing.py -q --basetemp=$(mktemp -d)`

- [x] **Step 6: 提交** `m3(bridge): native digitize tools for point/line/polygon capture`

---

### Task 3: 桥内顶点编辑工具 + 要素移动工具（薄封装）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（两个自实现 QgsMapTool 子类——新文件 `src/edit_tools.hpp/.cpp`，与 map_stack_service 同库）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`
- Test: `tests/test_qgis_vertex_move_tools.py`（新建）

**Interfaces:**
- Produces:
  - `set_map_tool` kind 再扩展：`"vertex"|"move"`
  - `set_edit_pick_callback(canvas, callback) -> None`（顶点/移动工具共用；回调签名按动作区分）：
    - 顶点拖动完成：`callback("vertex_moved", payload_json)`——`{"layer_doc_id": str, "feature_id": str, "vertex_index": int, "x": float, "y": float}`
    - 要素移动完成：`callback("feature_moved", payload_json)`——`{"layer_doc_id": str, "feature_id": str, "dx": float, "dy": float}`
    - 拾取失败（点空）：`callback("pick_miss", "{}")`
  - C++ 实现要点（薄，各 ≤150 行）：
    - `PwbVertexTool : QgsMapTool`：canvasPressEvent → `canvas->snappingUtils()->snapToMap`（优先顶点匹配）→ 命中则记 (layer, fid, vertex)，建 QgsRubberBand 预览；canvasMoveEvent 拖 rubber band；canvasReleaseEvent → callback("vertex_moved", ...)；Esc → 放弃。**不改镜像层数据**（镜像只读；权威变更走 Python session.set_vertex，镜像 reconcile 自动刷新）。
    - `PwbMoveTool : QgsMapTool`：press → snapToMap 要素匹配 → rubber band 画要素几何；move 偏移 rubber band；release → callback("feature_moved", dx/dy)。
    - fid 语义：镜像层 QgsFeature id 与文档 feature_id 的映射——镜像 upsert 时把文档 feature_id 写进 QgsFeature attribute（M2 镜像已带属性；若 feature_id 不在属性里，Task 内补一列 `__pwb_fid` 隐藏属性）。
- Python 侧 canvas_shim：`vertex_moved` → `session.set_vertex(feature_id, vertex_index, (x,y))`；`feature_moved` → `session.move_feature(feature_id, dx, dy)`；`pick_miss` → 不变更。

- [x] **Step 1: 写失败测试**（QTest 鼠标 press/move/release 序列驱动两工具；断言回调 payload 与 session 应用后文档几何变化——session 部分用 canvas_shim 层集成测试或直接桥级测试断言回调 JSON）

- [x] **Step 2: 运行确认失败**

- [x] **Step 3: 实现**（edit_tools.hpp/.cpp + 绑定 + shim 接线）

- [x] **Step 4: 运行确认通过**

- [x] **Step 5: 回归**（test_qgis_vertex_move_tools.py + test_map_tools.py + test_vector_edit_session.py + test_composite_editing.py）

- [x] **Step 6: 提交** `m3(bridge): vertex/move edit tools with Python-authoritative writes`

---

### Task 4: 原生选择/identify 工具 + 选中高亮

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（选集回写）
- Test: `tests/test_qgis_select_identify.py`（新建）

**Interfaces:**
- Produces:
  - `set_map_tool` kind：`"select"|"identify"`
  - `set_selection_callback(canvas, callback)`：`callback(selection_json)`——`{"layer_doc_id": str, "feature_ids": [str]}`（QgsMapToolSelect 释放后取命中要素；identify 单要素同名回调）
  - `highlight_features(canvas, layer_doc_id, feature_ids_json) -> None` / `clear_highlights(canvas) -> None`（QgsRubberBand 选中高亮——QGIS 桌面选中色，画布刷新时重画；Python 选集是权威，高亮只是投影）
- Python 侧：selection 回调 → controller 既有选集 API（composite_editing 选集状态）；选集变更（含表格/树侧选）→ `highlight_features` 投影。旧 Python 选择工具的命中逻辑在 QGIS 模式下退役（类保留供非 QGIS 路径）。

- [x] **Step 1: 写失败测试** → **Step 2: 确认失败** → **Step 3: 实现** → **Step 4: 通过** → **Step 5: 回归** → **Step 6: 提交** `m3(bridge): native select/identify tools + rubber band highlight`

---

### Task 5: 键盘路径归一 + 工具条状态同步

**Files:**
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（Esc 路径）
- Modify: `paleo_workbench/ui/map_action_controller.py`（状态回流，若需）
- Test: `tests/test_qgis_editing_keyboard.py`（新建）

**要点:**
- Esc 双路径归一：QGIS 采点中 Esc 由原生工具消费（digitizingCanceled，Task 2 已测）；**非采点态** Esc 走既有 QAction 快捷键 → cancel_active_tool。保证两件事：① 采点中 Esc 不触发 cancel_active_tool（工具自己吃掉按键——QAction 是 WindowShortcut，画布内 Esc 先到工具 keyPressEvent，验证不双触发）；② 原生工具 canceled 后 Python 工具条状态回落（action_state 刷新，互斥动作组不卡死）。
- Backspace/Delete：采点中删上一顶点由原生链处理（Task 1 的 cadDock 已满足 assert）；非采点态 Delete 删选中要素走既有 Python 命令路径（不动）。
- Ctrl+Z/Ctrl+Shift+Z：仍落 Python undo 栈（map_action_controller :88-96 不动）；**确认原生工具不使用 QGIS edit buffer**（无意外 QUndoStack 分叉）。
- 测试：采点中按 Esc → digitizingCanceled 回调一次且 cancel_active_tool 未被调用；采点完成/取消后 action_state 与工具条勾选态一致。

- [x] **Step 1-6**（同前 TDD 节奏）→ 提交 `m3(editing): unify keyboard paths and toolbar state with native tools`

---

### Task 6: M2 移交项

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（screen_to_map :738-741 int 截断 → QPointF 不截断）
- Modify: `paleo_workbench/ui/qgis_stack/`（zoom_to_layer 语义归一、✏ 编辑标记视觉、图层名过滤框（候选）、snap 菜单勾选态）
- Test: 视各项补进既有测试文件

- [x] screen_to_map 返回浮点不截断（读 map_stack_service.cpp:738-741 现状，改 QPointF 经 toMapCoordinates 直接回 double 对）+ 精度回归测试
- [x] zoom_to_layer 语义归一（与 QGIS「缩放至图层」一致：含空图层回退全图）
- [x] ✏ 编辑标记视觉（树节点或工具条上标出活动编辑会话图层）
- [x] （候选）图层名过滤框；snap 菜单勾选态持久

→ 提交 `m3(polish): M2 handover items`

---

### Task 7: 收尾（全量回归 + 文档 + 终局审查 + 合并 + 真机验收）

- [x] **Step 1: 全量回归对账**

Run: `run_env.sh tests/ -q --basetemp=$(mktemp -d) --deselect tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`
与 M2 终局基线（51F/3E 预存环境性 + flake 清单）逐条对账，零新增红才放行。

- [x] **Step 2: 文档**——更新 `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md` 的 M3 状态；更新 AGENTS.md 涉及部分（若有）。

- [x] **Step 3: 终局审查**——派 coder subagent 审查全分支 diff（M2 模式：C/I/M 分级，With fixes 才放行）。

- [x] **Step 4: 合并回 main + 删功能分支 + 清临时 worktree**（fast-forward 优先）。

- [x] **Step 5: 真机验收**——启动应用（命令见下），用户操作确认采点/顶点/移动/选择/捕捉/undo 全链。

启动命令：
```bash
cd /home/kevin/projects/paleo_project/main && \
M=/home/kevin/projects/paleo_project/main; \
PYTHONPATH="$M:$M/geo-viz-engine:$(echo $M/geo-viz-engine/packages/* | tr ' ' ':'):$M/well-log-engine" \
/opt/miniconda3/bin/python3.13 -m paleo_workbench.main
```
