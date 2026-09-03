# QGIS 原生地图栈 M1（地基：桥骨架 + QgsMapCanvas 嵌入）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 vendored QGIS 4.2 的 `QgsMapCanvas` 嵌入工作站综合编修文档区，图层经 `QgsProject` 镜像显示，原生 pan/zoom 可用——M1 可演示。

**Architecture:** 扩展 `native/qgis_render_bridge`（pybind11）新增 `mapstack` 子模块：C++ 创建/持有 `QgsMapCanvas` 与 `QgsProject` 镜像图层，QWidget 指针以 `uintptr_t` 返回；Python 侧 `paleo_workbench/ui/qgis_stack/` 包用 `shiboken6.wrapInstance` 嵌入 PySide6 布局，桥回调经 `QTimer.singleShot(0, …)` marshal 成 Qt Signal。综合编修区经兼容 shim（`QgisCanvasHost` 实现 `UnifiedMapCanvas` 的被用子集）替换旧画布。

**Tech Stack:** PySide6 (Qt6), pybind11, vendored QGIS 4.2 (`third_party/qgis`), shiboken6, pytest + pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`（M2–M4 计划待 M1 落地后编写）

## Global Constraints

- 硬依赖：不依赖系统 QGIS；只允许使用 vendored 构建（`native/qgis_render_bridge/build/qgis-vendor/output`）。
- 不向 QGIS 官方 Python 绑定（sip/PyQt6）迁移；进程内只有 PySide6 一套绑定运行时。
- C++ 边界：**No QWidget crosses the boundary as a typed object**——控件以 `uintptr_t` 地址传递，Python 侧只经 `shiboken6.wrapInstance` 还原。
- 运行 Python 为 `/opt/miniconda3/bin/python3.13`（仓库残留 `*.cpython-312*.so` 不可复用，必须按 3.13 重编扩展）。
- 测试一律经仓库统一入口：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args>`（offscreen、LD_PRELOAD shim、PYTHONPATH 已配好）。
- 画布底色为白色（上一轮用户决定）：`canvas.setCanvasColor(Qt::white)`。
- QGIS 4.2 的 GDAL/OGR provider **内置于 `qgis_core`**（`src/core/providers/{gdal,ogr}`），无需补编 provider 插件——spec §8 的 provider 项作废，Task 1 只做验证。
- 所有提交在 `/home/kevin/projects/paleo_project/main` 工作区（`main` 分支）进行。

---

### Task 1: 桥扩展按 Python 3.13 重编并安装进环境

**Files:**
- Build: `native/qgis_render_bridge/`（不修改源码，仅构建安装）
- Test: `tests/test_qgis_mapstack_env.py`（新建）

**Interfaces:**
- Produces: 可 `import qgis_render_bridge` 的当前环境；`qgis_render_bridge.__version__ == "0.2.17a0"`；`QgisRenderBridge().initialize()` 在 offscreen `QApplication` 下成功。

- [ ] **Step 1: 验证 provider 内置事实（spec 偏差确认）**

```bash
ls /home/kevin/projects/paleo_project/main/third_party/qgis/src/core/providers/ | grep -E "gdal|ogr|memory"
```
Expected: 输出 `gdal`、`memory`、`ogr` 三行（provider 已编入 qgis_core，无需改构建目标）。

- [ ] **Step 2: 安装构建依赖并重编安装桥**

```bash
/opt/miniconda3/bin/python3.13 -m pip install "pybind11>=2.12" ninja
cd /home/kevin/projects/paleo_project/main
/opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge
```
Expected: 构建复用现有 `build/qgis-vendor`（`setup.py` 检测到 `libqgis_{core,gui,analysis}.so` 与 `resources/srs.db` 齐全即跳过 QGIS 重编），只编译扩展；结尾 `Successfully installed qgis_render_bridge`。若扩展编译缺 Qt/QGIS 头文件，检查 `PALEO_QGIS_BUILD_DIR` 是否指向 `native/qgis_render_bridge/build/qgis-vendor`。

- [ ] **Step 3: 写环境冒烟测试**

```python
# tests/test_qgis_mapstack_env.py
"""M1 Task 1: vendored QGIS 桥在当前 Python 3.13 环境可用（硬依赖起点）。"""
import pytest

pytest.importorskip("PySide6")


def test_bridge_importable_and_initializes(qapp):
    import qgis_render_bridge

    assert qgis_render_bridge.__version__ == "0.2.17a0"
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    assert bridge.initialized
    assert bridge.version()  # vendored QGIS 版本串非空
    bridge.shutdown()
```

- [ ] **Step 4: 运行验证通过**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_env.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd /home/kevin/projects/paleo_project/main
git add tests/test_qgis_mapstack_env.py
git commit -m "test(qgis): M1 环境冒烟——vendored 桥 py3.13 可导入可初始化"
```

---

### Task 2: mapstack C++ 骨架（QgisMapStack 生命周期 + QgsProject 权威）

**Files:**
- Create: `native/qgis_render_bridge/src/map_stack_service.hpp`
- Create: `native/qgis_render_bridge/src/map_stack_service.cpp`
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（模块尾部追加 `mapstack` 子模块绑定）
- Test: `tests/test_qgis_mapstack_lifecycle.py`（新建）

**Interfaces:**
- Consumes: Task 1 的可导入桥。
- Produces（后续任务依赖的精确签名）:
  - `qgis_render_bridge.mapstack.QgisMapStack()` 构造器
  - `.initialize() -> None`（幂等；要求已存在 `QApplication`；复用 vendored prefix 初始化 `QgsApplication`）
  - `.initialized -> bool`（只读属性）
  - `.project_layer_count() -> int`（`QgsProject::instance()` 内图层数）
  - `.shutdown() -> None`（移除本栈加入的图层，不销毁全局 QGIS 上下文）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_mapstack_lifecycle.py
"""M1 Task 2: QgisMapStack 生命周期——初始化幂等、QgsProject 单例可达。"""
import pytest

pytest.importorskip("PySide6")


def test_mapstack_lifecycle(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    assert not stack.initialized
    stack.initialize()
    assert stack.initialized
    stack.initialize()  # 幂等：二次调用不抛异常
    assert stack.project_layer_count() == 0
    stack.shutdown()
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_lifecycle.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'qgis_render_bridge.mapstack'`（或 import 阶段 AttributeError）

- [ ] **Step 3: 实现 C++ 骨架**

```cpp
// native/qgis_render_bridge/src/map_stack_service.hpp
// 注意：本任务只落生命周期声明；Task 3/4/5 各自在类中追加自己的
// 方法声明与定义（声明/定义/绑定同一任务内落地，避免超前声明导致链接错误）。
#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace pwb::qgis_render {

// QGIS 原生地图栈：QgsProject（图层运行时权威）+ QgsMapCanvas 宿主。
// 控件一律以 uintptr_t 地址过边界（No QWidget crosses the boundary）。
class QgisMapStack {
public:
  QgisMapStack();
  ~QgisMapStack();

  void initialize();
  bool initialized() const noexcept;
  int projectLayerCount() const;
  void shutdown();

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_render
```

```cpp
// native/qgis_render_bridge/src/map_stack_service.cpp（本任务只实现生命周期，
// 其余方法先给「未实现」兜底——但不得留 TODO 注释，空实现必须抛明确异常）
#include "map_stack_service.hpp"

#include <stdexcept>

#include <QCoreApplication>

#include <qgsapplication.h>
#include <qgsproject.h>

namespace pwb::qgis_render {

// 与 qgis_render_bridge.cpp 的 initialize 同一约定：vendored prefix 由
// 构建宏 PALEO_QGIS_PREFIX_PATH 注入；初始化进程级只发生一次。
extern const std::string PALEO_QGIS_PREFIX_PATH;  // 定义于 qgis_render_bridge.cpp

struct QgisMapStack::Impl {
  bool initialized = false;
};

QgisMapStack::QgisMapStack() : impl_(std::make_unique<Impl>()) {}
QgisMapStack::~QgisMapStack() = default;

void QgisMapStack::initialize() {
  if (impl_->initialized) return;
  if (QCoreApplication::instance() == nullptr) {
    throw std::runtime_error("QgisMapStack requires an existing Qt application");
  }
  if (PALEO_QGIS_PREFIX_PATH.empty()) {
    throw std::runtime_error("vendored QGIS prefix is not configured");
  }
  // QgsApplication::init 静态幂等（内部有全局守卫，与 QgisRenderBridge 共享）。
  QgsApplication::setPrefixPath(
      QString::fromStdString(PALEO_QGIS_PREFIX_PATH), true);
  QgsApplication::init();
  QgsApplication::initQgis();
  impl_->initialized = true;
}

bool QgisMapStack::initialized() const noexcept { return impl_->initialized; }

int QgisMapStack::projectLayerCount() const {
  return static_cast<int>(QgsProject::instance()->count());
}

void QgisMapStack::shutdown() {
  // 只移除图层、保留全局 QGIS 上下文（进程内可能有多个栈实例交替）。
  QgsProject::instance()->removeAllMapLayers();
  impl_->initialized = false;
}

}  // namespace pwb::qgis_render
```

> 若 `PALEO_QGIS_PREFIX_PATH` 在 `qgis_render_bridge.cpp` 中是 static/匿名命名空间，把其定义改为 `namespace pwb::qgis_render { const std::string PALEO_QGIS_PREFIX_PATH = ...; }`（去掉 static），保持单一来源。

```cpp
// bindings.cpp 尾部追加（PYBIND11_MODULE 内，geometry 子模块之后）；
// 文件顶部追加 #include "map_stack_service.hpp"：
    auto mapstack = module.def_submodule("mapstack", "QGIS native map stack");
    py::class_<pwb::qgis_render::QgisMapStack>(mapstack, "QgisMapStack")
        .def(py::init<>())
        .def("initialize", &pwb::qgis_render::QgisMapStack::initialize)
        .def_property_readonly("initialized", &pwb::qgis_render::QgisMapStack::initialized)
        .def("project_layer_count", &pwb::qgis_render::QgisMapStack::projectLayerCount)
        .def("shutdown", &pwb::qgis_render::QgisMapStack::shutdown);
```

同时把 `map_stack_service.cpp` 加入构建：`native/qgis_render_bridge/setup.py` 的扩展 `sources` 列表追加 `str(SRC / "map_stack_service.cpp")`（找到现有 `sources=[...]` 处）。

- [ ] **Step 4: 重编扩展并运行测试**

```bash
cd /home/kevin/projects/paleo_project/main
/opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_lifecycle.py -v
```
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/map_stack_service.* native/qgis_render_bridge/src/bindings.cpp native/qgis_render_bridge/setup.py tests/test_qgis_mapstack_lifecycle.py
git commit -m "feat(qgis): mapstack 子模块骨架——QgisMapStack 生命周期与 QgsProject 权威入口"
```

---

### Task 3: QgsMapCanvas 创建 + shiboken 嵌入宿主（白底）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（实现 canvas 方法）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（追加 canvas 绑定）
- Create: `paleo_workbench/ui/qgis_stack/__init__.py`
- Create: `paleo_workbench/ui/qgis_stack/widgets.py`
- Test: `tests/test_qgis_canvas_embed.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `QgisMapStack`。
- Produces:
  - C++（本任务在 `map_stack_service.hpp` 的类中追加声明，绑定为 snake_case）：`create_canvas/set_canvas_white_background/set_destination_crs/set_canvas_extent/canvas_extent/zoom_to_full_extent/zoom_to_previous_extent/zoom_to_next_extent/refresh_canvas/screen_to_map/map_to_screen`；extent 一律 `[xmin, ymin, xmax, ymax]`。
  - Python：`paleo_workbench.ui.qgis_stack.widgets.QgisCanvasHost(stack, parent=None)`，属性 `.canvas -> QWidget`（wrap 后的 QgsMapCanvas）、`.canvas_address -> int`、`.stack -> QgisMapStack`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_canvas_embed.py
"""M1 Task 3: QgsMapCanvas 经地址边界嵌入 PySide6 布局，白底。"""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_canvas_embeds_as_child_widget(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    assert host.canvas.parentWidget() is host
    assert host.canvas.width() > 0
    # 白底：QWidget 基色即画布底色（#ffffff）。
    assert host.canvas.palette().color(host.canvas.backgroundRole()).name() == "#ffffff"


def test_canvas_extent_roundtrip(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    stack.set_destination_crs(host.canvas_address, "EPSG:4326")
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 10.0)
    extent = stack.canvas_extent(host.canvas_address)
    assert extent == pytest.approx([0.0, 0.0, 10.0, 10.0], abs=2.0)  # 画布按宽高比扩展
    point = stack.screen_to_map(host.canvas_address, 320.0, 240.0)
    assert point == pytest.approx([5.0, 5.0], abs=1.5)
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_canvas_embed.py -v`
Expected: FAIL（`ModuleNotFoundError: paleo_workbench.ui.qgis_stack` 或 C++ 方法未绑定）

- [ ] **Step 3: 实现 C++ canvas 方法**

```cpp
// map_stack_service.hpp 的 QgisMapStack 类中追加声明（public 区）：
  std::uintptr_t createCanvas();
  void setCanvasWhiteBackground(std::uintptr_t canvas);
  void setDestinationCrs(std::uintptr_t canvas, const std::string& crs_auth_id);
  void setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                       double xmax, double ymax);
  std::vector<double> canvasExtent(std::uintptr_t canvas) const;
  void zoomToFullExtent(std::uintptr_t canvas);
  void zoomToPreviousExtent(std::uintptr_t canvas);
  void zoomToNextExtent(std::uintptr_t canvas);
  void refreshCanvas(std::uintptr_t canvas);
  std::vector<double> screenToMap(std::uintptr_t canvas, double x, double y) const;
  std::vector<double> mapToScreen(std::uintptr_t canvas, double x, double y) const;
```

```cpp
// map_stack_service.cpp 追加 include：
#include <QColor>
#include <QWidget>
#include <qgsmapcanvas.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsrectangle.h>

// 地址还原辅助（本文件内静态；Task 4/5 复用）：
static QgsMapCanvas* canvasOrThrow(std::uintptr_t address) {
  auto* canvas = reinterpret_cast<QgsMapCanvas*>(address);
  if (canvas == nullptr) throw std::invalid_argument("null canvas address");
  return canvas;
}

// 实现（QgisMapStack 成员）：
std::uintptr_t QgisMapStack::createCanvas() {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  auto* canvas = new QgsMapCanvas();  // 无父对象：所有权随地址移交 Python 侧布局
  canvas->setCanvasColor(Qt::white);
  canvas->enableAntiAliasing(true);
  return reinterpret_cast<std::uintptr_t>(canvas);
}

void QgisMapStack::setCanvasWhiteBackground(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->setCanvasColor(Qt::white);
}

void QgisMapStack::setDestinationCrs(std::uintptr_t canvas, const std::string& crs) {
  canvasOrThrow(canvas)->setDestinationCrs(
      QgsCoordinateReferenceSystem(QString::fromStdString(crs)));
}

void QgisMapStack::setCanvasExtent(std::uintptr_t canvas, double xmin, double ymin,
                                   double xmax, double ymax) {
  canvasOrThrow(canvas)->setExtent(QgsRectangle(xmin, ymin, xmax, ymax));
}

std::vector<double> QgisMapStack::canvasExtent(std::uintptr_t canvas) const {
  const QgsRectangle r = canvasOrThrow(canvas)->extent();
  return {r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()};
}

void QgisMapStack::zoomToFullExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToFullExtent();
}
void QgisMapStack::zoomToPreviousExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToPreviousExtent();
}
void QgisMapStack::zoomToNextExtent(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->zoomToNextExtent();
}
void QgisMapStack::refreshCanvas(std::uintptr_t canvas) {
  canvasOrThrow(canvas)->refresh();
}

std::vector<double> QgisMapStack::screenToMap(std::uintptr_t canvas, double x, double y) const {
  const QgsPointXY p = canvasOrThrow(canvas)->getCoordinateTransform()->toMapCoordinates(
      static_cast<int>(x), static_cast<int>(y));
  return {p.x(), p.y()};
}

std::vector<double> QgisMapStack::mapToScreen(std::uintptr_t canvas, double x, double y) const {
  const QPointF p = canvasOrThrow(canvas)->getCoordinateTransform()->transform(
      QgsPointXY(x, y));
  return {p.x(), p.y()};
}
```

```cpp
// bindings.cpp 的 QgisMapStack 绑定追加：
        .def("create_canvas", &pwb::qgis_render::QgisMapStack::createCanvas)
        .def("set_canvas_white_background", &pwb::qgis_render::QgisMapStack::setCanvasWhiteBackground)
        .def("set_destination_crs", &pwb::qgis_render::QgisMapStack::setDestinationCrs)
        .def("set_canvas_extent", &pwb::qgis_render::QgisMapStack::setCanvasExtent)
        .def("canvas_extent", &pwb::qgis_render::QgisMapStack::canvasExtent)
        .def("zoom_to_full_extent", &pwb::qgis_render::QgisMapStack::zoomToFullExtent)
        .def("zoom_to_previous_extent", &pwb::qgis_render::QgisMapStack::zoomToPreviousExtent)
        .def("zoom_to_next_extent", &pwb::qgis_render::QgisMapStack::zoomToNextExtent)
        .def("refresh_canvas", &pwb::qgis_render::QgisMapStack::refreshCanvas)
        .def("screen_to_map", &pwb::qgis_render::QgisMapStack::screenToMap)
        .def("map_to_screen", &pwb::qgis_render::QgisMapStack::mapToScreen)
```

- [ ] **Step 4: 实现 Python 嵌入层**

```python
# paleo_workbench/ui/qgis_stack/__init__.py
"""QGIS 原生地图栈的 PySide6 嵌入层（M1）。"""
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

__all__ = ["QgisCanvasHost"]
```

```python
# paleo_workbench/ui/qgis_stack/widgets.py
"""桥地址 ↔ PySide6 控件的唯一转换点（No QWidget crosses the boundary 的落地）。"""
from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import QVBoxLayout, QWidget


def cpp_pointer(widget: QWidget) -> int:
    """PySide6 控件 → C++ QWidget 地址。"""
    return int(shiboken6.getCppPointer(widget)[0])


def wrap_widget(address: int) -> QWidget:
    """C++ QWidget 地址 → PySide6 控件（所有权移交，随父对象销毁）。"""
    return shiboken6.wrapInstance(address, QWidget)


class QgisCanvasHost(QWidget):
    """把 QgsMapCanvas 嵌进 PySide6 布局的宿主。"""

    def __init__(self, stack, parent=None):
        super().__init__(parent)
        self.stack = stack
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas_address: int = stack.create_canvas()
        self.canvas = wrap_widget(self.canvas_address)
        layout.addWidget(self.canvas)
```

- [ ] **Step 5: 重编扩展并运行测试**

```bash
cd /home/kevin/projects/paleo_project/main
/opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_canvas_embed.py tests/test_qgis_mapstack_lifecycle.py -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/qgis_stack/ tests/test_qgis_canvas_embed.py
git commit -m "feat(qgis): QgsMapCanvas 地址边界嵌入 PySide6（QgisCanvasHost，白底）"
```

---

### Task 4: 图层镜像进 QgsProject + 画布渲染

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（图层方法 + 树桥）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（图层绑定）
- Test: `tests/test_qgis_mapstack_layers.py`（新建）

**Interfaces:**
- Consumes: Task 3 的 canvas 方法。
- Produces:
  - `add_vector_layer_geojson(name, geometry_type, crs_auth_id, geojson_feature_collection) -> str`（layer id；`geometry_type ∈ {"Point","LineString","Polygon"}`；GeoJSON 为标准 FeatureCollection 字符串）
  - `remove_layer(layer_id) -> bool`、`set_layer_visibility(layer_id, visible)`、`set_layer_opacity(layer_id, opacity)`、`clear_project_layers()`
  - 图层加入后 canvas 自动重渲染（`QgsLayerTreeMapCanvasBridge`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_mapstack_layers.py
"""M1 Task 4: GeoJSON 图层镜像进 QgsProject，画布渲染出要素像素。"""
import pytest

pytest.importorskip("PySide6")

_POINTS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "A1"}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_add_mirror_render_remove(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    layer_id = stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _POINTS)
    assert layer_id
    assert stack.project_layer_count() == 1

    stack.set_destination_crs(host.canvas_address, "EPSG:4326")
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 10.0)
    stack.refresh_canvas(host.canvas_address)
    qtbot.waitUntil(lambda: True, timeout=100)  # 让事件循环驱动一帧

    # 中心点要素已渲染：画布中央像素不是纯白。
    from PySide6.QtGui import QImage
    image = host.canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    center = image.pixelColor(320, 240)
    assert (center.red(), center.green(), center.blue()) != (255, 255, 255)

    stack.set_layer_visibility(layer_id, False)
    stack.refresh_canvas(host.canvas_address)
    assert stack.remove_layer(layer_id)
    assert stack.project_layer_count() == 0
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（`AttributeError: ... 'add_vector_layer_geojson'`）

- [ ] **Step 3: 实现 C++ 图层方法**

```cpp
// map_stack_service.hpp 的 QgisMapStack 类中追加声明（public 区）：
  std::string addVectorLayerGeoJson(const std::string& name,
                                    const std::string& geometry_type,
                                    const std::string& crs_auth_id,
                                    const std::string& geojson_feature_collection);
  bool removeLayer(const std::string& layer_id);
  void setLayerVisibility(const std::string& layer_id, bool visible);
  void setLayerOpacity(const std::string& layer_id, double opacity);
  void clearProjectLayers();
```

```cpp
// map_stack_service.cpp 追加 include：
#include <unordered_map>
#include <qgsvectorlayer.h>
#include <qgsjsonutils.h>
#include <qgslayertreemapcanvasbridge.h>
#include <qgslayertree.h>
#include <qgslayertreelayer.h>

// Impl 结构体改为：
struct QgisMapStack::Impl {
  bool initialized = false;
  std::unordered_map<std::uintptr_t, std::unique_ptr<QgsLayerTreeMapCanvasBridge>>
      tree_bridges;
};

// createCanvas 的 return 之前追加（树桥让 QgsProject 图层变化自动反映到画布）：
//   auto tree_bridge = std::make_unique<QgsLayerTreeMapCanvasBridge>(
//       QgsProject::instance()->layerTreeRoot(), canvas);
//   tree_bridge->setCanvasLayers();
//   impl_->tree_bridges.emplace(reinterpret_cast<std::uintptr_t>(canvas),
//                               std::move(tree_bridge));
```

std::string QgisMapStack::addVectorLayerGeoJson(
    const std::string& name, const std::string& geometry_type,
    const std::string& crs_auth_id, const std::string& geojson) {
  if (!impl_->initialized) throw std::runtime_error("map stack is not initialized");
  const QString uri = QStringLiteral("%1?crs=%2")
      .arg(QString::fromStdString(geometry_type), QString::fromStdString(crs_auth_id));
  auto layer = std::make_unique<QgsVectorLayer>(
      uri, QString::fromStdString(name), QStringLiteral("memory"));
  if (!layer->isValid()) throw std::runtime_error("memory layer creation failed: " + name);

  const QgsFeatureList features = QgsJsonUtils::stringToFeatureList(
      QString::fromStdString(geojson));
  if (!features.isEmpty()) {
    layer->dataProvider()->addFeatures(features);
    layer->updateExtents();
  }
  const std::string id = layer->id().toStdString();
  QgsProject::instance()->addMapLayer(layer.release());
  return id;
}

bool QgisMapStack::removeLayer(const std::string& layer_id) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(
      QString::fromStdString(layer_id));
  if (layer == nullptr) return false;
  QgsProject::instance()->removeMapLayer(layer);
  return true;
}

void QgisMapStack::setLayerVisibility(const std::string& layer_id, bool visible) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  QgsLayerTreeLayer* node = QgsProject::instance()->layerTreeRoot()->findLayer(layer);
  if (node != nullptr) node->setItemVisibilityChecked(visible);
}

void QgisMapStack::setLayerOpacity(const std::string& layer_id, double opacity) {
  QgsMapLayer* layer = QgsProject::instance()->mapLayer(QString::fromStdString(layer_id));
  if (layer == nullptr) throw std::invalid_argument("unknown layer: " + layer_id);
  layer->setOpacity(std::clamp(opacity, 0.0, 1.0));
}

void QgisMapStack::clearProjectLayers() {
  QgsProject::instance()->removeAllMapLayers();
}
```

```cpp
// bindings.cpp 追加：
        .def("add_vector_layer_geojson", &pwb::qgis_render::QgisMapStack::addVectorLayerGeoJson)
        .def("remove_layer", &pwb::qgis_render::QgisMapStack::removeLayer)
        .def("set_layer_visibility", &pwb::qgis_render::QgisMapStack::setLayerVisibility)
        .def("set_layer_opacity", &pwb::qgis_render::QgisMapStack::setLayerOpacity)
        .def("clear_project_layers", &pwb::qgis_render::QgisMapStack::clearProjectLayers)
```

- [ ] **Step 4: 重编并运行测试**

```bash
cd /home/kevin/projects/paleo_project/main
/opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_layers.py -v
```
Expected: 1 passed（若中心像素断言失败：先确认 `QgsLayerTreeMapCanvasBridge::setCanvasLayers()` 已调用、extent 已 set 且 refresh 后跑了事件循环）

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/ tests/test_qgis_mapstack_layers.py
git commit -m "feat(qgis): GeoJSON 图层镜像进 QgsProject + 图层树画布桥渲染"
```

---

### Task 5: 原生 pan/zoom 工具 + extent/坐标信号回调

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（`setMapTool` + 回调）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（工具/回调绑定；`#include <pybind11/functional.h>`）
- Create: `paleo_workbench/ui/qgis_stack/events.py`
- Test: `tests/test_qgis_mapstack_tools.py`（新建）

**Interfaces:**
- Consumes: Task 3/4。
- Produces:
  - `set_map_tool(canvas, kind)`，`kind ∈ {"pan", "zoomIn", "zoomOut"}`（编辑类 kind 属 M3，不在本任务）
  - `set_extent_callback(canvas, callable)` / `set_xy_callback(canvas, callable)`；callable 在 GUI 线程被调（C++ 内部已 `py::gil_scoped_acquire`），参数分别为 `(xmin, ymin, xmax, ymax)` 与 `(x, y)`
  - Python：`paleo_workbench.ui.qgis_stack.events.StackEvents`，Signal `extent_changed(float×4)`、`map_position_changed(float×2)`；`attach(stack, canvas_address)` 完成接线（回调→`QTimer.singleShot(0, …)`→Signal）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_mapstack_tools.py
"""M1 Task 5: 原生 map tool 切换 + extent/坐标回调 marshal 成 Qt Signal。"""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_set_native_tool(stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    for kind in ("pan", "zoomIn", "zoomOut"):
        stack.set_map_tool(host.canvas_address, kind)  # 不抛异常即通过
    with pytest.raises(Exception):
        stack.set_map_tool(host.canvas_address, "not-a-tool")


def test_extent_callback_fires_as_signal(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.events import StackEvents
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    events = StackEvents()
    events.attach(stack, host.canvas_address)
    seen = []
    events.extent_changed.connect(lambda *a: seen.append(a))

    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 20.0, 20.0)
    qtbot.waitUntil(lambda: len(seen) > 0, timeout=2000)
    assert seen[-1][2] > 0  # xmax 有效
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（`AttributeError` / 无 `events` 模块）

- [ ] **Step 3: 实现 C++ 工具与回调**

GIL 约定：`map_stack_service.cpp` **不引入 pybind11**（保持纯 Qt/C++ 编译单元）；回调存的是裸 `std::function`，由 bindings.cpp 在绑定层用 lambda 包 `py::gil_scoped_acquire` 后传入。

```cpp
// map_stack_service.hpp 的 QgisMapStack 类中追加声明（public 区）：
  void setMapTool(std::uintptr_t canvas, const std::string& kind);
  using ExtentCallback = std::function<void(double, double, double, double)>;
  using PointCallback = std::function<void(double, double)>;
  void setExtentCallback(std::uintptr_t canvas, ExtentCallback callback);
  void setXyCallback(std::uintptr_t canvas, PointCallback callback);
```

```cpp
// map_stack_service.cpp 追加 include：
#include <qgsmaptoolpan.h>
#include <qgsmaptoolzoom.h>
#include <qgspointxy.h>

// Impl 结构体增加成员：
//   std::unordered_map<std::uintptr_t, std::unique_ptr<QgsMapTool>> tools;
//   std::unordered_map<std::uintptr_t, ExtentCallback> extent_callbacks;
//   std::unordered_map<std::uintptr_t, PointCallback> xy_callbacks;

void QgisMapStack::setMapTool(std::uintptr_t canvas_addr, const std::string& kind) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  if (kind == "pan") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolPan>(canvas);
  } else if (kind == "zoomIn") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, false);
  } else if (kind == "zoomOut") {
    impl_->tools[canvas_addr] = std::make_unique<QgsMapToolZoom>(canvas, true);
  } else {
    throw std::invalid_argument("unknown map tool kind: " + kind);
  }
  canvas->setMapTool(impl_->tools[canvas_addr].get());
}

void QgisMapStack::setExtentCallback(std::uintptr_t canvas_addr, ExtentCallback callback) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->extent_callbacks[canvas_addr] = std::move(callback);
  QObject::connect(canvas, &QgsMapCanvas::extentsChanged, canvas, [this, canvas_addr]() {
    const auto& cb = impl_->extent_callbacks[canvas_addr];
    if (!cb) return;
    const QgsRectangle r = canvasOrThrow(canvas_addr)->extent();
    cb(r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum());
  });
}

void QgisMapStack::setXyCallback(std::uintptr_t canvas_addr, PointCallback callback) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  impl_->xy_callbacks[canvas_addr] = std::move(callback);
  QObject::connect(canvas, &QgsMapCanvas::xyCoordinates, canvas,
                   [this, canvas_addr](const QgsPointXY& p) {
    const auto& cb = impl_->xy_callbacks[canvas_addr];
    if (!cb) return;
    cb(p.x(), p.y());
  });
}
```

```cpp
// bindings.cpp（文件顶部确认已有 #include <pybind11/functional.h>）追加绑定——
// GIL 包装在这一层完成：
        .def("set_map_tool", &pwb::qgis_render::QgisMapStack::setMapTool)
        .def("set_extent_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas, py::function f) {
               self.setExtentCallback(canvas, [f = std::move(f)](double a, double b, double c, double d) {
                 py::gil_scoped_acquire gil;
                 f(a, b, c, d);
               });
             })
        .def("set_xy_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas, py::function f) {
               self.setXyCallback(canvas, [f = std::move(f)](double x, double y) {
                 py::gil_scoped_acquire gil;
                 f(x, y);
               });
             })
```

- [ ] **Step 4: 实现 events.py**

```python
# paleo_workbench/ui/qgis_stack/events.py
"""桥回调 → Qt Signal。桥回调在 GUI 线程但直接回 Python 层，统一经
QTimer.singleShot(0, …) 重排队，避免在桥调用栈深处触发槽函数。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class StackEvents(QObject):
    extent_changed = Signal(float, float, float, float)
    map_position_changed = Signal(float, float)

    def attach(self, stack, canvas_address: int) -> None:
        stack.set_extent_callback(
            canvas_address,
            lambda xmin, ymin, xmax, ymax: QTimer.singleShot(
                0, lambda: self.extent_changed.emit(xmin, ymin, xmax, ymax)
            ),
        )
        stack.set_xy_callback(
            canvas_address,
            lambda x, y: QTimer.singleShot(
                0, lambda: self.map_position_changed.emit(x, y)
            ),
        )
```

- [ ] **Step 5: 重编并运行测试**

```bash
cd /home/kevin/projects/paleo_project/main
/opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_tools.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/qgis_stack/events.py tests/test_qgis_mapstack_tools.py
git commit -m "feat(qgis): 原生 pan/zoom map tool + extent/坐标回调 marshal"
```

---

### Task 6: 兼容 shim 接入综合编修文档区

**Files:**
- Create: `paleo_workbench/ui/qgis_stack/canvas_shim.py`
- Modify: `paleo_workbench/ui/workstation/composite_document.py`（中央画布替换 + 接线）
- Test: `tests/test_composite_qgis_canvas.py`（新建）

**Interfaces:**
- Consumes: Task 3/4/5 全部。
- Produces:
  - `QgisCanvasShim(QWidget)`——实现 `CompositeDocument` 及其控制器当前在 `UnifiedMapCanvas` 上实际使用的子集：
    `set_layer_snapshot(snapshot)`（把 `MapRenderSnapshot.layers` 的矢量图层转 GeoJSON 镜像进 QgsProject）、`set_extent(tuple)`、`view_extent -> tuple`、`previous_extent()`、`next_extent()`、`update()`、信号 `extent_changed`、`map_position_changed(float, float)`、`backend_status_changed`、`tool_operation(str)`（M1 只发 pan/zoom；编辑类 op 发状态消息"M3 恢复"，不抛异常）、`map_to_screen(tuple) -> tuple`、`screen_to_map(tuple) -> tuple`、`set_overlay_provider(callable)`（M1 存而不画）
  - `CompositeDocument.canvas` 改为 `QgisCanvasShim` 实例（中央布局位置不变）。

**已知取舍（M1 内接受，M3 收回）：** 自绘编辑叠加层（采点预览/顶点手柄）在 M1 不显示；`CompositeEditController.attach_canvas` 仍被调用（其数据模型继续工作），凡直接触碰旧画布像素/overlay 的既有测试用 `pytest.mark.skip(reason="QGIS 栈 M3 恢复")` 隔离并列入本任务提交说明。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_composite_qgis_canvas.py
"""M1 Task 6: 综合编修文档区由 QgsMapCanvas 承载（shim 契约）。"""
import pytest

pytest.importorskip("PySide6")


def test_composite_document_hosts_qgis_canvas(qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.resize(900, 600)
    doc.show()

    assert isinstance(doc.canvas, QgisCanvasShim)
    assert doc.canvas.canvas.width() > 0  # 真 QgsMapCanvas 已在布局中
    doc.canvas.backend_status_changed.emit  # 信号存在
    assert "qgis" in doc.canvas.backend_status.lower()


def test_shim_mirrors_vector_snapshot_to_project(qtbot):
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot,
    )
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.canvas.set_layer_snapshot(MapRenderSnapshot(
        project_crs="EPSG:4326",
        layers=[
            MapLayerSnapshot(
                id="w1", name="井位", layer_type="vector",
                data_revision=1, style_revision=1, visible=True, opacity=1.0,
                extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
                features=({"id": "f1",
                           "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                           "properties": {}},),
                style={"fill": "#e03131", "stroke": "#1f2937", "stroke_width": 1.0,
                       "marker": "circle", "marker_size": 6.0},
            ),
        ],
    ))
    assert doc.canvas.stack.project_layer_count() == 1
```

- [ ] **Step 2: 运行确认失败**

Expected: FAIL（无 `canvas_shim` 模块 / `doc.canvas` 仍是 `UnifiedMapCanvas`）

- [ ] **Step 3: 实现 canvas_shim.py**

```python
# paleo_workbench/ui/qgis_stack/canvas_shim.py
"""QgisCanvasShim：QGIS 画布承载，暴露 CompositeDocument 现行消费的
UnifiedMapCanvas 子集契约。M1 只承诺 pan/zoom 与图层镜像；编辑类
tool_operation 记录状态消息，M3 由原生 QgsMapTool 编辑栈接管。"""
from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "Polygon", "MultiPolygon": "Polygon"}


class QgisCanvasShim(QWidget):
    extent_changed = Signal()
    map_position_changed = Signal(float, float)
    backend_status_changed = Signal()
    tool_operation = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from qgis_render_bridge.mapstack import QgisMapStack

        self.stack = QgisMapStack()
        self.stack.initialize()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._host = QgisCanvasHost(self.stack, self)
        layout.addWidget(self._host)
        self.canvas = self._host.canvas  # 真 QgsMapCanvas（测试可达）
        self.events = StackEvents(self)
        self.events.attach(self.stack, self._host.canvas_address)
        self.events.extent_changed.connect(lambda *_: self.extent_changed.emit())
        self.events.map_position_changed.connect(self.map_position_changed)
        self._overlay_provider = None
        self._mirrored_layers: list[str] = []

    # --- 状态与几何 ---------------------------------------------------
    @property
    def backend_status(self) -> str:
        return "qgis: ready"

    @property
    def canvas_address(self) -> int:
        return self._host.canvas_address

    @property
    def view_extent(self) -> tuple[float, float, float, float]:
        return tuple(self.stack.canvas_extent(self.canvas_address))

    def set_extent(self, extent) -> None:
        self.stack.set_canvas_extent(self.canvas_address, *extent)

    def previous_extent(self) -> None:
        self.stack.zoom_to_previous_extent(self.canvas_address)

    def next_extent(self) -> None:
        self.stack.zoom_to_next_extent(self.canvas_address)

    def map_to_screen(self, point) -> tuple[float, float]:
        return tuple(self.stack.map_to_screen(self.canvas_address, point[0], point[1]))

    def screen_to_map(self, point) -> tuple[float, float]:
        return tuple(self.stack.screen_to_map(self.canvas_address, point[0], point[1]))

    def set_overlay_provider(self, provider) -> None:
        self._overlay_provider = provider  # M1 存而不画

    # --- 图层镜像 ------------------------------------------------------
    def set_layer_snapshot(self, snapshot) -> None:
        if snapshot.project_crs:
            self.stack.set_destination_crs(self.canvas_address, snapshot.project_crs)
        self.stack.clear_project_layers()
        self._mirrored_layers.clear()
        for layer in snapshot.layers:
            if not layer.visible or layer.layer_type != "vector":
                continue
            features = [
                {"type": "Feature",
                 "geometry": f.get("geometry"),
                 "properties": dict(f.get("properties") or {})}
                for f in layer.features
            ]
            if not features:
                continue
            geom = _GEOMETRY_TYPE.get(
                str(features[0]["geometry"].get("type", "")), "Point"
            )
            layer_id = self.stack.add_vector_layer_geojson(
                layer.name or layer.id, geom, layer.crs or snapshot.project_crs,
                json.dumps({"type": "FeatureCollection", "features": features}),
            )
            if layer.opacity < 1.0:
                self.stack.set_layer_opacity(layer_id, layer.opacity)
            self._mirrored_layers.append(layer_id)
        self.stack.refresh_canvas(self.canvas_address)
        self.backend_status_changed.emit()

    def update(self) -> None:  # noqa: A003 — Qt 契约
        super().update()
        self.stack.refresh_canvas(self.canvas_address)
```

- [ ] **Step 4: 替换 CompositeDocument 中央画布**

`paleo_workbench/ui/workstation/composite_document.py`：
- import 区把 `from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas` 替换为 `from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim`。
- 构造中 `self.canvas = UnifiedMapCanvas(parent=self)`（约 704 行）改为 `self.canvas = QgisCanvasShim(parent=self)`。
- 其余接线（`edit_controller.attach_canvas(self.canvas)`、各信号连接）保持不变——shim 契约就是按这些调用点定义的；若发现 shim 未覆盖的调用点，在 shim 上补同名方法（M1 语义：无副作用的存根 + 状态消息），不得让 CompositeDocument 回引 `UnifiedMapCanvas`。

- [ ] **Step 5: 运行新测试 + 综合编修相关既有测试并隔离 M3 依赖项**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_composite_qgis_canvas.py tests/test_composite_gis.py tests/test_workstation_shell.py -v
```
对因「自绘编辑叠加层在 M1 不存在」而失败的用例，加 `pytest.mark.skip(reason="QGIS 栈 M3 恢复")`，并在提交说明中逐个列出用例名。像素基准类断言若只因底色/渲染器不同而失败，改为针对 QGIS 渲染输出重新标定（不得以放松断言之名放行行为回归）。
Expected: 新测试 2 passed；既有套件通过或被明确标注 skip。

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/qgis_stack/canvas_shim.py paleo_workbench/ui/workstation/composite_document.py tests/test_composite_qgis_canvas.py <被隔离的测试文件>
git commit -m "feat(qgis): 综合编修文档区切换 QgsMapCanvas（兼容 shim；M3 恢复原生编辑）"
```

---

### Task 7: M1 收尾——端到端演示验证 + 文档 + 全量回归

**Files:**
- Modify: `README.md`（构建/运行节增加桥的安装命令）
- Modify: `AGENTS.md` 或 `CLAUDE.md`（如存在对应条目，更新地图栈状态）
- Test: 全量回归

**Interfaces:**
- Consumes: Task 1–6。
- Produces: M1 可演示判定记录（本任务提交说明）。

- [ ] **Step 1: 真实应用冒烟（offscreen 结构断言）**

```bash
cd /home/kevin/projects/paleo_project/main
ENGINE=/home/kevin/projects/paleo_project/main/geo-viz-engine
PP="/home/kevin/projects/paleo_project/main:$ENGINE:/home/kevin/projects/paleo_project/main/well-log-engine"
for pkg in "$ENGINE"/packages/*/; do PP="$PP:${pkg%/}"; done
QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 PYTHONPATH="$PP" \
  timeout 90 /opt/miniconda3/bin/python3.13 - <<'EOF'
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
app = QApplication(sys.argv)
from paleo_workbench.app import PaleoWorkbenchWindow
win = PaleoWorkbenchWindow()
win.resize(1440, 900)
win.show()
def check():
    ws = win.app_shell.workstation
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    assert isinstance(ws.composite.canvas, QgisCanvasShim), type(ws.composite.canvas)
    print("M1-SMOKE PASS")
    app.quit()
QTimer.singleShot(3000, check)
app.exec()
EOF
```
Expected: 输出 `M1-SMOKE PASS`

- [ ] **Step 2: 真机启动验证（用户桌面）**

```bash
ENGINE=/home/kevin/projects/paleo_project/main/geo-viz-engine
PP="$ENGINE:/home/kevin/projects/paleo_project/main/well-log-engine"
for pkg in "$ENGINE"/packages/*/; do PP="$PP:${pkg%/}"; done
cd /home/kevin/projects/paleo_project/main
PYTHONPATH="$PP" /opt/miniconda3/bin/python3.13 -m paleo_workbench.main
```
预期：综合编修 tab 显示白底 QGIS 画布；加载 `data/project_area` 工程后井位/工区图层可见；鼠标拖拽平移、滚轮缩放为 QGIS 原生行为。由用户确认后进入 M2。

- [ ] **Step 3: 更新文档**

`README.md` 的 "Running the Application" 前增加：

```markdown
### QGIS 原生地图栈（硬依赖，自 v0.3 起）

地图区由 vendored QGIS 4.2（`third_party/qgis`）的 `QgsMapCanvas` 承载，
首次构建/安装：

    python -m pip install "pybind11>=2.12" ninja
    python -m pip install -e native/qgis_render_bridge   # 首次构建 vendored QGIS 需数小时

桥未安装时地图区构造会明确报错（无 fallback）。
```

`AGENTS.md`/`CLAUDE.md` 中涉及 `UnifiedMapCanvas`/fallback 渲染的条目标注「M1 起综合编修区由 QGIS 画布承载；fallback 拆除在 M4」。

- [ ] **Step 4: 全量回归**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/ -x -q
```
Expected: 全绿，或仅剩已知环境性失败（缺 `layer_model_core`/`grid_render_core` C++ 扩展的用例——clean main 同样失败）与本计划 Task 6 标注的 M3 skip 项。将结果摘要写入提交说明。

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md CLAUDE.md 2>/dev/null; git add -A docs/
git commit -m "docs(qgis): M1 收尾——构建说明、地图栈状态、回归基线"
```

---

## M1 完成定义（DoD）

1. `QgisCanvasShim` 承载综合编修区，真 `QgsMapCanvas` 在布局中可见可交互（pan/zoom 原生）。
2. 矢量图层经 GeoJSON 镜像进 `QgsProject` 并渲染（白底）。
3. extent/坐标信号以 Qt Signal 形式到达 Python 侧。
4. 上述全部测试绿；M3 依赖项以 skip 显式标注且列出清单。
5. 用户在真机确认演示效果。

## 显式不在 M1 范围

- `QgsLayerTreeView` 图层管理、`QgsVectorLayerPropertiesDialog`（M2）。
- 编辑类 `QgsMapTool`、捕捉、撤销重做（M3）。
- 工程文件持久化往返、fallback 拆除（M4）。
