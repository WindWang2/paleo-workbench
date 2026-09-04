# QGIS 原生地图栈 M4（本切片）：只读页真画布 + 自有 QgsProject

- 日期：2026-09-04
- 状态：已批准（用户 2026-09-04 确认方案 3）
- 父 spec：`docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`
- 前置：M1（`70c9811e`）/ M2（`55fcb640`）/ M3（本地 `52550ee9`）已交付综合编修区；本切片不重开编修栈

## 目标

综合编修区以外的三张地图（首页、工区图、编图页预览）改为嵌入真 `QgsMapCanvas`，交互只读（平移/缩放 + 单击拾取），**各自持有独立 `QgsProject`**，不与综合编修的 `QgsProject::instance()` 抢图层。

成功标准：

1. 首页 / 工区图 / 编图预览在桥可用时看到的是 `QgsMapCanvas`，不是 `UnifiedMapCanvas` 的帧图。
2. 综合编修 `set_layer_snapshot` 不会删除首页工区层；只读页 reconcile 不会删除编修镜像层。
3. 首页/工区图单击井位（无拖拽）仍发既有信号；比例尺/指北针/选中井高亮仍可见。
4. 无桥环境（主 CI）继续走 `UnifiedMapCanvas` + fallback，测试不因此变红。
5. Task 0：M3 真机回归（工具包装未装、cadDock 漏显示）合入后再迁页面。

## 非目标（本切片不做）

原父 spec §10「M4 收尾」里下列项**推迟**，不在本切片：

- 工程文件嵌入 mini-`QgsProject` XML（当前 `user_vector_layers` + `qgis_style` 已够用）
- 拆除 fallback / 删除 `qgis_backend_probe` / `PALEO_DISABLE_QGIS_RENDERER`
- 把 `mapping_page` 的 `MapEditView`（QGraphics 制图编辑器）换成原生编辑工具
- 把综合编修迁出 `QgsProject::instance()`
- 修 QGIS CI 专轨跑不通（#1147）
- 退役 `VectorEditSession`（M3 铁律已否决父 spec §6）

井 / 地震 / 测井页面仍不是 QGIS 图层域（父 spec 非目标不变）。

## 约束（沿用 M1–M3）

- 不依赖系统 QGIS；只走 vendored `third_party/qgis`。
- 进程内只有 PySide6。控件以 `uintptr_t` 过桥，`shiboken6.wrapInstance` 还原。
- `map_stack_service.cpp` 禁止 pybind11 / Python.h；GIL 只在 `bindings.cpp`。
- 回调销毁走孤儿坟场（禁止在 `destroyed` 里拆含 `py::function` 的 `std::function`）。
- 综合编修权威模型不变：Python 文档权威，QGIS 镜像；只读页同样是「快照 → 镜像」，不把井/地震实体变成 QGIS 编辑层。

## 现状（与本切片相关的差距）

| 表面 | 现在 | 问题 |
|---|---|---|
| 综合编修 `CompositeDocument` | `QgisCanvasShim` → `QgsProject::instance()` | 保持不动 |
| 首页 `home_page`、工区 `workarea_map_widget`、编图预览 `mapping_page.unified_canvas` | `UnifiedMapCanvas`；桥在时 `create_map_render_backend()` 走 QGIS **渲染器出帧**，不是 `QgsMapCanvas` | 本切片要换真画布 |
| `QgisMapStack::createCanvas` | 一律把 `QgsLayerTreeMapCanvasBridge` 接到 `instance()->layerTreeRoot()`，并建 cadDock | 只读页若走这条路径会进编修工程 |
| `QgisCanvasShim.set_layer_snapshot` | `remove_mirror_layers_except` 按本快照未见则删 | 共享 `instance()` 时会互删 |
| `QgisCanvasShim` | 无 `map_clicked`；`set_overlay_provider` 存而不画 | 首页/工区依赖这两项 |
| M3 真机 | `attach_canvas` 直传工具栈，shim 只认 `.tools`；cadDock 随父 `show` | Task 0 |

数据入口已经对齐：三页都调用 `set_layer_snapshot(MapRenderSnapshot)`。工区层 id 带 `home_workarea:` 前缀。井点击是 Python 像素容差命中，不是 QGIS identify。

## 架构

```
PySide6 页面
 └─ create_display_canvas()
     ├─ 桥可用 → QgisDisplayCanvas
     │    └─ QgisMapStack.initialize(display=True)
     │         ├─ 自有 QgsProject（非 instance()）
     │         ├─ QgsMapCanvas::setProject(owned)
     │         ├─ 不建 QgsLayerTreeMapCanvasBridge
     │         ├─ 不建 cadDock / 编辑工具
     │         └─ upsert 后 canvas.setLayers(本工程图层)
     └─ 桥不可用 → UnifiedMapCanvas（fallback，主 CI）

综合编修（不变）
 └─ QgisCanvasShim
      └─ QgisMapStack.initialize()          # display=False
           └─ QgsProject::instance()
```

进程里 `QgsApplication::initQgis()` 仍只做一次（已有 `initialized` 门 + 生命周期 mutex）。`instance()` 继续服务编修区。只读栈额外 `new QgsProject()`，在 `shutdown`/`dtor` 里先 `removeAllMapLayers` 再销毁工程对象。

## 组件

### 1. C++：`QgisMapStack` 的 display 模式

**文件：** `native/qgis_render_bridge/src/map_stack_service.{hpp,cpp}`，`bindings.cpp`

- `initialize()` 增加可选参数，默认保持现行为：

  ```cpp
  void initialize(bool display = false);
  ```

  Python：`initialize(display: bool = False)`。既有测试不改调用。

- `Impl` 增加 `std::unique_ptr<QgsProject> owned_project`。`display==true` 时构造。

- 统一入口：

  ```cpp
  QgsProject* project() const {
    return impl_->owned_project ? impl_->owned_project.get()
                                : QgsProject::instance();
  }
  ```

  `map_stack_service.cpp` 里现有 `QgsProject::instance()` 全部改为 `project()`（编修路径语义不变：`owned_project` 为空则仍是单例）。

- `createCanvas()`：
  - 编修：现状（tree bridge + cadDock，接 `project()` 即单例）。
  - display：`canvas->setProject(project())`；**不**建 `QgsLayerTreeMapCanvasBridge`；**不**建 cadDock；工具默认 `QgsMapToolPan`。
  - display 下 `setCanvasLayers` 的等价物：按 `project()->layerTreeRoot()` 当前顺序收集 `QgsMapLayer*`，`canvas->setLayers(...)`。所有会调用 `tree_bridge->setCanvasLayers()` 的路径在 display 且无 bridge 时走这条。

- `create_layer_tree_view` / 编辑工具 / cadDock API 在 display 栈上调用：抛 `std::runtime_error`（只读栈不是缩小版编修栈）。

- `shutdown()`：display 先 `destroyCanvas` 全部画布，再 `owned_project->removeAllMapLayers()`，再 `reset` unique_ptr。不得碰 `QgsProject::instance()`。

- `projectLayerCount()` 已走 `project()->count()`，隔离测试直接用它。

### 2. Python：`QgisDisplayCanvas`

**新建：** `paleo_workbench/ui/qgis_stack/display_canvas.py`

不继承 `QgisCanvasShim`（避免带上工具包装、树、digitize 回调）。与 `UnifiedMapCanvas` 对齐的只读契约：

| 成员 | 行为 |
|---|---|
| `set_layer_snapshot(snapshot)` | 复用 shim 的镜像循环（抽共享函数，禁止复制粘贴两份 upsert）；`remove_mirror_layers_except` 只作用于本栈 `project()` |
| `set_extent` / `view_extent` / `zoom_by` / `map_units_per_pixel` | 与 shim 相同，走桥 |
| `map_to_screen` / `screen_to_map` | 与 shim 相同 |
| `map_clicked(tuple)` | **新增。** 见下节 |
| `set_overlay_provider` | 存 + 画。见下节 |
| `shutdown()` | 本栈 `shutdown`，幂等；隐藏窗格由宿主在工程切换时调用（工区图已有此约定） |
| `backend_status` / `backend_status_changed` | 桥可用为 `"qgis"` |

**工厂** `create_display_canvas(parent=None) -> QWidget`：能 `import qgis_render_bridge.mapstack` 则返回 `QgisDisplayCanvas`，否则 `UnifiedMapCanvas`。三页只经工厂构造，禁止直接 `QgisDisplayCanvas()` 进生产页（测试可直构并 `pytest.importorskip`）。

镜像循环从 `QgisCanvasShim.set_layer_snapshot` 抽到 `paleo_workbench/ui/qgis_stack/mirror.py`（纯函数 + stack/canvas_address），shim 与 display 共用。行为不得变：零要素上树、`qgis_style`/`legacy`、`pwb/doc_id`。

### 3. 单击与叠加层

`QgsMapCanvas` 吃鼠标（pan 工具）。`QgisDisplayCanvas` 在包装后的 canvas 上装 event filter：

- 左键 press 记录位置；release 且曼哈顿距离 &lt; 6px → `map_clicked.emit(screen_to_map(pos))`（与 `UnifiedMapCanvas` 同阈值）。
- 拖拽交给原生 pan，不发 `map_clicked`。
- 滚轮缩放保持 QGIS 默认。

叠加层：canvas 上方一张 `WA_TransparentForMouseEvents` 的 sibling `QWidget`，`paintEvent` 调用既有 `UnifiedMapCanvas._paint_overlay` / `paint_map_decorations` 的同一套绘制（抽到 `paleo_workbench/ui/map_overlays.py` 若需要避免 display 依赖 unified 的私有方法；否则 display 直接调 `paint_map_decorations` + 复制选中井黄圈那段，**优先抽函数**）。鼠标穿透，点击仍到 canvas。

不把装饰做成 QGIS decoration item，不把井高亮做成桥内 `QgsHighlight`（本切片 YAGNI；编修区高亮路径不动）。

首页/工区的井命中算法（16px 容差、`well_id` 属性）留在页面，不进桥。

### 4. 三页替换

| 文件 | 改动 |
|---|---|
| `paleo_workbench/ui/pages/home_page.py` | `UnifiedMapCanvas()` → `create_display_canvas()`；信号/快照/extent API 不变 |
| `paleo_workbench/ui/pages/workarea_map_widget.py` | 同上；`shutdown()` 仍转给画布 |
| `paleo_workbench/ui/pages/mapping_page.py` | 仅 `self.unified_canvas`；`MapEditView` / `MapCanvasPanel` / 组图面板不动 |

`workstation_composite_prototype.py`、benchmark 仍可用 `UnifiedMapCanvas`（非生产路径）。

### 5. Task 0：M3 真机回归（先于页面替换提交）

工作树已有未提交补丁，本切片必须先合：

1. `canvas_shim.set_map_tool_controller`：对象自身有 `set_active_tool` 则视为工具栈（`attach_canvas` 直传 `self.tools`），否则再取 `.tools`。
2. `createCanvas` 里 cadDock 构造后 `hide()`（非浮动子控件会随父 show 被递归显示）。
3. 新测 `tests/test_qgis_tool_wiring.py`（tool-id→kind 整链 + cadDock 保持隐藏）。

不提交 `*_styles.db` / `symbology-style.db` / `user-history.db` / `.superpowers/`。cadDock 改动需重装 `qgis_render_bridge`。

## 数据流

```
ProjectDocument
  → build_workarea_map_snapshot / mapping snapshot（纯 Python，不变）
  → QgisDisplayCanvas.set_layer_snapshot
  → stack.upsert_mirror_layer 写入 owned QgsProject
  → canvas.setLayers(owned 图层)
  → QgsMapCanvas 渲染

单击
  → event filter map_clicked(map_xy)
  → HomePage/WorkAreaMapWidget 像素容差命中 wells 层
  → well_selected / well_activated（信号不变）
```

权威仍是 `ProjectDocument`。owned `QgsProject` 是该页的运行时镜像，不写回工程文件。

## 错误处理

- 工厂：桥缺失 → `UnifiedMapCanvas`，不抛到页面构造。
- `QgisDisplayCanvas` 直构（测试）：桥缺失 → 与 shim 相同的 `RuntimeError` 文案（含 `PALEO_WITH_QGIS_RENDERER=1 pip install -e native/qgis_render_bridge`）。
- display 栈误调树/编辑 API → C++ `runtime_error`，Python 测试断言。
- `set_layer_snapshot` 单层失败：与 shim 相同（无有效 renderer 则 skip 该层；有 renderer_xml 且报 invalid 则抛）。
- 生命周期：display `shutdown` 不得 `clear_project_layers` 到 `instance()`（shim 编修路径仍清自己的单例，那是编修契约）。

## 测试

跑法沿用 M3：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <args> -q --basetemp=$(mktemp -d)`。全量须 `--deselect tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`。看 `N passed/failed` 行，不看管道退出码。

| 文件 | 断言 |
|---|---|
| `tests/test_qgis_tool_wiring.py` | Task 0：activate_tool 映射 kind；cadDock `isHidden` |
| `tests/test_qgis_display_isolation.py` | 两个 display 栈互不影响 `projectLayerCount`；display upsert 后 `QgsProject.instance()` 层数不变（经桥暴露的 `project_layer_count` 在 authoring 栈上测单例） |
| `tests/test_qgis_display_canvas.py` | `set_layer_snapshot` 后画布非空；bare click 发 `map_clicked`；拖拽不发；`create_layer_tree_view` 抛错 |
| `tests/test_home_map_well_click.py` | 保留 UnifiedMapCanvas 单测；新增/改 HomePage 经工厂的井点击（无桥 skip 或走 fallback 原测） |
| 既有 `tests/test_qgis_*` 编修套件 | 全绿，证明 `project()` 替换没改 instance() 语义 |

不把 fallback 单测改成必依赖桥。

## 文档

- `README.md` / `CLAUDE.md` 地图栈段：M4 本切片后，首页/工区/编图预览在桥可用时也是 `QgsMapCanvas`（只读）；fallback 仍用于测试/主 CI；综合编修仍硬依赖桥。
- 父 spec §10 M4 行改为指向本文，并标明 XML 持久化与拆 fallback 为后续切片。

## 风险

1. `QgsProject::instance()` 机械替换漏一处 → 只读层写进单例。隔离测试必须卡住。
2. display 无 tree bridge 时漏 `setLayers` → 白画布。快照测试必须断言 canvas 图层数。
3. event filter 与 `QgsMapToolPan` 抢单击 → 井点不中。阈值与 UnifiedMapCanvas 对齐，回归 `test_home_map_well_click`。
4. 叠加层 widget 未穿透鼠标 → pan 失效。必须 `WA_TransparentForMouseEvents`。
5. 多份 `QgsProject` + 多次 `initialize`：`initialized` 门保证 `initQgis` 一次；第二份 display 只 new `QgsProject`。

## 里程碑顺序（本切片）

0. Task 0 真机回归（测试红 → 实现 → 绿 → 提交，不含 `.db`）
1. C++ `project()` + `initialize(display)` + display `createCanvas`
2. 隔离测试绿
3. `QgisDisplayCanvas` + 工厂 + overlay/click
4. 三页替换
5. 文档 + 编修回归 + 本切片测试

## 修订记录

- 2026-09-04：用户确认「D 然后 B」+ 隔离方案 3（只读栈自有 `QgsProject`，编修继续 `instance()`）。
