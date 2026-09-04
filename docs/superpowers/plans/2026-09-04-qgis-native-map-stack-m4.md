# QGIS 原生地图栈 M4（只读页真画布 + 自有 QgsProject）实施计划

> **Status: COMPLETE** — merged to main at `629ba15a`。checkbox 未回写，as-built 以 git log 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先合上 M3 真机回归（工具包装 / cadDock hide），再让首页、工区图、编图预览在桥可用时嵌入真 `QgsMapCanvas`；每页自有 `QgsProject`，只读（pan/zoom + 单击），不与综合编修的 `QgsProject::instance()` 抢层。无桥时工厂回落 `UnifiedMapCanvas`。

**Architecture:** `QgisMapStack::initialize(display=False)` 保持编修路径（`project()` → `QgsProject::instance()`）。`initialize(display=True)` 构造 `owned_project`，`createCanvas` 调用 `canvas->setProject(owned)`，不建 tree bridge / cadDock；镜像 upsert 后 `canvas->setLayers`。Python `QgisDisplayCanvas` + `create_display_canvas()` 对接三页既有 `set_layer_snapshot` / `map_clicked` / overlay 契约。

**Tech Stack:** PySide6 (Qt6), pybind11, vendored QGIS 4.2, shiboken6, pytest + pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m4-design.md`

---

## Global Constraints

- 不依赖系统 QGIS；vendored 构建在 `native/qgis_render_bridge/build/qgis-vendor/output`。
- 不向 sip/PyQt6 迁移。控件以 `uintptr_t` 过桥。
- `map_stack_service.cpp` 禁止 pybind11 / Python.h；GIL 只在 `bindings.cpp`。
- 回调销毁走孤儿坟场（`destroyed` 里不得拆含 `py::function` 的 `std::function`）。
- 编修栈 API/语义不得破坏：`initialize()` 无参 = 现在的行为。
- 重建：`cd /home/kevin/projects/paleo_project/main && PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation`
- 测试：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args> -q --basetemp=$(mktemp -d)`。全量须 `--deselect tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`。看 `N passed/failed`，不看管道退出码。
- 工作区 `/home/kevin/projects/paleo_project/main`；功能分支 `feat/qgis-native-map-stack-m4`，合回 main 后删分支。
- **绝不提交** `.superpowers/`、`*_styles.db`、`symbology-style.db`、`user-history.db`。
- 不拆 fallback、不写 QgsProject XML、不改 `MapEditView`、不修 QGIS CI 专轨。

## 文件地图

| 路径 | 职责 |
|---|---|
| `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp` | `initialize(display)`、`project()`、display `createCanvas`、`syncCanvasLayers`、`canvasLayerCount` |
| `native/qgis_render_bridge/src/bindings.cpp` | `initialize(display=False)`、`canvas_layer_count` |
| `paleo_workbench/ui/qgis_stack/mirror.py` | 从 shim 抽出的 `mirror_snapshot_to_stack` |
| `paleo_workbench/ui/qgis_stack/display_canvas.py` | `QgisDisplayCanvas`、`create_display_canvas` |
| `paleo_workbench/ui/qgis_stack/canvas_shim.py` | Task 1 工具包装；镜像改调 `mirror.py` |
| `paleo_workbench/ui/pages/home_page.py` | 工厂换画布 |
| `paleo_workbench/ui/pages/workarea_map_widget.py` | 工厂换画布 |
| `paleo_workbench/ui/pages/mapping_page.py` | 仅预览画布走工厂；`MapEditView` 不动 |
| `tests/test_qgis_tool_wiring.py` | Task 1 |
| `tests/test_qgis_display_isolation.py` | Task 2 |
| `tests/test_qgis_display_canvas.py` | Task 3 |
| `README.md` / `CLAUDE.md` | Task 5 文档 |

## 已核实事实（执行时直接采信）

- `QgsMapCanvas::setProject(QgsProject*)` 在 `third_party/qgis/src/gui/qgsmapcanvas.h:477`。
- `map_stack_service.cpp` 有 52 处 `QgsProject::instance()`；全部改为 `project()`。
- 每个 `QgisCanvasShim` 自己 `QgisMapStack()` + `initialize()`；`shutdown` 按 `owned_layers` 从 `project()` 删层。共享 `instance()` 时只读页和编修会互删。
- `QgisCanvasShim` 无 `map_clicked`；`set_overlay_provider` 存而不画。
- `attach_canvas` 传 `self.tools`（`composite_editing.py:453`）。工作树已有包装修复和 cadDock `hide()`，未提交。
- `paint_map_decorations` 已是 `unified_map_canvas.py` 的公开函数。
- `mapping_page` 的 `unified_canvas` 目前挂了 `set_map_tool_controller`；QGIS 只读预览不再挂；fallback 的 `UnifiedMapCanvas` 仍可挂。

---

### Task 1: M3 真机回归（工具包装 + cadDock hide）

**Files:**
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（`set_map_tool_controller`）
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（`createCanvas` cadDock）
- Test: `tests/test_qgis_tool_wiring.py`（工作树已有；若缺失按下述写入）

- [ ] **Step 1: 建分支**

```bash
cd /home/kevin/projects/paleo_project/main
git checkout -b feat/qgis-native-map-stack-m4
```

- [ ] **Step 2: 确认测试文件存在**

`tests/test_qgis_tool_wiring.py` 必须含 `test_shim_maps_tool_ids_to_native_kinds` 与 `test_cad_dock_stays_hidden`（见工作树版本）。若被清掉，从 git stash / 本计划仓库工作树恢复，不要重写不同断言。

- [ ] **Step 3: shim 接直传工具栈**

`set_map_tool_controller` 里把 `tools = getattr(controller, "tools", None)` 换成：

```python
if hasattr(controller, "set_active_tool"):
    tools = controller
else:
    tools = getattr(controller, "tools", None)
```

Docstring 写明：`attach_canvas` 直传 `MapToolController`，只认 `.tools` 时包装不装、真机永远 pan。

- [ ] **Step 4: cadDock 构造后 hide**

`createCanvas` 里：

```cpp
auto* cadDock = new QgsAdvancedDigitizingDockWidget(canvas, canvas);
cadDock->hide();
impl_->cad_docks[addr] = cadDock;
```

- [ ] **Step 5: 重建桥并跑测试**

```bash
cd /home/kevin/projects/paleo_project/main && \
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation && \
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_tool_wiring.py tests/test_qgis_digitize_tool.py tests/test_composite_qgis_canvas.py \
  -q --basetemp=$(mktemp -d)
```

Expected: 相关 passed，0 failed。

- [ ] **Step 6: 提交**

```bash
git add paleo_workbench/ui/qgis_stack/canvas_shim.py \
        native/qgis_render_bridge/src/map_stack_service.cpp \
        tests/test_qgis_tool_wiring.py
git commit -m "$(cat <<'EOF'
m3(fix): 真机回归——工具栈直传接线 + cadDock 显式 hide

attach_canvas 传 MapToolController 本体，shim 只认 .tools 时包装不装。
QDockWidget 子控件随父 show 递归显示，构造后 hide。
EOF
)"
```

不要 add `*.db` / `.superpowers/`。

---

### Task 2: C++ display 模式（自有 QgsProject + 隔离）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp`
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Test: `tests/test_qgis_display_isolation.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_qgis_display_isolation.py`：

```python
# -*- coding: utf-8 -*-
"""M4: display 栈自有 QgsProject，不写入编修单例。"""
import json

import pytest

pytest.importorskip("PySide6")

_GEOJSON = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
         "properties": {"name": "P"}}
    ],
})


@pytest.fixture()
def qapp_ok(qapp):
    return qapp


def _show(qtbot, addr):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    w = wrapInstance(addr, QWidget)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    return w


def test_initialize_display_kwarg_exists(qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack
    s = QgisMapStack()
    s.initialize(display=True)
    try:
        assert s.initialized
    finally:
        s.shutdown()


def test_display_upsert_does_not_change_authoring_count(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    authoring = QgisMapStack()
    authoring.initialize()
    display = QgisMapStack()
    display.initialize(display=True)
    try:
        before = authoring.project_layer_count()
        canvas = display.create_canvas()
        _show(qtbot, canvas)
        display.upsert_mirror_layer(
            "home_workarea:wells", "wells", "Point", "EPSG:4326",
            _GEOJSON, "", "", "", True, 1.0,
        )
        assert display.project_layer_count() == 1
        assert display.canvas_layer_count(canvas) == 1
        assert authoring.project_layer_count() == before
    finally:
        display.shutdown()
        authoring.shutdown()


def test_two_display_stacks_do_not_share_layers(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    a = QgisMapStack()
    a.initialize(display=True)
    b = QgisMapStack()
    b.initialize(display=True)
    try:
        ca = a.create_canvas()
        cb = b.create_canvas()
        _show(qtbot, ca)
        _show(qtbot, cb)
        a.upsert_mirror_layer(
            "a:wells", "A", "Point", "EPSG:4326", _GEOJSON, "", "", "", True, 1.0,
        )
        assert a.project_layer_count() == 1
        assert b.project_layer_count() == 0
        assert a.canvas_layer_count(ca) == 1
        assert b.canvas_layer_count(cb) == 0
    finally:
        a.shutdown()
        b.shutdown()


def test_display_create_layer_tree_view_raises(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        with pytest.raises(RuntimeError, match="display"):
            s.create_layer_tree_view(canvas)
    finally:
        s.shutdown()


def test_display_rejects_edit_map_tools(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        s.set_map_tool(canvas, "pan")
        with pytest.raises(RuntimeError, match="display"):
            s.set_map_tool(canvas, "addPoint")
    finally:
        s.shutdown()


def test_display_canvas_has_no_cad_dock(qtbot, qapp_ok):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        w = wrapInstance(canvas, QWidget)
        qtbot.addWidget(w)
        w.resize(400, 400)
        w.show()
        dock = next(
            (c for c in w.children()
             if c.metaObject().className() == "QgsAdvancedDigitizingDockWidget"),
            None,
        )
        assert dock is None
    finally:
        s.shutdown()
```

- [ ] **Step 2: 跑确认失败**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_display_isolation.py -v --basetemp=$(mktemp -d)
```

Expected: FAIL（`initialize() got an unexpected keyword argument 'display'` 或 `canvas_layer_count` 不存在）。

- [ ] **Step 3: 头文件**

`map_stack_service.hpp` 把 `void initialize();` 换成：

```cpp
void initialize(bool display = false);
bool isDisplay() const noexcept;
int canvasLayerCount(std::uintptr_t canvas) const;
```

在 `QgisMapStack` 的 private 区增加（若尚无 `Impl` 前向已够用，不必把 `project()` 放进 public）：

```cpp
private:
  class Impl;
  QgsProject* project() const;
  void syncCanvasLayers(std::uintptr_t canvas);
```

需要在头里前向声明 `class QgsProject;`。

- [ ] **Step 4: Impl + project() + initialize**

`Impl` 增加：

```cpp
bool display_mode = false;
std::unique_ptr<QgsProject> owned_project;
```

```cpp
QgsProject* QgisMapStack::project() const {
  if (impl_->owned_project) return impl_->owned_project.get();
  return QgsProject::instance();
}

bool QgisMapStack::isDisplay() const noexcept {
  return impl_ && impl_->display_mode;
}

void QgisMapStack::initialize(bool display) {
  if (impl_->initialized) return;
  if (QCoreApplication::instance() == nullptr) {
    throw std::runtime_error("QgisMapStack requires an existing Qt application");
  }
  if (PALEO_QGIS_PREFIX_PATH.empty()) {
    throw std::runtime_error("vendored QGIS prefix is not configured");
  }
  std::lock_guard<std::mutex> lock(g_qgis_lifecycle_mutex);
  QgsApplication::setPrefixPath(
      QString::fromStdString(PALEO_QGIS_PREFIX_PATH), true);
  QgsApplication::init();
  QgsApplication::initQgis();
  if (display) {
    impl_->owned_project = std::make_unique<QgsProject>();
    impl_->display_mode = true;
  }
  impl_->initialized = true;
}
```

把本文件全部 `QgsProject::instance()` 换成 `project()`（52 处，含 `shutdown` 删层循环、`upsertMirrorLayer` 的 `addMapLayer`、`createLayerTreeView` 的 root、`QgsCoordinateTransform(..., project())`）。

- [ ] **Step 5: syncCanvasLayers + display createCanvas**

```cpp
void QgisMapStack::syncCanvasLayers(std::uintptr_t canvas_addr) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  auto bit = impl_->tree_bridges.find(canvas_addr);
  if (bit != impl_->tree_bridges.end() && bit->second) {
    bit->second->setCanvasLayers();
    return;
  }
  QList<QgsMapLayer*> layers;
  QgsProject* prj = project();
  if (prj != nullptr) {
    const QList<QgsMapLayer*> order = prj->layerTreeRoot()->layerOrder();
    for (QgsMapLayer* layer : order) {
      if (layer != nullptr) layers.append(layer);
    }
  }
  canvas->setLayers(layers);
}

int QgisMapStack::canvasLayerCount(std::uintptr_t canvas_addr) const {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  return static_cast<int>(canvas->layers().size());
}
```

所有 `for (auto& kv : impl_->tree_bridges) { if (kv.second) kv.second->setCanvasLayers(); }` 改为：

```cpp
for (auto& kv : impl_->canvas_refs) {
  if (!kv.second.isNull()) syncCanvasLayers(kv.first);
}
```

`createCanvas`：

```cpp
std::uintptr_t QgisMapStack::createCanvas() {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  auto* canvas = new QgsMapCanvas();
  canvas->setCanvasColor(Qt::white);
  canvas->enableAntiAliasing(true);
  if (impl_->display_mode) {
    canvas->setProject(project());
  } else {
    auto tree_bridge = std::make_unique<QgsLayerTreeMapCanvasBridge>(
        project()->layerTreeRoot(), canvas);
    tree_bridge->setCanvasLayers();
    std::uintptr_t addr = reinterpret_cast<std::uintptr_t>(canvas);
    impl_->tree_bridges.emplace(addr, std::move(tree_bridge));
    impl_->canvas_refs[addr] = canvas;
    auto* cadDock = new QgsAdvancedDigitizingDockWidget(canvas, canvas);
    cadDock->hide();
    impl_->cad_docks[addr] = cadDock;
    impl_->dead_canvas_addrs.erase(addr);
    return addr;
  }
  std::uintptr_t addr = reinterpret_cast<std::uintptr_t>(canvas);
  impl_->canvas_refs[addr] = canvas;
  impl_->dead_canvas_addrs.erase(addr);
  canvas->setMapTool(new QgsMapToolPan(canvas));
  return addr;
}
```

`createLayerTreeView` 开头：

```cpp
if (impl_->display_mode) {
  throw std::runtime_error("display map stack has no layer tree");
}
```

`setMapTool` 在处理 addPoint/vertex/select 之前：

```cpp
if (impl_->display_mode) {
  if (kind != "pan" && kind != "zoomIn" && kind != "zoomOut") {
    throw std::runtime_error("display map stack does not host edit tools");
  }
}
```

`shutdown` 在现有删 `owned_layers` 之后（已走 `project()`）：

```cpp
if (impl_->owned_project) {
  impl_->owned_project->removeAllMapLayers();
  impl_->owned_project.reset();
}
impl_->display_mode = false;
```

不得对 `QgsProject::instance()` 做 `removeAllMapLayers`。

- [ ] **Step 6: 绑定**

`bindings.cpp` 把 initialize 换成：

```cpp
.def("initialize", &pwb::qgis_render::QgisMapStack::initialize,
     py::arg("display") = false)
.def("canvas_layer_count", &pwb::qgis_render::QgisMapStack::canvasLayerCount)
```

- [ ] **Step 7: 重建 + 测试**

```bash
cd /home/kevin/projects/paleo_project/main && \
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation && \
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_display_isolation.py tests/test_qgis_canvas_embed.py \
  tests/test_qgis_layertree_embed.py tests/test_qgis_digitize_tool.py \
  tests/test_qgis_tool_wiring.py \
  -q --basetemp=$(mktemp -d)
```

Expected: 全绿（编修测试证明无参 `initialize()` 仍走单例）。

- [ ] **Step 8: 提交**

```bash
git add native/qgis_render_bridge/src/map_stack_service.hpp \
        native/qgis_render_bridge/src/map_stack_service.cpp \
        native/qgis_render_bridge/src/bindings.cpp \
        tests/test_qgis_display_isolation.py
git commit -m "$(cat <<'EOF'
m4(bridge): display 栈自有 QgsProject，与编修 instance() 隔离

initialize(display=True) 不建 tree bridge/cadDock；镜像只写入 owned project。
EOF
)"
```

---

### Task 3: QgisDisplayCanvas + 镜像抽取 + 单击/叠加层

**Files:**
- Create: `paleo_workbench/ui/qgis_stack/mirror.py`
- Create: `paleo_workbench/ui/qgis_stack/display_canvas.py`
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（`set_layer_snapshot` 改调 mirror）
- Modify: `paleo_workbench/ui/qgis_stack/__init__.py`
- Test: `tests/test_qgis_display_canvas.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_qgis_display_canvas.py`：

```python
# -*- coding: utf-8 -*-
"""M4: QgisDisplayCanvas 快照镜像、单击、工厂回落。"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
import pytest

pytest.importorskip("PySide6")


def _point_snapshot():
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot,
    )
    layer = MapLayerSnapshot(
        id="home_workarea:wells",
        name="wells",
        layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(
            {"id": "w1", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
             "properties": {"well_id": "A12"}},
        ),
        style={"stroke": "#409cff"},
        visible=True,
        opacity=1.0,
    )
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))


def _click(widget, pos: QPointF):
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
    QApplication.sendEvent(widget, press)
    QApplication.sendEvent(widget, release)


def test_display_canvas_mirrors_snapshot_and_click(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    canvas = QgisDisplayCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 400)
    canvas.show()
    canvas.set_layer_snapshot(_point_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.wait(50)
    assert canvas.stack.canvas_layer_count(canvas.canvas_address) == 1

    seen = []
    canvas.map_clicked.connect(seen.append)
    target = canvas.canvas
    _click(target, QPointF(200, 200))
    qtbot.wait(50)
    assert len(seen) == 1
    assert seen[0][0] == pytest.approx(5.0, abs=1.5)
    assert seen[0][1] == pytest.approx(5.0, abs=1.5)


def test_display_canvas_drag_does_not_click(qtbot, qapp):
    from PySide6.QtWidgets import QApplication
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    canvas = QgisDisplayCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 400)
    canvas.show()
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    seen = []
    canvas.map_clicked.connect(seen.append)
    target = canvas.canvas
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(80, 80),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove, QPointF(180, 160),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(180, 160),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, press)
    QApplication.sendEvent(target, move)
    QApplication.sendEvent(target, release)
    qtbot.wait(50)
    assert seen == []


def test_create_display_canvas_returns_qgis_when_bridge_present(qapp):
    from paleo_workbench.ui.qgis_stack.display_canvas import (
        QgisDisplayCanvas, create_display_canvas,
    )
    w = create_display_canvas()
    assert isinstance(w, QgisDisplayCanvas)
    w.shutdown()


def test_shim_and_display_share_mirror_helper(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        addr = s.create_canvas()
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(addr, QWidget)
        qtbot.addWidget(w)
        w.resize(200, 200)
        w.show()
        qgis_ids, doc_ids = mirror_snapshot_to_stack(s, addr, _point_snapshot())
        assert doc_ids == ["home_workarea:wells"]
        assert s.canvas_layer_count(addr) == 1
        assert qgis_ids
    finally:
        s.shutdown()
```

- [ ] **Step 2: 跑确认失败**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_display_canvas.py -v --basetemp=$(mktemp -d)
```

Expected: FAIL（`display_canvas` 无法导入）。

- [ ] **Step 3: 抽 `mirror.py`**

把 `QgisCanvasShim.set_layer_snapshot` 的镜像循环（CRS、GeoJSON、style、`upsert_mirror_layer`、`remove_mirror_layers_except`、`set_mirror_layer_order`、`refresh_canvas`）原样移到：

```python
# paleo_workbench/ui/qgis_stack/mirror.py
def mirror_snapshot_to_stack(stack, canvas_address, snapshot) -> tuple[list[str], list[str]]:
    """Returns (mirrored_qgis_ids, seen_doc_ids)."""
```

`canvas_shim.set_layer_snapshot` 变成：调该函数，写入 `_mirrored_layers` / `_mirrored_doc_ids`。零要素上树、`qgis_style` 门控、异常语义必须与搬前逐行一致（先跑 `tests/test_qgis_mapstack_style.py tests/test_qgis_layer_panel.py` 作对照）。

几何类型映射表 `_GEOMETRY_TYPE` 跟着挪到 `mirror.py`，shim 若仍需要可从那里 import。

- [ ] **Step 4: 实现 `display_canvas.py`**

```python
# paleo_workbench/ui/qgis_stack/display_canvas.py
"""只读 QgsMapCanvas：自有 QgsProject，供首页/工区/编图预览。"""
from __future__ import annotations

import sys
import weakref

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost
from paleo_workbench.ui.unified_map_canvas import paint_map_decorations


def create_display_canvas(parent=None) -> QWidget:
    try:
        from qgis_render_bridge.mapstack import QgisMapStack  # noqa: F401
    except ImportError:
        from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
        return UnifiedMapCanvas(parent=parent)
    return QgisDisplayCanvas(parent)


class _ClickFilter(QObject):
    def __init__(self, host: "QgisDisplayCanvas") -> None:
        super().__init__(host)
        self._host = host
        self._press: QPointF | None = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press = event.position()
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
                press = self._press
                self._press = None
                if (event.position() - press).manhattanLength() < 6:
                    host = self._host
                    pos = event.position()
                    host.map_clicked.emit(host.screen_to_map((pos.x(), pos.y())))
        return False


class _Overlay(QWidget):
    def __init__(self, host: "QgisDisplayCanvas") -> None:
        super().__init__(host)
        self._host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        host = self._host
        provider = getattr(host, "_overlay_provider", None)
        if provider is None:
            return
        state = provider() or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = tuple(state.get("selected_features") or ())
        if selected:
            painter.setPen(QPen(QColor("#ffe066"), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for feature in selected:
                geometry = feature.get("geometry") if isinstance(feature, dict) else getattr(feature, "geometry", None)
                if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                    continue
                coords = geometry.get("coordinates") or ()
                if len(coords) < 2:
                    continue
                sx, sy = host.map_to_screen((float(coords[0]), float(coords[1])))
                painter.drawEllipse(QPointF(sx, sy), 8.0, 8.0)
        decorations = state.get("decorations") or {}
        if decorations:
            paint_map_decorations(
                painter, decorations,
                width=self.width(), height=self.height(),
                extent=host.view_extent, dark_chrome=False,
            )
        painter.end()


class QgisDisplayCanvas(QWidget):
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    backend_status_changed = Signal(str)
    map_clicked = Signal(tuple)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from qgis_render_bridge.mapstack import QgisMapStack

        self.stack = QgisMapStack()
        self.stack.initialize(display=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._host = QgisCanvasHost(self.stack, self)
        layout.addWidget(self._host)
        self.canvas = self._host.canvas
        self.canvas_address = self._host.canvas_address
        self._overlay_provider = None
        self._shutdown_done = False
        self._extent_history = [(0.0, 0.0, 1.0, 1.0)]
        self._extent_history_index = 0
        self.events = StackEvents(self)
        self.events.attach(self.stack, self.canvas_address)
        self.events.extent_changed.connect(self._on_stack_extent)
        self._overlay = _Overlay(self)
        self._filter = _ClickFilter(self)
        self.canvas.installEventFilter(self._filter)
        self.stack.set_map_tool(self.canvas_address, "pan")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _on_stack_extent(self, xmin, ymin, xmax, ymax) -> None:
        tup = (float(xmin), float(ymin), float(xmax), float(ymax))
        self.extent_changed.emit(tup)

    @property
    def view_extent(self):
        try:
            return tuple(self.stack.canvas_extent(self.canvas_address))
        except Exception:
            return self._extent_history[self._extent_history_index]

    def set_extent(self, extent, *, record_history: bool = True, coalesce_history: bool = False) -> None:
        tup = tuple(float(v) for v in extent)
        self.stack.set_canvas_extent(self.canvas_address, *tup)

    def set_layer_snapshot(self, snapshot) -> None:
        if self._shutdown_done:
            return
        mirror_snapshot_to_stack(self.stack, self.canvas_address, snapshot)
        self._overlay.update()

    def map_to_screen(self, point):
        return tuple(self.stack.map_to_screen(self.canvas_address, float(point[0]), float(point[1])))

    def screen_to_map(self, point):
        return tuple(self.stack.screen_to_map(self.canvas_address, float(point[0]), float(point[1])))

    def set_overlay_provider(self, provider) -> None:
        self._overlay_provider = provider
        self._overlay.update()

    def update(self) -> None:  # noqa: A003
        super().update()
        self._overlay.update()

    @property
    def backend_status(self) -> str:
        return "qgis"

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self.stack.shutdown()
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)
```

`__init__.py` 导出 `create_display_canvas`、`QgisDisplayCanvas`。

- [ ] **Step 5: 跑测试**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_display_canvas.py tests/test_qgis_mapstack_style.py \
  tests/test_qgis_layer_panel.py tests/test_qgis_display_isolation.py \
  -q --basetemp=$(mktemp -d)
```

Expected: 全绿。若单击不触发：event filter 装在 `self.canvas`（wrap 后的 `QgsMapCanvas`），用 `QApplication.sendEvent` 而不是调 `mousePressEvent`（原生工具不走 QWidget 虚函数）。

- [ ] **Step 6: 提交**

```bash
git add paleo_workbench/ui/qgis_stack/mirror.py \
        paleo_workbench/ui/qgis_stack/display_canvas.py \
        paleo_workbench/ui/qgis_stack/canvas_shim.py \
        paleo_workbench/ui/qgis_stack/__init__.py \
        tests/test_qgis_display_canvas.py
git commit -m "$(cat <<'EOF'
m4(ui): QgisDisplayCanvas——只读真画布 + 快照镜像 + map_clicked

镜像循环与 shim 共用 mirror.py。无桥工厂回落 UnifiedMapCanvas。
EOF
)"
```

---

### Task 4: 三页替换

**Files:**
- Modify: `paleo_workbench/ui/pages/home_page.py`
- Modify: `paleo_workbench/ui/pages/workarea_map_widget.py`
- Modify: `paleo_workbench/ui/pages/mapping_page.py`
- Test: `tests/test_home_map_well_click.py`（保留 UnifiedMapCanvas 单测；加 HomePage 工厂路径）

- [ ] **Step 1: 写失败测试（HomePage 画布类型）**

在 `tests/test_home_map_well_click.py` 末尾追加：

```python
def test_home_page_uses_display_canvas_when_bridge_present(qtbot, qapp):
    from paleo_workbench.ui.pages.home_page import HomePage
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    page = HomePage()
    qtbot.addWidget(page)
    assert isinstance(page.map_canvas, QgisDisplayCanvas)
```

- [ ] **Step 2: 跑确认失败**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_home_map_well_click.py::test_home_page_uses_display_canvas_when_bridge_present \
  -v --basetemp=$(mktemp -d)
```

Expected: FAIL（`map_canvas` 仍是 `UnifiedMapCanvas`）。

- [ ] **Step 3: 换三页**

`home_page.py`：

```python
from paleo_workbench.ui.qgis_stack.display_canvas import create_display_canvas
# 删除 UnifiedMapCanvas import（若无其它引用）
self.map_canvas = create_display_canvas()
```

`workarea_map_widget.py`：同样 `self.map_canvas = create_display_canvas(parent=self)`。模块 docstring 把「UnifiedMapCanvas」改成「create_display_canvas（桥可用为 QgsMapCanvas）」。

`mapping_page.py` 只改预览：

```python
from paleo_workbench.ui.qgis_stack.display_canvas import create_display_canvas

self.unified_canvas = create_display_canvas()
if hasattr(self.unified_canvas, "set_map_tool_controller"):
    self.unified_canvas.set_map_tool_controller(self._map_tools)
self.unified_canvas.set_overlay_provider(self._unified_overlay_state)
```

`MapEditView` / `MapCanvasPanel` / 组图面板一行不改。QGIS 预览是只读（没有 `set_map_tool_controller`）；fallback 预览仍可编辑。

- [ ] **Step 4: 跑页面测试**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_home_map_well_click.py tests/test_qgis_display_canvas.py \
  tests/test_qgis_display_isolation.py tests/test_composite_qgis_canvas.py \
  tests/test_qgis_layer_panel.py \
  -q --basetemp=$(mktemp -d)
```

Expected: 全绿。`test_home_map_well_click` 里直接构造 `UnifiedMapCanvas()` 的单击单测保持原样（不改生产页依赖）。

若 HomePage 井点击在 display 路径失败：确认 `map_clicked` 从原生 canvas 滤出，且 `HomePage._on_map_clicked` 仍连在 `self.map_canvas.map_clicked`。

- [ ] **Step 5: 提交**

```bash
git add paleo_workbench/ui/pages/home_page.py \
        paleo_workbench/ui/pages/workarea_map_widget.py \
        paleo_workbench/ui/pages/mapping_page.py \
        tests/test_home_map_well_click.py
git commit -m "$(cat <<'EOF'
m4(ui): 首页/工区图/编图预览经工厂嵌入只读 QgsMapCanvas

无桥仍回落 UnifiedMapCanvas。MapEditView 不动。
EOF
)"
```

---

### Task 5: 文档 + 编修回归

**Files:**
- Modify: `README.md`（QGIS 原生地图栈节）
- Modify: `CLAUDE.md`（地图栈段）
- Modify: `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`（若 M4 行尚未改）

- [ ] **Step 1: README / CLAUDE**

把「其余页面仍走 UnifiedMapCanvas + fallback」改成：

> M4 起首页 / 工区图 / 编图预览在桥可用时也嵌入只读 `QgsMapCanvas`（自有 `QgsProject`，与综合编修隔离）。无桥或主 CI 仍走 `UnifiedMapCanvas` + fallback。综合编修继续硬依赖桥。fallback 拆除与工程文件 QgsProject XML 不在本切片。

- [ ] **Step 2: 编修 + 只读回归**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_qgis_tool_wiring.py tests/test_qgis_display_isolation.py \
  tests/test_qgis_display_canvas.py tests/test_home_map_well_click.py \
  tests/test_qgis_canvas_embed.py tests/test_qgis_layertree_embed.py \
  tests/test_qgis_digitize_tool.py tests/test_qgis_vertex_move_tools.py \
  tests/test_qgis_select_identify.py tests/test_qgis_editing_keyboard.py \
  tests/test_qgis_layer_panel.py tests/test_qgis_layer_panel_menu.py \
  tests/test_qgis_mapstack_style.py tests/test_composite_qgis_canvas.py \
  tests/test_composite_editing.py tests/test_composite_gis.py \
  -q --basetemp=$(mktemp -d)
```

Expected: 无新增红。预存环境性（缺 `layer_model_core` / `grid_render_core`）可忽略。

- [ ] **Step 3: 提交文档**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md \
        docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m4-design.md \
        docs/superpowers/plans/2026-09-04-qgis-native-map-stack-m4.md
git commit -m "docs(qgis): M4 只读页真画布状态"
```

- [ ] **Step 4: 合回 main（本切片做完、审查通过后）**

```bash
git checkout main
git merge --ff-only feat/qgis-native-map-stack-m4
git branch -d feat/qgis-native-map-stack-m4
```

真机验收：启动应用（M3 计划里的 PYTHONPATH 命令），确认首页工区图是 QGIS 画布、点井仍跳转、综合编修采点仍可用、两页图层不串。

---

## Spec coverage（自检）

| Spec 条目 | Task |
|---|---|
| Task 0 真机回归 | Task 1 |
| `initialize(display)` + `project()` + 52 处 instance 替换 | Task 2 |
| display 不建 tree/cadDock；误调抛错 | Task 2 |
| 两 display 栈 + 编修 count 隔离 | Task 2 |
| `QgisDisplayCanvas` / 工厂 | Task 3 |
| `map_clicked` 阈值 6px | Task 3 |
| overlay 鼠标穿透 + 装饰/选中井 | Task 3 |
| `mirror.py` 共用 | Task 3 |
| 三页替换；MapEditView 不动 | Task 4 |
| 无桥回落 | Task 3 工厂 |
| README/CLAUDE | Task 5 |
| 不拆 fallback / 不写 XML / 不改编修 instance() | 全局约束 |

无 TBD/TODO。`canvas_layer_count` / `initialize(display=True)` / `create_display_canvas` 在后续任务中的名字与 Task 2/3 定义一致。
