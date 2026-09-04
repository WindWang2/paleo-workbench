# QGIS 原生地图栈 M2（QgsLayerTreeView 图层管理 + 原生图层属性对话框）实施计划

> **Status: COMPLETE** — merged to main at `55fcb640`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 综合编修区的图层管理面板与图层属性对话框完全由 QGIS 原生控件承载——`QgsLayerTreeView`（图例/勾选/拖拽排序/重命名/右键菜单）替换自绘 `LayerManagerPanel` 的树，`QgsVectorLayerProperties` 替换自绘 `MapLayerPropertiesDialog`；镜像改增量，树操作回写文档模型。

**Architecture:** 扩展 `native/qgis_render_bridge` 的 `mapstack` 子模块：C++ 侧创建 `QgsLayerTreeView`（`QgsLayerTreeModel` 挂 `QgsProject::instance()->layerTreeRoot()`）+ 自实现 `QgsLayerTreeViewMenuProvider`（app 层的 `QgsAppLayerTreeViewMenuProvider` 不可用，用 `QgsLayerTreeViewDefaultActions` + 自定义动作）+ 模态 `QgsVectorLayerProperties`。文档图层 id 经 `QgsMapLayer` customProperty `pwb/doc_id` 双向映射。镜像从「整树清空重建」改为按 doc_id 的增量 reconcile（upsert + 补删 + 排序）。树的用户操作经 std::function 回调 marshal 到 Python（QTimer.singleShot），只写文档模型与持久化，不再回推画布（画布由 `QgsLayerTreeMapCanvasBridge` 自动同步）。属性对话框 exec 后提取 `renderer_xml`/`labeling_xml`/opacity 走现有 `qgis_style` payload 路径回写持久化。

**Tech Stack:** PySide6 (Qt6), pybind11, vendored QGIS 4.2 (`third_party/qgis`, libqgis_gui 已含全部所需符号), shiboken6, pytest + pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`；**M1 已完成并合并 main（70c9811e + 样式修复 54db801f）**

## Global Constraints

- 硬依赖：不依赖系统 QGIS；只允许 vendored 构建（`native/qgis_render_bridge/build/qgis-vendor/output`）。
- 不向 QGIS 官方 Python 绑定（sip/PyQt6）迁移；进程内只有 PySide6 一套绑定运行时。
- C++ 边界：**No QWidget crosses the boundary as a typed object**——控件以 `uintptr_t` 地址传递，Python 侧只经 `shiboken6.wrapInstance` 还原。
- 绑定暴露给 Python 的名字必须 snake_case；GIL 只在 `bindings.cpp` 处理；`map_stack_service.cpp` 保持纯 Qt/C++（禁止 pybind11/Python.h include）。
- `QgsProject` 是地图图层**运行时权威**；自有工程文件是**持久化权威**。树的用户操作直接落在 QgsProject（画布经 QgsLayerTreeMapCanvasBridge 自动跟随），同时回写文档模型；文档模型触发的镜像不得整树重建。
- 重建命令：`cd /home/kevin/projects/paleo_project/main && PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge`（env var 必须带）。
- 测试一律经 `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args>`（offscreen）。禁止对含 QOpenGLWidget 的整窗 `grab()`（段错误）；对画布本身 `grab()` 可用。
- 画布底色白色（既有决定）；M1 既有 API 的签名/语义不得破坏（Task 2 的 reconcile 是 `set_layer_snapshot` 内部实现替换，对外契约不变）。
- 所有提交在 `/home/kevin/projects/paleo_project/main` 工作区进行（功能分支 + 合并回 main，分支合并后删除）。

## 已核实的环境事实（侦察结论，执行时直接采信）

- `QgsLayerTreeView`（`third_party/qgis/src/gui/layertree/qgslayertreeview.h:426`）、`QgsLayerTreeViewDefaultActions`（`qgslayertreeviewdefaultactions.h:38`）、`QgsVectorLayerProperties`（`src/gui/vector/qgsvectorlayerproperties.h:59`，ctor `(QgsMapCanvas*, QgsMessageBar*, QgsVectorLayer*, QWidget*, Qt::WindowFlags)`）、`QgsRasterLayerProperties`（`src/gui/raster/qgsrasterlayerproperties.h:54`）均已编入 `libqgis_gui.so.4.2.0`（nm 已验证导出符号）。
- `QgsLayerTreeModel` 在 `libqgis_core`（`src/core/layertree/qgslayertreemodel.h:60`），flags：`ShowLegend`、`AllowNodeReorder`、`AllowNodeRename`、`AllowNodeChangeVisibility`。
- `QgsLayerTreeViewMenuProvider` 是 gui 的纯虚接口（`qgslayertreeview.h:655`），`view->setMenuProvider(...)` 接管所有权；`view->defaultActions()` 返回 `QgsLayerTreeViewDefaultActions*`。app 级菜单提供者不可链接，必须自实现。
- 树构造配方：`model = new QgsLayerTreeModel(QgsProject::instance()->layerTreeRoot(), parent)` → `model->setFlag(...)` → `view = new QgsLayerTreeView(parent)` → `view->setModel(model)`（内部自建 proxy）。画布同步桥已在 M1 `createCanvas` 中创建（`QgsLayerTreeMapCanvasBridge(layerTreeRoot, canvas)`），树勾选后画布自动刷新，无需额外接线。
- 图标经 qrc 编译进库（`QgsApplication::getThemeIcon`），无需拷资源；`PALEO_QGIS_PREFIX_PATH` 指向 vendor output 即可。
- 样式序列化工具已共享在 `native/qgis_render_bridge/src/style_codec.{hpp,cpp}`：`renderer_to_xml(const QgsFeatureRenderer&)` / `renderer_from_xml(...)` / `apply_renderer_style(...)` / `apply_label_style(...)`。模态对话框进程内模式参照 `src/gui_service.cpp`（`assert_gui_thread` + DialogSession + `collect_result`）。
- `QgsVectorLayerProperties` 的 symbology 页内嵌 `QgsRendererPropertiesDialog`（`qgsvectorlayerproperties.cpp:1537`），即 QGIS 桌面同款符号系统编辑。
- 图层属性对话框需要 `QgsMessageBar*`——允许传 `nullptr`；`toggleEditing`/`exportAuxiliaryLayer` 信号本进程无接收者，忽略。

---

### Task 1: C++ 图层树视图创建 + 嵌入宿主

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp`（追加本任务声明）
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`（树视图创建 + 选择回调）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（绑定）
- Test: `tests/test_qgis_layertree_embed.py`（新建）

**Interfaces:**
- Consumes: M1 的 `QgisMapStack`（`initialize`/`create_canvas`/owned_layers/`canvas_refs` QPointer 机制）。
- Produces:
  - `create_layer_tree_view(canvas) -> int`（canvas 为 uintptr_t 地址；返回 QgsLayerTreeView 的 uintptr_t 地址；树的 model 挂 `QgsProject::instance()->layerTreeRoot()`，flags = ShowLegend|AllowNodeReorder|AllowNodeRename|AllowNodeChangeVisibility）
  - `set_tree_selection_callback(tree_view, callback) -> None`（`callback(doc_layer_id_or_empty_str)`；当前图层变化时触发；doc id 从 `QgsMapLayer` customProperty `pwb/doc_id` 读取，无该属性时回退传 QGIS layer id）
  - 只读树辅助绑定（uintptr_t 边界的现实约束：wrapInstance 只能拿到 QWidget 基类指针，无法在 Python 侧操作树模型；树操作一律走生产绑定）：
    - `tree_view_row_count(tree_view) -> int`
    - `tree_view_layer_name(tree_view, row) -> str`
    - `tree_view_set_current_row(tree_view, row) -> None`（程序化设置当前图层，触发选择回调）
  - Python 侧 `paleo_workbench/ui/qgis_stack/widgets.py` 新增 `QgisLayerTreeHost`（与 `QgisCanvasHost` 同模式：统一 `wrap_widget()` 还原 + 布局承载；widgets.py 顶部抽公共 `wrap_widget(address)`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_layertree_embed.py
"""M2 Task 1: QgsLayerTreeView 嵌入宿主，镜像图层出现在树中。"""
import pytest

pytest.importorskip("PySide6")
from shiboken6 import wrapInstance
from PySide6.QtWidgets import QWidget

_GEOJSON = """{
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


def test_layer_tree_view_embeds_and_lists_mirror_layers(qtbot, stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    tree_addr = stack.create_layer_tree_view(canvas)
    assert tree_addr != 0
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _GEOJSON)
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    names = [stack.tree_view_layer_name(tree_addr, row) for row in range(stack.tree_view_row_count(tree_addr))]
    assert "井位" in names


def test_selection_callback_fires_with_doc_id(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    seen = []
    stack.set_tree_selection_callback(tree_addr, seen.append)
    stack.add_vector_layer_geojson("工区边界", "Polygon", "EPSG:4326", _GEOJSON)
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    stack.tree_view_set_current_row(tree_addr, 0)
    qtbot.waitUntil(lambda: len(seen) >= 1, timeout=2000)
    assert seen[-1]  # 非空：doc id 或 QGIS layer id
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_layertree_embed.py -v`
Expected: FAIL（`AttributeError: create_layer_tree_view`）

- [ ] **Step 3: 实现 C++（声明/定义/绑定同任务落地）**

```cpp
// map_stack_service.hpp 追加（类 public 区）：
  std::uintptr_t createLayerTreeView(std::uintptr_t canvas);
  void setTreeSelectionCallback(std::uintptr_t tree_view,
                                std::function<void(const std::string&)> callback);
// private 区追加：
  QgsLayerTreeView* treeViewOrThrow(std::uintptr_t address) const;

// public 区追加（树驱动/检视 API——uintptr_t 边界不暴露 Qt 模型类型，
// 测试与 M2 面板任务经此操作树；无效树地址经 treeViewOrThrow 抛
// invalid_argument，无效行号抛 std::out_of_range，model 为 null 抛
// std::runtime_error，不做静默返回）：
  int treeViewRowCount(std::uintptr_t tree) const;
  std::string treeViewLayerName(std::uintptr_t tree, int row) const;
  void treeViewSetCurrentRow(std::uintptr_t tree, int row);
```

```cpp
// map_stack_service.cpp 追加
#include <qgslayertreeview.h>
#include <qgslayertreemodel.h>
#include <qgslayertree.h>
#include <qgsmaplayer.h>

// Impl 追加成员：
//   std::unordered_map<std::uintptr_t, QPointer<QgsLayerTreeView>> tree_views;
//   std::unordered_map<std::uintptr_t, std::function<void(const std::string&)>> tree_sel_callbacks;
//   std::unordered_map<std::uintptr_t, QMetaObject::Connection> tree_sel_connections;
// （shutdown/析构/destroyCanvas 的清理路径同步断开/擦除，模式同 Task 5 的 connections）

std::uintptr_t QgisMapStack::createLayerTreeView(std::uintptr_t canvas_addr) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);  // 仅校验存活；树挂全局 root
  (void)canvas;
  QgsLayerTree* root = QgsProject::instance()->layerTreeRoot();
  auto* model = new QgsLayerTreeModel(root);  // 父对象由 view 接管前临时无父——先挂到 view
  auto* view = new QgsLayerTreeView();
  model->setParent(view);
  model->setFlag(QgsLayerTreeModel::ShowLegend);
  model->setFlag(QgsLayerTreeModel::AllowNodeReorder);
  model->setFlag(QgsLayerTreeModel::AllowNodeRename);
  model->setFlag(QgsLayerTreeModel::AllowNodeChangeVisibility);
  view->setModel(model);
  const auto addr = reinterpret_cast<std::uintptr_t>(view);
  impl_->tree_views[addr] = view;
  return addr;
}

QgsLayerTreeView* QgisMapStack::treeViewOrThrow(std::uintptr_t address) const {
  const auto it = impl_->tree_views.find(address);
  if (it == impl_->tree_views.end() || it->second.isNull()) {
    throw std::invalid_argument("layer tree view address no longer valid");
  }
  return it->second.data();
}

void QgisMapStack::setTreeSelectionCallback(
    std::uintptr_t tree_addr, std::function<void(const std::string&)> callback) {
  QgsLayerTreeView* view = treeViewOrThrow(tree_addr);
  impl_->tree_sel_callbacks[tree_addr] = std::move(callback);
  if (impl_->tree_sel_connections.contains(tree_addr)) {
    QObject::disconnect(impl_->tree_sel_connections[tree_addr]);
  }
  impl_->tree_sel_connections[tree_addr] = QObject::connect(
      view, &QgsLayerTreeView::currentLayerChanged, view,
      [this, tree_addr](QgsMapLayer* layer) {
        const auto it = impl_->tree_sel_callbacks.find(tree_addr);
        if (it == impl_->tree_sel_callbacks.end() || !it->second) return;
        if (impl_->tree_views.value(tree_addr).isNull()) return;
        std::string id;
        if (layer != nullptr) {
          const QVariant doc = layer->customProperty(QStringLiteral("pwb/doc_id"));
          id = (doc.isValid() && !doc.toString().isEmpty())
                   ? doc.toString().toStdString()
                   : layer->id().toStdString();
        }
        it->second(id);
      });
}
```

```cpp
// bindings.cpp 追加（mapstack 子模块，GIL 在绑定层）：
        .def("create_layer_tree_view", &pwb::qgis_render::QgisMapStack::createLayerTreeView)
        .def("tree_view_row_count", &pwb::qgis_render::QgisMapStack::treeViewRowCount)
        .def("tree_view_layer_name", &pwb::qgis_render::QgisMapStack::treeViewLayerName)
        .def("tree_view_set_current_row", &pwb::qgis_render::QgisMapStack::treeViewSetCurrentRow)
        .def("set_tree_selection_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t tree, py::function f) {
               self.setTreeSelectionCallback(
                   tree, [f = std::move(f)](const std::string& id) {
                     py::gil_scoped_acquire gil;
                     f(id);
                   });
             });
```

```python
# paleo_workbench/ui/qgis_stack/widgets.py 追加
class QgisLayerTreeHost(QWidget):
    """承载 QGIS 原生 QgsLayerTreeView 的 Qt 宿主（地址边界单点还原）。"""

    def __init__(self, stack, canvas_address: int, parent=None) -> None:
        super().__init__(parent)
        self.stack = stack
        self.canvas_address = canvas_address
        self.tree_view_address = stack.create_layer_tree_view(canvas_address)
        self.tree_view = wrap_widget(self.tree_view_address)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tree_view)
```

注意：
- `createLayerTreeView` 必须先于或独立于画布存在性可用——树挂的是 `layerTreeRoot` 全局单例；canvas 参数仅用于存活校验与未来扩展（如 MessageBar/缩放动作需要画布）。
- `shutdown()`/`~QgisMapStack()` 清理路径追加：`tree_sel_connections` 逐个 `disconnect` 后清空、`tree_sel_callbacks` 清空、`tree_views` 清空（QPointer 不自 delete，控件由 Qt 父子关系销毁；模式完全照 Task 5 fix 后的现有清理代码）。
- `destroyCanvas` 不影响树视图（树与画布无父子关系）；但若画布销毁后树仍存活是合法的（ QgsLayerTreeMapCanvasBridge 在 destroyCanvas 已清理）。

- [ ] **Step 4: 重编 + 运行**

```bash
cd /home/kevin/projects/paleo_project/main
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_layertree_embed.py -v
```
Expected: 2 passed（若树不显示图层：确认 `QgsLayerTreeRegistryBridge` 已由 QgsProject 自带走注册——`addMapLayer` 自动入树；确认 model rowCount 在事件循环后刷新）

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/qgis_stack/widgets.py tests/test_qgis_layertree_embed.py
git commit -m "feat(qgis): QgsLayerTreeView 创建嵌入 + 当前图层选择回调"
```

---

### Task 2: 增量镜像 reconcile（替换整树清空重建）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（upsert/补删/排序/可见性方法）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`（绑定）
- Modify: `paleo_workbench/ui/qgis_stack/canvas_shim.py`（`set_layer_snapshot` 改走 reconcile）
- Test: `tests/test_qgis_mapstack_reconcile.py`（新建）

**Interfaces:**
- Consumes: Task 1 的树；M1 的 `add_vector_layer_geojson`（本任务后保留为「无 doc_id 的 upsert 特例」或直接委托新 API——对外绑定保留不删）。
- Produces:
  - `upsert_mirror_layer(doc_id, name, geometry_type, crs_auth_id, geojson, renderer_xml, labeling_xml, legacy_style_json, visible, opacity) -> str`（按 `pwb/doc_id` customProperty 找本栈既有镜像：存在则就地更新要素（truncate+addFeatures）/样式（仅当 xml 变化时重设）/名称/不透明度/树勾选；不存在则新建（M1 的创建+样式路径）并登记 owned_layers。返回 QGIS layer id）
  - `remove_mirror_layers_except(doc_ids: list[str]) -> None`（仅移除本栈 owned 且 doc_id 不在清单内的镜像）
  - `set_mirror_layer_order(doc_ids_top_first: list[str]) -> None`（把本栈镜像在 layerTreeRoot 中按清单顺序排到顶部，保持彼此相对顺序；非本栈节点不动）
  - `set_mirror_layer_visibility(doc_id, visible) -> None`（程序化勾选，供 shim 使用；与树回调的去回声配合 Task 3）
  - `mirror_order_top_first() -> list[str]`（只读辅助：本栈镜像节点的顶层顺序 doc_id 列表）
  - `mirror_layer_visibility(doc_id) -> bool`（只读辅助：镜像节点当前勾选态）
- 对外契约不变：`canvas_shim.set_layer_snapshot` 语义不变（同步、完整反映 snapshot），只是内部从清空重建改为 reconcile。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_mapstack_reconcile.py
"""M2 Task 2: 增量镜像——未变图层的 QgsMapLayer 对象与树节点在 re-mirror 后保持不变。"""
import json

import pytest

pytest.importorskip("PySide6")

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
         "properties": {"name": "A1"}}
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_upsert_reuses_layer_object(stack):
    a = stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                                  json.dumps(_FC), "", "", "", True, 1.0)
    b = stack.upsert_mirror_layer("doc-b", "边界", "Point", "EPSG:4326",
                                  json.dumps(_FC), "", "", "", True, 1.0)
    a2 = stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                                   json.dumps(_FC), "", "", "", False, 0.8)
    assert a2 == a  # 同一镜像复用同一 QgsVectorLayer
    assert b != a


def test_remove_except_and_order(stack):
    ids = {}
    for doc in ("doc-1", "doc-2", "doc-3"):
        ids[doc] = stack.upsert_mirror_layer(doc, doc, "Point", "EPSG:4326",
                                             json.dumps(_FC), "", "", "", True, 1.0)
    stack.set_mirror_layer_order(["doc-3", "doc-1", "doc-2"])
    assert stack.mirror_order_top_first() == ["doc-3", "doc-1", "doc-2"]
    stack.remove_mirror_layers_except(["doc-1"])
    assert stack.project_layer_count() == 1
    stack.remove_mirror_layers_except([])
    assert stack.project_layer_count() == 0


def test_visibility_without_rebuild(stack):
    qid = stack.upsert_mirror_layer("doc-v", "v", "Point", "EPSG:4326",
                                    json.dumps(_FC), "", "", "", True, 1.0)
    stack.set_mirror_layer_visibility("doc-v", False)
    assert stack.mirror_layer_visibility("doc-v") is False
    stack.set_mirror_layer_visibility("doc-v", True)
    assert stack.mirror_layer_visibility("doc-v") is True
    # 对象未被替换
    assert stack.upsert_mirror_layer("doc-v", "v", "Point", "EPSG:4326",
                                     json.dumps(_FC), "", "", "", True, 1.0) == qid
```

（实现侧随之提供只读辅助绑定 `mirror_order_top_first() -> list[str]` 与 `mirror_layer_visibility(doc_id) -> bool`，已在上方 Produces 声明，供测试与 shim 使用。）

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_reconcile.py -v`
Expected: FAIL（`AttributeError: upsert_mirror_layer`）

- [ ] **Step 3: 实现**

C++ 要点（完整实现由执行者按此契约落地，关键代码必须包含）：

```cpp
// Impl 追加：std::unordered_map<std::string, std::string> mirror_by_doc;  // doc_id -> qgis layer id

// 查找辅助（file-static）：
static QgsVectorLayer* findMirrorByDocId(QgsProject* project, const std::string& doc_id) {
  for (auto* layer : project->mapLayers().values()) {
    if (layer->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString() == doc_id)
      return qobject_cast<QgsVectorLayer*>(layer);
  }
  return nullptr;
}
```

- `upsertMirrorLayer`：先 `findMirrorByDocId`；命中 → 就地更新：`dataProvider()->truncate()` 后 `addFeatures`（沿用 M1 的 `QgsJsonUtils::stringToFeatureList`，空 GeoJSON 抛 `std::invalid_argument`——沿用样式修复期的校验语义）、`updateExtents()`；`renderer_xml`/`labeling_xml`/`legacy_style_json` 与上一次应用的串比较（Impl 存 `mirror_style_sig: doc_id -> 三串拼接`），变化才 `applyStyleToLayer`；`setName(name)`；`setOpacity(clamp)`；树节点 `setItemVisibilityChecked(visible)`（**包在 Impl 的 `suppress_tree_callbacks` 计数器里**，Task 3 用）；未命中 → 走 M1 创建路径（含样式应用先于 addMapLayer），`layer->setCustomProperty("pwb/doc_id", doc_id)`，登记 `owned_layers` 与 `mirror_by_doc`。
- `removeMirrorLayersExcept`：遍历 `owned_layers`，凡有 `pwb/doc_id` 且不在清单的，`removeMapLayer` + 擦除 `owned_layers`/`mirror_by_doc`/`mirror_style_sig`；无 doc_id 的 owned 图层（M1 直加路径产物）视为「不在清单」一并移除——`clear_project_layers` 委托为 `remove_mirror_layers_except([])`。
- `setMirrorLayerOrder`：`QgsLayerTreeRoot` 操作——对每个 doc_id（倒序）找到 `findLayer(layerId)` 节点，`root->takeChild`/`insertChild(0, node)` 按清单顶部优先重排；非镜像节点保持在镜像块之后。实现细节允许用 `QgsLayerTree` 的 move 语义，但结果必须满足 `mirror_order_top_first()` 断言。
- `removeLayer(qgis_id)` 的 owned 语义保持；若目标有 doc_id，同步擦 `mirror_by_doc`。
- shutdown/destroyCanvas 清理：`mirror_by_doc`/`mirror_style_sig` 随 owned 清理（shutdown 只清本栈，语义不变）。

```python
# canvas_shim.py —— set_layer_snapshot 重写为 reconcile（替换 clear+循环 add 段）：
    def set_layer_snapshot(self, snapshot) -> None:
        """Mirror snapshot vector layers into the QGIS project (incremental).

        Note (M2): reconcile by ``pwb/doc_id`` — unchanged layers keep their
        QgsVectorLayer object, tree state and renderer across publishes.
        Note (F3 gap, tracked for M2+): legacy ``scale_range`` 仍未转发。
        """
        if getattr(self, "_shutdown_done", False):
            return
        if snapshot.project_crs:
            try:
                self.stack.set_destination_crs(self.canvas_address, str(snapshot.project_crs))
            except Exception:
                pass
        seen: list[str] = []
        for layer in snapshot.layers:
            if layer.layer_type != "vector":
                continue
            features = [...]  # 现有 FeatureCollection 组装逻辑原样保留
            if not features:
                continue
            geom = ...  # 现有 _GEOMETRY_TYPE 映射原样保留
            renderer_xml, labeling_xml, legacy_json = self._style_payload(layer)  # 提取逻辑从既有代码原样搬
            try:
                self.stack.upsert_mirror_layer(
                    layer.id, layer.name or layer.id, geom,
                    layer.crs or snapshot.project_crs,
                    json.dumps({"type": "FeatureCollection", "features": features}),
                    renderer_xml, labeling_xml, legacy_json,
                    bool(layer.visible), float(layer.opacity),
                )
            except Exception as exc:
                # 现有「样式错误抛出、其余 continue」门控逻辑原样保留
                ...
            seen.append(layer.id)
        try:
            self.stack.remove_mirror_layers_except(seen)
            self.stack.set_mirror_layer_order(seen)  # snapshot 顺序 = 顶层优先（与现有「index-1 = 上移」一致）
            self.stack.refresh_canvas(self.canvas_address)
        except Exception:
            pass
        try:
            self.backend_status_changed.emit(self.backend_status)
        except Exception:
            pass
```

- [ ] **Step 4: 重编 + 运行**

```bash
cd /home/kevin/projects/paleo_project/main
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -q tests/test_qgis_mapstack_reconcile.py tests/test_qgis_mapstack_style.py tests/test_qgis_mapstack_layers.py tests/test_composite_qgis_canvas.py tests/test_composite_gis.py
```
Expected: 全绿（M1 既有测试语义不得变红；`test_qgis_mapstack_style.py` 的双重镜像红色保持断言是 reconcile 的正确性护栏）

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/qgis_stack/canvas_shim.py tests/test_qgis_mapstack_reconcile.py
git commit -m "feat(qgis): 增量镜像 reconcile——未变图层保持对象/树态/样式"
```

---

### Task 3: 树操作回写文档模型（可见性/排序/重命名，去回声）✅ 已实现（925fcf7a）

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（树变更回调：可见性/顺序/重命名 + suppress 计数器绑定）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Create: `paleo_workbench/ui/qgis_stack/tree_sync.py`（`TreeChangeSet`/`parse_tree_change`）
- Test: `tests/test_qgis_layertree_writeback.py`（新建，5 例全绿）

**Interfaces（as-built）:**
- `set_tree_change_callback(tree_view, callback) -> None`：callback 收 JSON 串 `{"visibility": {doc_id: bool}, "order": [doc_id...], "renames": {doc_id: name}}`，只含本次实际变更；程序化 reconcile 期间（suppress 计数 >0）不触发。
- 用户语义驱动绑定（不包 SuppressGuard，刻意触发回调）：`tree_view_set_row_checked(tree, row, checked)` / `tree_view_rename_row(tree, row, name)` / `tree_view_move_row(tree, from, to)`。
- Python 侧 `tree_sync.py`：`parse_tree_change(payload) -> TreeChangeSet`（frozen dataclass，Task 4 由面板消费）。

**实现要点（as-built，替代原草图）:**
- 排序监听挂 `rowsInserted`/`rowsRemoved`（顶层 parent 过滤），**不是** `rowsMoved`——QGIS 的节点移动（含用户 DnD：insertChildNodes + removeRows）不发 rowsMoved；flush 经 `QTimer::singleShot(0)` 按 tick 合并（`tree_pending` + `tree_flush_scheduled`）。
- `QgsLayerTreeModel::setData(CheckStateRole)` 对叶子节点经 `visibilityChanged`→`nodeVisibilityChanged` 发**空 roles** 的 `dataChanged`；刷新类 dataChanged 也是空 roles，无法按 roles 区分——用**影子表**区分真实变更：`known_layer_names`（重命名）与 `known_layer_visibility`（勾选态），程序化写入处（upsert 两路径 / `setMirrorLayerVisibility` / M1 `setLayerVisibility`）同步影子；首次见面只建基线不上报；镜像擦除辅助（`eraseMirrorBy*`）同步清影子。
- `QgsLayerTreeModel::setData(EditRole)` 落地后 fallthrough 到 `QAbstractItemModel::setData` 返回 false——返回值不可用作成败依据，以节点名核验。
- `treeViewMoveRow` 必须与 QGIS DnD 同序：**先插入同 layer 新节点、再移除旧节点**（registry bridge `groupRemovedChildren` 按 findLayer 跳过仍在树中的图层）；先 take 后插会被 QueuedConnection 延迟删除把图层从 project 误删。旧节点 takeChild 后需手动 delete（orphan 不销毁）。
- `qobject_cast<QgsLayerTreeModel*>(view->model())` 在该类上不可靠（调试实测返回 null）——model 指针在创建时直存 `Impl::tree_models`。
- 清理路径（dtor/shutdown）：`tree_change_connections`（vector）逐个断开，`tree_change_callbacks`/`tree_pending`/`tree_flush_scheduled`/`known_layer_names`/`known_layer_visibility`/`tree_models` 清空。

---

### Task 4: QgisLayerTreePanel 替换 LayerManagerPanel（挂接 dock + 右键菜单 + 回写落地）

**Files:**
- Create: `paleo_workbench/ui/qgis_stack/layer_tree_panel.py`（`QgisLayerTreePanel`）
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（自实现 menu provider + 菜单动作回调）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Modify: `paleo_workbench/ui/workstation/composite_document.py`（面板替换挂接，最小改动）
- Test: `tests/test_qgis_layer_panel.py`（新建）；按需适配 `tests/test_composite_gis.py`/`test_workstation_shell.py` 中直接戳 `LayerManagerPanel.tree` 内部的断言（仅当替换导致其失效时——优先保持适配层兼容）

**Interfaces:**
- Consumes: Task 1–3 全部；`LayerManagerPanel` 的既有接缝（15 个请求信号 + `bind`/`select_layer`/`layer_by_id`/`set_layer_visible`/`set_layer_opacity`/`move_layer`/`set_editing_layer` + `_layers` 读取）。
- Produces:
  - `QgisLayerTreePanel(QWidget)`：CompositeDocument 的 drop-in 替换——同名信号（`create_layer_requested`/`remove_layer_requested(str)`/`rename_layer_requested(str)`/`import_reference_requested`/`remove_reference_requested(str)`/`refresh_reference_requested(str)`/`toggle_reference_snap_requested(str)`/`attribute_table_requested(str)`/`toggle_editing_requested(str)`/`properties_requested(str)`/`symbology_requested(str)`/`labeling_requested(str)`/`duplicate_layer_requested(str)`/`export_layer_requested(str)`/`repair_layer_requested(str)`/`active_layer_changed(object)`），同名方法（`bind(canvas, layers)`/`set_project_crs(crs)`/`select_layer(id)`/`layer_by_id(id)`/`set_layer_visible`/`set_layer_opacity`/`move_layer`/`set_editing_layer`），`self._layers` 保持可读（`list[MapLayerSnapshot]`，回写时同步更新）。
  - C++：`set_tree_menu_callback(tree_view, callback) -> None`（`callback(action_key, doc_layer_id)`）；menu provider 在 C++ 侧组装：QGIS 默认动作（`actionRenameGroupOrLayer`/`actionRemoveGroupOrLayer`/`actionZoomToLayers`/`actionShowFeatureCount`）+ 自定义动作键（`"properties"`/`"symbology"`/`"labeling"`/`"attribute_table"`/`"toggle_editing"`/`"duplicate"`/`"export"`/`"repair"`/`"create_layer"`/`"import_reference"`/`"remove_reference"`/`"refresh_reference"`/`"toggle_reference_snap"`），自定义动作触发菜单回调，Python 侧映射到对应请求信号。
  - `zoom_to_layer(tree_view, doc_id) -> None`（C++ 直接做：extent → canvas；不经 Python 回环）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_layer_panel.py
"""M2 Task 4: QgisLayerTreePanel 作为 LayerManagerPanel 的 drop-in 替换。"""
import json

import pytest

pytest.importorskip("PySide6")

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


def _snapshot(layers):
    from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=tuple(layers))


def _layer(layer_id, name, visible=True):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    return MapLayerSnapshot(
        id=layer_id, name=name, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(_FC["features"][0],), style={}, renderer_payload=None,
        source_version_id="", metadata={}, scale_range=None,
        visible=visible, opacity=1.0,
    )


def test_panel_bind_mirrors_layers_and_emits_active(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    active = []
    panel.active_layer_changed.connect(active.append)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_host.tree_view.model().rowCount() >= 2, timeout=3000)
    panel.select_layer("doc-b")
    qtbot.waitUntil(lambda: active and active[-1] == "doc-b", timeout=2000)


def test_tree_visibility_writes_back_to_panel_layers(qtbot, qapp):
    from PySide6.QtCore import Qt
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    canvas.show()
    panel.show()
    model = panel.tree_host.tree_view.model()
    qtbot.waitUntil(lambda: model.rowCount() >= 1, timeout=3000)
    model.setData(model.index(0, 0), Qt.Unchecked, Qt.CheckStateRole)
    qtbot.waitUntil(lambda: panel.layer_by_id("doc-a").visible is False, timeout=2000)
```

（`MapLayerSnapshot` 的字段名/构造以 `paleo_workbench/mapping/map_render_backend.py:68` 实际定义为准——执行者先读定义再写测试，字段不符时适配测试构造器，不得改 snapshot 定义。）

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_layer_panel.py -v`
Expected: FAIL（`ModuleNotFoundError: paleo_workbench.ui.qgis_stack.layer_tree_panel`）

- [ ] **Step 3: 实现**

C++ menu provider（执行者补全，关键结构）：

```cpp
// map_stack_service.cpp 内（file-static）：
class PwbLayerTreeMenuProvider : public QgsLayerTreeViewMenuProvider {
 public:
  PwbLayerTreeMenuProvider(QgsLayerTreeView* view, QgsMapCanvas* canvas,
                           std::function<void(const std::string&, const std::string&)> cb)
      : view_(view), canvas_(canvas), cb_(std::move(cb)) {}

  QMenu* createContextMenu() override {
    auto* menu = new QMenu();
    auto* actions = view_->defaultActions();
    const QModelIndex idx = view_->currentIndex();
    QgsMapLayer* layer = view_->currentLayer();
    if (layer != nullptr) {
      menu->addAction(actions->actionZoomToLayers(canvas_, menu));
      menu->addAction(actions->actionShowFeatureCount(menu));
      menu->addSeparator();
      menu->addAction(actions->actionRenameGroupOrLayer(menu));
      menu->addAction(actions->actionRemoveGroupOrLayer(menu));
      menu->addSeparator();
      addCustom(menu, QStringLiteral("图层属性…"), "properties", layer);
      addCustom(menu, QStringLiteral("符号系统…"), "symbology", layer);
      addCustom(menu, QStringLiteral("标注…"), "labeling", layer);
      addCustom(menu, QStringLiteral("打开属性表"), "attribute_table", layer);
      addCustom(menu, QStringLiteral("开始/停止编辑"), "toggle_editing", layer);
      addCustom(menu, QStringLiteral("复制图层"), "duplicate", layer);
      addCustom(menu, QStringLiteral("导出图层…"), "export", layer);
      addCustom(menu, QStringLiteral("修复无效几何…"), "repair", layer);
      // 引用图层动作（依 customProperty pwb/reference 判断后追加）：
      //   "remove_reference" / "refresh_reference" / "toggle_reference_snap"
    } else {
      addCustom(menu, QStringLiteral("新建矢量图层"), "create_layer", nullptr);
      addCustom(menu, QStringLiteral("导入参考图层"), "import_reference", nullptr);
    }
    return menu;
  }

 private:
  void addCustom(QMenu* menu, const QString& text, const char* key, QgsMapLayer* layer) {
    menu->addAction(text, menu, [this, key, layer]() {
      if (!cb_) return;
      std::string doc;
      if (layer) doc = layer->customProperty(QStringLiteral("pwb/doc_id")).toString().toStdString();
      cb_(key, doc);
    });
  }
  QgsLayerTreeView* view_; QgsMapCanvas* canvas_;
  std::function<void(const std::string&, const std::string&)> cb_;
};
```

- `setTreeMenuCallback`：setMenuProvider（view 接管所有权；重设前先把旧 provider 置空防悬垂）；回调存储/断开模式同 Task 5。
- 引用图层标记：Task 2 的 `upsert_mirror_layer` 尚无 reference 标记——在 customProperty 上增加 `pwb/reference`（"true"/""），shim 侧 reconcile 时按 `layer.metadata.get("reference")` 写入。本任务给它加一个**带默认值的**尾参 `is_reference: bool = False`（pybind11 `py::arg("is_reference") = false`），Task 2 既有测试的 10 参调用不受影响。

Python `layer_tree_panel.py`（骨架，执行者补全接缝方法）：

```python
class QgisLayerTreePanel(QWidget):
    """QgsLayerTreeView 承载的图层管理面板——LayerManagerPanel 的 drop-in 替换。"""

    create_layer_requested = Signal()
    remove_layer_requested = Signal(str)
    # …15 个请求信号 + active_layer_changed，签名与 LayerManagerPanel 完全一致

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: list = []
        self._canvas = None
        self._project_crs = ""
        self._editing_layer_id = None
        self._suppress_writeback = False
        # 顶部工具行：新建/导入/删除按钮 + 不透明度滑杆（复用既有交互）
        # 中部：QgisLayerTreeHost（bind 时创建，需 canvas）
        # 布局 margins 0、占满面板

    def bind(self, canvas, layers) -> None:
        self._canvas = canvas
        self._layers = list(layers)
        if self.tree_host is None:
            self.tree_host = QgisLayerTreeHost(canvas.stack, canvas.canvas_address, self)
            self._layout.addWidget(self.tree_host.tree_view, 1)
            # 接回调：selection → active_layer_changed；change → _apply_tree_change；menu → 信号映射
        self._canvas.set_layer_snapshot(self._make_snapshot())  # reconcile 入树

    def _make_snapshot(self):
        """由 self._layers/self._project_crs 组装 MapRenderSnapshot（与
        LayerManagerPanel._publish 的构造一致）。"""
        from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot
        return MapRenderSnapshot(
            project_crs=self._project_crs or "EPSG:4326",
            layers=tuple(self._layers),
        )

    def _apply_tree_change(self, payload: str) -> None:
        if self._suppress_writeback:
            return
        changes = parse_tree_change(payload)
        # visibility：self._layers 中 replace(layer, visible=...)；持久化与既有路径一致——
        #   直接调用自身 set_layer_visible 的「模型更新」部分但不触发 _publish 回推
        #   （画布已由 QgsLayerTreeMapCanvasBridge 同步；写回 _display 由
        #    CompositeDocument._sync_composition_now 的既有 apply_display_state 承担）
        # order：按 changes.order 重排 self._layers（仅镜像层；非镜像层保持原位）
        # renames：发 rename_layer_requested? 否——重命名已在树上生效，直接更新 self._layers
        #   名称并走 edit_controller 持久化路径（由 _sync_composition_now 既有逻辑落地）
```

关键语义（执行者必须保持）：
- 树勾选 → 只更新 `self._layers`（`dataclasses.replace`）+ 不调用 `_publish`（防回环）；`CompositeDocument._sync_composition_now` 的既有 `apply_display_state(display.values())` 路径在下次组合同步时把可见性/顺序/不透明度写进 `edit_controller._display` 与工程文件——为让回写不依赖「下次」，`_apply_tree_change` 末尾调用 `CompositeDocument` 既有的轻量同步入口（若需新增一个 `notify_display_changed()` 小方法到 CompositeDocument，允许，控制在 10 行内：内部调 `apply_display_state` + `_apply_reference_display_state` + 持久化，不重建快照）。
- `set_layer_visible`/`set_layer_opacity`/`move_layer`（外部调用方=CompositeDocument 属性应用路径）→ 更新 `self._layers` + `self._canvas` 的 `set_mirror_layer_visibility`/upsert，而非整树 `_publish`。
- `select_layer` → 树中定位 doc_id 节点 `setCurrentIndex`。
- `set_editing_layer` → 树节点 `setCustomProperty` 或 Qt 委托暂以现有 ✏ 语义不可用时，接受「无视觉前缀」并在报告中注明（M2 不阻塞）。
- `composite_document.py` 的挂接改动 = 构造处 `LayerManagerPanel()` → `QgisLayerTreePanel()` + import，其余不动。

- [ ] **Step 4: 重编 + 运行**

```bash
cd /home/kevin/projects/paleo_project/main
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -q tests/test_qgis_layer_panel.py tests/test_qgis_layertree_writeback.py tests/test_qgis_layertree_embed.py tests/test_qgis_mapstack_reconcile.py tests/test_composite_gis.py tests/test_workstation_shell.py tests/test_composite_qgis_canvas.py
```
Expected: 全绿（composite_gis / workstation_shell 若因替换出现断言失配，逐条判断：接缝保持则不应红；红了先修接缝兼容，确属内部实现耦合的测试可适配并说明）。

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/qgis_stack/ paleo_workbench/ui/workstation/composite_document.py tests/
git commit -m "feat(qgis): QgsLayerTreeView 图层管理面板替换 LayerManagerPanel"
```

---

### Task 5: 原生 QgsVectorLayerProperties 属性对话框

**Files:**
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp`（`execLayerProperties`）
- Modify: `native/qgis_render_bridge/src/bindings.cpp`
- Modify: `paleo_workbench/ui/workstation/composite_document.py`（`_open_layer_properties` 在画布为 QGIS 栈时走原生对话框）
- Test: `tests/test_qgis_layer_properties.py`（新建）

**Interfaces:**
- Consumes: Task 2 的镜像（doc_id → QgsVectorLayer）；`style_codec` 的 `renderer_to_xml`。
- Produces:
  - `exec_layer_properties(canvas, doc_id) -> dict`（模态打开 `QgsVectorLayerProperties`（矢量）/`QgsRasterLayerProperties`（栅格镜像暂不出现，矢量外类型抛 invalid_argument）；返回 `{"ok": bool, "renderer_xml": str, "labeling_xml": str, "opacity": float, "name": str}`；Cancel → `{"ok": False}`）
  - Python：`CompositeDocument._open_layer_properties` 在 `self.canvas` 为 `QgisCanvasShim` 时调用上述绑定，`ok` 后把结果走既有 `_apply_layer_properties` 等价路径写回（`qgis_style` payload：renderer_xml/labeling_xml + revision 递增；name/opacity 同步），`_sync_composition` 持久化。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_qgis_layer_properties.py
"""M2 Task 5: 原生 QgsVectorLayerProperties 对话框 exec 与结果回写。"""
import json

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_exec_properties_cancel_returns_not_ok(qtbot, stack):
    canvas = stack.create_canvas()
    stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0)
    # offscreen：自动 reject 模态对话框
    QTimer.singleShot(300, lambda: [w.reject() for w in qapp.activeModalWidget().findChildren(QDialog)] or (qapp.activeModalWidget() and qapp.activeModalWidget().reject()))
    result = stack.exec_layer_properties(canvas, "doc-a")
    assert result["ok"] is False


def test_exec_properties_accept_returns_renderer_xml(qtbot, stack):
    canvas = stack.create_canvas()
    stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0)

    def auto_accept():
        w = qapp.activeModalWidget()
        if w is not None:
            w.accept()
        else:
            QTimer.singleShot(100, auto_accept)

    QTimer.singleShot(100, auto_accept)
    result = stack.exec_layer_properties(canvas, "doc-a")
    assert result["ok"] is True
    assert "<renderer" in result["renderer_xml"]
    assert 0.0 < result["opacity"] <= 1.0
    assert result["name"] == "井位"
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_layer_properties.py -v`
Expected: FAIL（`AttributeError: exec_layer_properties`）

- [ ] **Step 3: 实现**

```cpp
// map_stack_service.cpp（关键结构，执行者补全）：
#include <qgsvectorlayerproperties.h>
#include <qgsrasterlayerproperties.h>
// #include <qgsmessagebar.h> 如需非空 messageBar，可先 nullptr

std::map<std::string, std::string> QgisMapStack::execLayerProperties(
    std::uintptr_t canvas_addr, const std::string& doc_id) {
  QgsMapCanvas* canvas = canvasOrThrow(canvas_addr);
  QgsMapLayer* layer = findMirrorByDocId(QgsProject::instance(), doc_id);
  if (layer == nullptr) throw std::invalid_argument("unknown mirror layer: " + doc_id);
  // GUI 线程断言沿用 gui_service.cpp 的 assert_gui_thread 模式（提取共享或内联同款检查）
  int code = QDialog::Rejected;
  if (auto* vec = qobject_cast<QgsVectorLayer*>(layer)) {
    QgsVectorLayerProperties dialog(canvas, nullptr, vec);
    code = dialog.exec();
  } else if (layer->type() == Qgis::LayerType::Raster) {
    QgsRasterLayerProperties dialog(layer, canvas);
    code = dialog.exec();
  } else {
    throw std::invalid_argument("unsupported layer type for properties dialog");
  }
  std::map<std::string, std::string> result;
  result["ok"] = code == QDialog::Accepted ? "1" : "0";
  if (code == QDialog::Accepted) {
    if (auto* vec = qobject_cast<QgsVectorLayer*>(layer)) {
      if (vec->renderer() != nullptr)
        result["renderer_xml"] = renderer_to_xml(*vec->renderer());
      if (vec->labelsEnabled() && vec->labeling() != nullptr) {
        QDomDocument doc;
        QgsReadWriteContext ctx;
        QDomElement el = vec->labeling()->save(doc, ctx);  // 若 save 签名不同按 4.2 头文件适配
        doc.appendChild(el);
        result["labeling_xml"] = doc.toString().toStdString();
      }
    }
    result["opacity"] = std::to_string(layer->opacity());
    result["name"] = layer->name().toStdString();
    layer->triggerRepaint();
  }
  return result;
}
```

```cpp
// bindings.cpp：返回 py::dict（GIL 在绑定层；exec 期间不得长期持锁阻塞 Qt 事件——
// 模态 exec 自旋本地事件循环，pybind11 调用本身在 GUI 线程，保持默认持锁即可，
// 与 gui_service 的既有对话框绑定同模式）
        .def("exec_layer_properties",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                const std::string& doc_id) {
               auto raw = self.execLayerProperties(canvas, doc_id);
               py::dict out;
               out["ok"] = raw["ok"] == "1";
               if (raw["ok"] == "1") {
                 out["renderer_xml"] = raw["renderer_xml"];
                 out["labeling_xml"] = raw["labeling_xml"];
                 out["opacity"] = std::stod(raw["opacity"]);
                 out["name"] = raw["name"];
               }
               return out;
             });
```

```python
# composite_document.py —— _open_layer_properties 前段分流（保持其余逻辑不变）：
    def _open_layer_properties(self, layer_id, focus=""):
        from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
        if isinstance(self.canvas, QgisCanvasShim):
            result = self.canvas.stack.exec_layer_properties(
                self.canvas.canvas_address, str(layer_id))
            if result.get("ok"):
                self._apply_native_layer_properties(str(layer_id), result)
            return
        # … 既有 MapLayerPropertiesDialog 路径原样保留（其他页面仍在用）
```

`_apply_native_layer_properties`（新方法，复用既有写回语义）：`name` → `edit_controller.rename_layer`（若变）；`opacity` → `layer_manager.set_layer_opacity`；`renderer_xml`/`labeling_xml` → 构造 `qgis_style` payload（沿用 `composite_document.py:1171` 的既有结构，`revision` 取旧值+1）→ `controller.set_layer_style` → `_sync_composition`。

- [ ] **Step 4: 重编 + 运行**

```bash
cd /home/kevin/projects/paleo_project/main
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -q tests/test_qgis_layer_properties.py tests/test_composite_gis.py tests/test_qgis_mapstack_style.py tests/test_qgis_mapstack_reconcile.py
```
Expected: 全绿（accept 用例 offscreen 下 `activeModalWidget` 时序若不稳，允许循环 singleShot 重试至 3s 上限；对话框必须真 exec，不得 mock）。

- [ ] **Step 5: Commit**

```bash
git add native/qgis_render_bridge/src/ paleo_workbench/ui/workstation/composite_document.py tests/test_qgis_layer_properties.py
git commit -m "feat(qgis): 原生 QgsVectorLayerProperties 图层属性对话框接入综合编修区"
```

---

### Task 6: M2 收尾——右键菜单动作端到端 + 全量回归 + 文档

**Files:**
- Test: `tests/test_qgis_layer_panel_menu.py`（新建）
- Modify: `README.md` / `CLAUDE.md`（M2 状态更新）
- Modify: `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`（仅当执行发现与 spec 有出入时补注）

**Interfaces:**
- Consumes: Task 1–5 全部。
- Produces: M2 DoD 验证 + 文档更新。

- [ ] **Step 1: 菜单动作端到端测试**

```python
# tests/test_qgis_layer_panel_menu.py
"""M2 Task 6: 图层树右键菜单自定义动作触发对应请求信号。"""
import json

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QMenu

# 面板构造/fixture 复用 test_qgis_layer_panel.py 的 _layer 构造器（读该文件照搬）


def test_menu_attribute_table_action_emits(qtbot, qapp, monkeypatch):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel
    from test_qgis_layer_panel import _layer

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    canvas.show()
    panel.show()
    tree = panel.tree_host.tree_view
    qtbot.waitUntil(lambda: tree.model().rowCount() >= 1, timeout=3000)
    panel.select_layer("doc-a")
    received = []
    panel.attribute_table_requested.connect(received.append)

    triggered = {"done": False}

    def click_menu():
        menu = qapp.activePopupWidget()
        if isinstance(menu, QMenu):
            for action in menu.actions():
                if action.text() == "打开属性表":
                    action.trigger()
                    triggered["done"] = True
                    return
            menu.close()
            triggered["done"] = True
        else:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, click_menu)

    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, click_menu)
    # 触发菜单：直接调 view 的 menuProvider（offscreen 右键事件路径不稳时，
    # 允许从 QgsLayerTreeView 的 customContextMenuRequested 等价入口触发）
    tree.customContextMenuRequested.emit(QPoint(5, 5))
    qtbot.waitUntil(lambda: triggered["done"], timeout=3000)
    qtbot.waitUntil(lambda: received == ["doc-a"], timeout=2000)
```

- [ ] **Step 2: 运行确认失败 → 修复至通过**（若 Task 4 已天然满足则直接 GREEN，仍须保留测试）

- [ ] **Step 3: 全量回归**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main --deselect tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout --basetemp=$(mktemp -d)
```
Expected: 与 M1 基线对账——只允许预存的 52 failed / 2 errors（缺 layer_model_core/grid_render_core/map_edit_core 的环境性失败 + test_app_close_dead_shell 2 项）；新增任何红都是本任务要修的。M1/M2 核心套件必须全绿。

- [ ] **Step 4: 文档**

- `README.md`「QGIS 原生地图栈」节追加 M2 状态：图层管理（QgsLayerTreeView）与图层属性（QgsVectorLayerProperties）已由 QGIS 原生控件承载；其余页面仍走 UnifiedMapCanvas + fallback，M4 拆除。
- `CLAUDE.md`「地图栈」节同步一句。

- [ ] **Step 5: Commit**

```bash
git add tests/test_qgis_layer_panel_menu.py README.md CLAUDE.md
git commit -m "docs(qgis): M2 收尾——菜单端到端测试 + 文档状态更新"
```

---

## As-built 决策记录（M2 终局审查后补记，2026-09-04）

- **旧面板三件 UI 资产显式不保留**（终局审查 I4 的"显式记录接受"选项）：
  - 上移/下移按钮：由 QgsLayerTreeView 原生拖拽取代（QGIS 桌面语义即如此，
    无按钮）；`move_layer` 接口保留供程序化调用。
  - 图例列表（WORKAREA_LEGEND_ITEMS）：工区级固定装饰说明，与图层内容无关，
    属旧面板私有 chrome，接受删除。
  - 名称搜索框：QGIS 桌面图层面板确有名称过滤框——列为 M3 入口候选
    （与编辑 UI 一并评估，届时走 QgsLayerTreeFilterProxyModel 路线）。
  - 「参与捕捉（切换）」菜单项无勾选态：捕捉参与状态权威在 Python 侧
    （参考图层 snap 集合），C++ 菜单侧无源可同步，暂为 plain toggle；
    M3 捕捉设置面板接入时一并归一。
- **rename 不经请求信号**：`rename_layer_requested` 面板信号已删除——树内
  改名直接生效并经 `_on_tree_change` → `apply_display_state` 写回编辑权威
  （C1 修复后 name 也经 `rename_layer` 落地持久化）。

## M2 完成定义（DoD）

1. 综合编修区图层管理面板为真 `QgsLayerTreeView`：图例图标、勾选可见性、拖拽排序、F2/右键重命名、右键菜单（含 QGIS 默认动作）可用。
2. 图层属性对话框为真 `QgsVectorLayerProperties`（符号系统页 = QGIS 桌面同款 `QgsRendererPropertiesDialog`）；应用后样式/名称/不透明度回写工程持久化。
3. 树的用户操作（可见性/排序/重命名）回写文档模型并持久化；程序化 reconcile 无回声；re-mirror 不再重建未变图层（颜色/树态稳定）。
4. 全部新增与既有测试绿（预存环境性失败除外，需对账）；fallback 保留未动。
5. 用户真机确认。

## 显式不在 M2 范围

- 编辑类 `QgsMapTool`（顶点编辑/捕捉/撤销重做）、编辑中图层的铅笔标记视觉（M3）。
- `QgsAttributeTable` 原生属性表（当前自绘 `CompositeAttributeTableDialog` 保留；是否换原生另行评估）。
- 图层树 embedded widget（QGIS 桌面那种内嵌透明度滑杆）；不透明度仍由面板顶部滑杆/属性对话框承担。
- 工程文件持久化往返结构变化、fallback 拆除（M4）。
- scale_range 转发（M1 已标注的遗留项，列入 M2 backlog 但不阻塞本里程碑）。
