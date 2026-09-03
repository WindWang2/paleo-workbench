# Task 5 报告：原生 pan/zoom 工具 + extent/坐标信号回调

## 实现内容

- **C++ 层** `native/qgis_render_bridge/src/map_stack_service.{hpp,cpp}`:
  - `QgisMapStack::setMapTool(canvas, kind)` 支持 `"pan" / "zoomIn" / "zoomOut"`，分别创建 `QgsMapToolPan` / `QgsMapToolZoom(canvas, false/true)`，存于 `Impl::tools` 并 `canvas->setMapTool()`。未知 kind 抛 `invalid_argument`。
  - `setExtentCallback` / `setXyCallback` 存 `std::function`，`QObject::connect` 到 `QgsMapCanvas::extentsChanged` / `xyCoordinates`，回调中取 `canvas->extent()` / `QgsPointXY` 并转发。保持纯 Qt/C++ 单元，不引入 pybind11。
  - `Impl` 新增 `tools` (`unique_ptr<QgsMapTool>`)、`extent_callbacks`、`xy_callbacks`、`canvas_refs` (`QPointer<QgsMapCanvas>`) 用于生命周期安全。

- **绑定层** `native/qgis_render_bridge/src/bindings.cpp`:
  - 顶部 `#include <pybind11/functional.h>`。
  - `mapstack` 子模块新增 `set_map_tool` 直接绑定，`set_extent_callback` / `set_xy_callback` 在 lambda 中用 `py::gil_scoped_acquire` 包 `py::function` 后传入 `std::function`，保证 GUI 线程持 GIL 回调 Python。

- **Python 桥** `paleo_workbench/ui/qgis_stack/events.py`:
  - `StackEvents(QObject)` 两 Signal：`extent_changed(float×4)`、`map_position_changed(float×2)`。
  - `attach(stack, canvas_address)` 分别 `stack.set_extent_callback` / `set_xy_callback`，回调内 `QTimer.singleShot(0, lambda: self.xxx.emit(...))` 重排队，避免在桥调用栈深处触发槽。

- **测试** `tests/test_qgis_mapstack_tools.py` 按 brief 原文新建，含 `test_set_native_tool` 与 `test_extent_callback_fires_as_signal`。

## TDD 证据

### Step 1-2: RED（未实现前）

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_tools.py -v
```

输出（节选）:
```
tests/test_qgis_mapstack_tools.py F F
  test_set_native_tool - AttributeError: 'qgis_render_bridge.mapstack.QgisMapStack' object has no attribute 'set_map_tool'
  test_extent_callback_fires_as_signal - ModuleNotFoundError: No module named 'paleo_workbench.ui.qgis_stack.events'
2 failed in 0.41s
```

### Step 5: GREEN（实现+重编后）

```bash
cd /home/kevin/projects/paleo_project/main
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_tools.py -v
```

输出:
```
tests/test_qgis_mapstack_tools.py ..  2 passed in 0.38s
```

重编产物: `native/qgis_render_bridge/qgis_render_bridge.cpython-313-x86_64-linux-gnu.so` (869K→871K, 2026-09-03 13:57)

### 回归无退化

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main tests/test_qgis_mapstack_layers.py tests/test_qgis_canvas_embed.py tests/test_qgis_mapstack_lifecycle.py tests/test_qgis_mapstack_env.py tests/test_qgis_render_bridge.py -v
```
```
10 passed in 1.30s
```

## 文件变更

- `native/qgis_render_bridge/src/map_stack_service.hpp` — 新增 `setMapTool`、`ExtentCallback`/`PointCallback`、`setExtentCallback`/`setXyCallback` 声明
- `native/qgis_render_bridge/src/map_stack_service.cpp` — 新增 include (`QPointer`, `qgsmaptool*`)、Impl 成员、销毁安全逻辑（`QPointer` + `release()` 避免 canvas 已销毁后 double-free）、`createCanvas` 记录 `canvas_refs`、`setMapTool`/`setExtentCallback`/`setXyCallback` 实现
- `native/qgis_render_bridge/src/bindings.cpp` — `#include <pybind11/functional.h>` + 三个 `def`
- `paleo_workbench/ui/qgis_stack/events.py` — 新建
- `tests/test_qgis_mapstack_tools.py` — 新建

## 偏离与适配

- **QgsMapTool API** 与 brief 一致：`QgsMapToolPan(canvas)`、`QgsMapToolZoom(canvas, bool zoomOut)` 均在 `third_party/qgis/src/gui/maptools/` 中存在，无需适配。
- **额外增加** `#include <qgsmaptool.h>` 与 `#include <QPointer>`：brief 仅列出 `qgsmaptoolpan.h/qgsmaptoolzoom.h/qgspointxy.h`，但 `Impl` 需完整类型 `QgsMapTool` 定义及 `QPointer` 前向。
- **生命周期安全加固**（最小必要偏离）：brief 未处理 canvas 先于 stack 销毁的场景，实测 `test_set_native_tool` 在 pytest fixture 拆卸顺序下 `host`（内含 `QgsMapCanvas`）先于 `stack.shutdown()` 销毁，导致 `unique_ptr<QgsMapTool>` 二次释放（`QgsMapTool` 以 `canvas` 为 QObject parent，canvas 销毁时已自动删 tool）。增加 `canvas_refs: QPointer<QgsMapCanvas>` 并在 `shutdown()`/析构中对 `canvasAlive==false` 的条目 `release()` 而非 `delete`，避免 `SIGSEGV at 0x1a`（`mCanvas->unsetMapTool` 解引用悬垂指针）。同时 `createCanvas`/`setMapTool`/`set*Callback` 均更新 `canvas_refs`。此改动不改变对外接口，仅修复悬垂。

## 关注与风险

- `setExtentCallback`/`setXyCallback` 每次调用 `QObject::connect` 不 `disconnect` 旧连接，重复调用会累积回调。当前任务单次 `attach` 场景无风险，若后续支持热切换需先 `disconnect`。
- `QPointer` 跟踪仅在 `shutdown`/析构时检查，若在 canvas 销毁后、shutdown 前再次 `set_map_tool` 旧地址会抛 `canvasOrThrow`？实际上悬垂地址传回会解引用未定义，调用方应避免使用已销毁 canvas 的地址。文档化“canvas 地址在宿主 QWidget 销毁后失效”可降低误用。
- 事件回调经 `QTimer.singleShot(0, ...)` 转 Signal，已在 GUI 线程持 GIL 执行，符合 brief 的线程/GIL 约束。
- 未引入额外依赖，保持 `map_stack_service.cpp` 纯 Qt/C++（GIL 仅在 `bindings.cpp`）。

## Fix: 审查发现修复

### 变更摘要（按发现）

- **F1 (Critical) 陈旧地址重入 double-free/UAF** — `map_stack_service.cpp` 新增 `ensureNotStale(canvas_addr)` 私有方法：入口处检查 `canvas_refs` 是否包含该地址且 `QPointer` 为 null，若是则 `release()`（非 delete）旧 `tools[addr]`，`QObject::disconnect` 并 `erase` 旧 `extent_connections`/`xy_connections`，`erase` 旧 `extent_callbacks`/`xy_callbacks`/`tree_bridges`，随后 `throw std::invalid_argument("canvas address no longer valid")`。该检查置于 `setMapTool`/`setExtentCallback`/`setXyCallback` 的解引用之前，避免对已释放 canvas 的 double-free 与 UAF。保持 `canvas_refs` tombstone 供 F2 的集中校验复用（仅移除其他映射，不立即移除 `canvas_refs` 条目，下次 `canvasOrThrow` 仍可识别为已知死亡地址）。

- **F2 (Important) canvasOrThrow 未查 QPointer 注册表** — 将原静态自由函数 `canvasOrThrow` 改为 `QgisMapStack::canvasOrThrow(std::uintptr_t) const` 成员方法：先查 `impl_->canvas_refs`，若条目存在且 `isNull()` 则抛 `invalid_argument("canvas address no longer valid")`；否则再做 `reinterpret_cast` 空指针检查。所有解引用 canvas 地址的调用点（`setCanvasWhiteBackground`/`setDestinationCrs`/`setCanvasExtent`/`canvasExtent`/`zoom*`/`refreshCanvas`/`screenToMap`/`mapToScreen`/`setMapTool`/`setExtentCallback`/`setXyCallback` 及其 lambda 内）均改走该单一路经。未见地址（无 `canvas_refs` 条目）仍按原逻辑放行，仅已知死亡地址被拒。

- **F3 (Important) `captured this` UAF** — `Impl` 新增 `extent_connections`/`xy_connections`（`unordered_map<uintptr_t, QMetaObject::Connection>`，`#include <QObject>`）。`setExtentCallback`/`setXyCallback` 存连接句柄；`shutdown()` 与 `~QgisMapStack()` 入口处先 `QObject::disconnect` 全部已存连接并 `clear()`，再清理回调映射，避免 `QgisMapStack` 先于 `QgsMapCanvas` 销毁后信号仍触发 `this->impl_` 悬垂。

- **F4 (Important) 回调累积** — 每次 `setExtentCallback`/`setXyCallback` 连接前，先查对应 `*_connections` 映射，若存在则 `disconnect` 旧连接并 `erase`，再 `connect` 新 lambda 并写入新句柄。确保单 canvas 单一回调，后续覆盖不会使单次 `extentsChanged`/`xyCoordinates` 触发 N 次。

- **F5 (Important) `py::function` 非 GIL 销毁** — 保持 `map_stack_service.cpp` 纯 Qt/C++（不引入 `pybind11`）。绑定层修复：`bindings.cpp` 中 `mapstack.QgisMapStack.shutdown` 由直接绑定 `&QgisMapStack::shutdown` 改为 lambda `[](QgisMapStack& self){ py::gil_scoped_acquire gil; self.shutdown(); }`，使 `extent_callbacks`/`xy_callbacks` 内 `py::function`（含 Python 引用计数）的 `clear()`/`析构` 始终在持 GIL 下执行。Python 侧对象析构本身持 GIL，`shutdown` wrappers 覆盖 C++ 侧显式清理路径。

- **M1 (Minor) `operator[]` 误插空条目** — 信号 lambda 内由 `impl_->extent_callbacks[canvas_addr]` / `impl_->xy_callbacks[canvas_addr]` 改为 `find()` + `end()`/`!cb` 早返，避免未注册地址的意外插空。

- **M2 (Minor) shutdown 后连接残留** — 由 F3 的 `disconnect` 覆盖，`shutdown()` 先断开全部 `extent_connections`/`xy_connections` 再 `clear()` 回调映射，`alive` canvas 的连接不再残留。

### 文件变更

- `native/qgis_render_bridge/src/map_stack_service.hpp` — 前向声明 `class QgsMapCanvas;`；`Impl` 增 `extent_connections`/`xy_connections`；`private` 增 `QgsMapCanvas* canvasOrThrow(uintptr_t) const` 与 `void ensureNotStale(uintptr_t)`。
- `native/qgis_render_bridge/src/map_stack_service.cpp` — 增 `#include <QObject>`；`Impl` 增两连接映射；`~QgisMapStack`/`shutdown` 先 `disconnect` 连接；`canvasOrThrow` 改成员并查 `canvas_refs`；新增 `ensureNotStale`（F1）；`setMapTool`/`setExtentCallback`/`setXyCallback` 入口调 `ensureNotStale`，连接前 `disconnect` 旧句柄（F4），lambda 用 `find()`（M1），存新 `Connection`。
- `native/qgis_render_bridge/src/bindings.cpp` — `shutdown` 改 GIL wrappers（F5）。
- `tests/test_qgis_mapstack_tools.py` — 新增 `test_extent_callback_no_duplicate_on_reregistration`（F4 回归）。

### 验证

**重编:**
```bash
cd /home/kevin/projects/paleo_project/main && PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --force-reinstall --no-deps
```
输出（节选）:
```
Successfully built qgis_render_bridge
Successfully installed qgis_render_bridge-0.2.17a0
```

**TDD — 新回归测试失败在前（旧代码）:**
```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -v tests/test_qgis_mapstack_tools.py::test_extent_callback_no_duplicate_on_reregistration
```
旧代码输出:
```
FAILED tests/test_qgis_mapstack_tools.py::test_extent_callback_no_duplicate_on_reregistration
  AssertionError: 重复注册导致回调累积，预期 1 次收到 2 次: [(-3.34..., 0.0, 23.34..., 20.0), (-3.34..., 0.0, 23.34..., 20.0)]
  assert 2 == 1
1 failed in 0.69s
```

**TDD — 修复后通过:**
```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -v tests/test_qgis_mapstack_tools.py::test_extent_callback_no_duplicate_on_reregistration
```
输出:
```
1 passed in 0.70s
```

**覆盖测试（修复后）:**
```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main -q tests/test_qgis_mapstack_tools.py tests/test_qgis_mapstack_layers.py tests/test_qgis_canvas_embed.py tests/test_qgis_mapstack_lifecycle.py tests/test_qgis_mapstack_env.py tests/test_qgis_render_bridge.py
```
输出:
```
13 passed in 1.65s
```
详细 `-v`:
```
tests/test_qgis_mapstack_tools.py ...  (含新增 F4 回归)
tests/test_qgis_mapstack_layers.py .
tests/test_qgis_canvas_embed.py ..
tests/test_qgis_mapstack_lifecycle.py .
tests/test_qgis_mapstack_env.py .
tests/test_qgis_render_bridge.py .....
13 passed in 1.66s
```
（期望 12 用例 + 新增 1 回归 = 13，全部通过；旧 12 用例保持通过。）

### 未完成/后续

- 陈旧地址的 tombstone 保留在 `canvas_refs` 直至 `shutdown()` 清空；若需长期运行且频繁创建/销毁 canvas，可考虑引入独立 `dead_addrs` 集合并在 `ensureNotStale` 时 `erase` 旧 `canvas_refs` 条目并记入 `dead_addrs`，以回收 `QPointer` 槽位同时保持已知死亡拒绝。此为可选优化，不影响当前 M1 正确性。
- `map_stack_service.cpp` 仍未引入 `pybind11`，F5 的析构 GIL 安全依赖 Python 侧对象析构持 GIL（`pybind11` 已保证）及 `shutdown` 显式 GIL wrappers；若未来在纯 C++ 侧直接析构持回调的 `QgisMapStack`，调用方需先经持 GIL 的 wrappers 完成 `shutdown`。
