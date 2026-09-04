# QGIS 原生地图栈 M5（工程 XML + fallback 收紧 + CI 门禁）实施计划

> **Status: IMPLEMENTED** on `feat/qgis-native-map-stack-m5`。相关套件 39 passed。QGIS CI 专轨是否全绿以推送后的 Actions 为准。合入 main 待确认。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把父 spec 从 M4 推迟的三项落地：mini-`QgsProject` XML 写入工程文件、生产路径不再用环境变量把已构建的桥降级、QGIS CI 专轨真正执行 mapstack 测试。

**Architecture:** C++ `QgisMapStack` 增加 `writeProjectXml` / `applyProjectXml`（donor 临时工程按 `pwb/doc_id` 拷呈现态，不替换 live 图层集合、不碰要素）。Python `ProjectDocument.map_qgis_project_xml` 是工程文件信封；综合编修 save 写出、load 后 overlay。主 CI 无桥时 `create_display_canvas` 仍回落 `UnifiedMapCanvas`。

**Tech Stack:** PySide6 (Qt6), pybind11, vendored QGIS 4.2, pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m5-design.md`

---

## Global Constraints

- 不依赖系统 QGIS；vendored 构建在 `native/qgis_render_bridge/build/qgis-vendor/output`。
- 进程内只有 PySide6。控件以 `uintptr_t` 过桥。
- `map_stack_service.cpp` 禁止 pybind11 / Python.h；GIL 只在 `bindings.cpp`。
- 回调销毁走孤儿坟场。
- 要素权威仍是 Python `user_vector_layers` / `VectorEditSession`。
- 重建：`cd /home/kevin/projects/paleo_project/main && PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation`
- 测试：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args> -q --basetemp=$(mktemp -d)`。看 `N passed/failed`，不看管道退出码。
- 工作区 `/home/kevin/projects/paleo_project/main`，分支 `feat/qgis-native-map-stack-m5`。
- **绝不提交** `.superpowers/`、`symbology-style.db`、`user-history.db`。
- 不改编图页 `MapEditView`、不迁 `QgsProject::instance()`、不退役 `VectorEditSession`、不删 `FallbackMapRenderBackend`。

## 文件地图

| 路径 | 职责 |
|---|---|
| `native/qgis_render_bridge/src/map_stack_service.hpp/.cpp` | `writeProjectXml` / `applyProjectXml` |
| `native/qgis_render_bridge/src/bindings.cpp` | snake_case 绑定 |
| `native/qgis_render_bridge/setup.py` | 转发 `CMAKE_PREFIX_PATH` / `PALEO_QGIS_CMAKE_PREFIX` |
| `paleo_workbench/project/models.py` | `map_qgis_project_xml` |
| `paleo_workbench/project/manager.py` | dirty domain |
| `paleo_workbench/ui/workstation/composite_document.py` | save 写 XML、load 后 apply |
| `paleo_workbench/mapping/map_render_backend.py` | 去掉环境变量降级 |
| `tests/test_qgis_project_xml.py` | 桥级 round-trip |
| `tests/test_qgis_project_xml_persist.py` | 工程字段 + composite 接线 |
| `.github/workflows/qgis-renderer.yml` | conda Qt prefix + marker 路径 |
| `README.md` / `CLAUDE.md` / 父 spec | 状态 |

---

### Task 1: 桥 write/apply project XML

**Files:**
- Create: `tests/test_qgis_project_xml.py`
- Modify: `native/qgis_render_bridge/src/map_stack_service.hpp`
- Modify: `native/qgis_render_bridge/src/map_stack_service.cpp`
- Modify: `native/qgis_render_bridge/src/bindings.cpp`

- [x] **Step 1: 写失败测试**

```python
# tests/test_qgis_project_xml.py
"""M5: QgsProject XML 写出/按 pwb/doc_id 套用呈现态，不替换要素。"""
import json

import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON

pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
pytestmark = pytest.mark.qgis

_GEOJSON_A = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
         "properties": {"name": "A"}}
    ],
})
_GEOJSON_B = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
         "properties": {"name": "B"}}
    ],
})


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack
    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_write_project_xml_contains_qgis_and_doc_id(stack):
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    xml = stack.write_project_xml()
    assert "<qgis" in xml
    assert "doc-a" in xml


def test_apply_project_xml_restores_visibility_opacity_order(stack):
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    stack.upsert_mirror_layer(
        "doc-b", "LayerB", "Point", "EPSG:4326", _GEOJSON_B,
        visible=True, opacity=1.0,
    )
    stack.set_mirror_layer_order(["doc-b", "doc-a"])
    stack.set_mirror_layer_visibility("doc-a", False)
    stack.set_mirror_layer_opacity("doc-b", 0.4)
    xml = stack.write_project_xml()

    stack.remove_mirror_layers_except([])
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    stack.upsert_mirror_layer(
        "doc-b", "LayerB", "Point", "EPSG:4326", _GEOJSON_B,
        visible=True, opacity=1.0,
    )
    applied = stack.apply_project_xml(xml)
    assert applied == 2
    assert stack.mirror_order_top_first()[0] == "doc-b"
    assert stack.mirror_layer_visibility("doc-a") is False


def test_apply_empty_xml_is_noop(stack):
    assert stack.apply_project_xml("") == 0


def test_apply_garbage_xml_raises(stack):
    with pytest.raises(RuntimeError):
        stack.apply_project_xml("not-xml<<<")
```

- [ ] **Step 2: 跑确认失败**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  /opt/miniconda3/bin/python3.13 -m pytest tests/test_qgis_project_xml.py -q --basetemp=$(mktemp -d)
```

Expected: FAIL，`write_project_xml` 不存在。

- [ ] **Step 3: 实现 C++**

`map_stack_service.hpp` 在 `setEditIndicator` 声明后追加：

```cpp
  std::string writeProjectXml();
  int applyProjectXml(const std::string& xml);
```

`map_stack_service.cpp` 实现要点：

- `#include <QFile>` `<QTemporaryDir>`
- `writeProjectXml`：未 initialize 抛错；`QTemporaryDir` + `map.qgs`；`project()->write(path)` 失败抛 `runtime_error`；`QFile` 读全部 UTF-8。
- `applyProjectXml`：空串 return 0；同样写临时文件；`QgsProject donor;` `donor.read(path)` 失败抛错；`SuppressGuard`；遍历 `donor.mapLayers()`，`pwb/doc_id` 命中 live `findMirrorByDocId` 则：`renderer()->clone()`、`labeling()->clone()` + `setLabelsEnabled`、`setOpacity`、`setName`、树节点 `setItemVisibilityChecked`；收集 donor `layerTreeRoot()->layerOrder()` 的 doc_id 调 `setMirrorLayerOrder`；return 套用计数。
- donor 是栈上对象，clone renderer/labeling **之后** donor 析构。

`bindings.cpp` mapstack class 追加：

```cpp
.def("write_project_xml", &pwb::qgis_render::QgisMapStack::writeProjectXml)
.def("apply_project_xml", &pwb::qgis_render::QgisMapStack::applyProjectXml)
```

- [ ] **Step 4: 重建 + 测试**

```bash
cd /home/kevin/projects/paleo_project/main && \
PALEO_WITH_QGIS_RENDERER=1 /opt/miniconda3/bin/python3.13 -m pip install -e native/qgis_render_bridge --no-build-isolation && \
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  /opt/miniconda3/bin/python3.13 -m pytest tests/test_qgis_project_xml.py -q --basetemp=$(mktemp -d)
```

Expected: 4 passed。

- [ ] **Step 5: 提交** `m5(bridge): QgsProject XML write/apply by pwb/doc_id`

---

### Task 2: 工程字段 + 综合编修 save/load

**Files:**
- Create: `tests/test_qgis_project_xml_persist.py`
- Modify: `paleo_workbench/project/models.py`
- Modify: `paleo_workbench/project/manager.py`
- Modify: `paleo_workbench/ui/workstation/composite_document.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_qgis_project_xml_persist.py
"""M5: map_qgis_project_xml 进入工程文件；composite save/load 接线。"""
import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON

pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
pytestmark = pytest.mark.qgis


def test_project_document_roundtrips_map_qgis_project_xml():
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("demo")
    assert doc.map_qgis_project_xml == ""
    doc.map_qgis_project_xml = "<qgis>ok</qgis>"
    loaded = ProjectDocument.model_validate(doc.model_dump())
    assert loaded.map_qgis_project_xml == "<qgis>ok</qgis>"


def test_sync_composition_writes_xml_onto_project(qapp, qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    page = CompositeDocument()
    qtbot.addWidget(page)
    project = ProjectDocument.new("demo")
    page.set_project(project)
    assert "<qgis" in (project.map_qgis_project_xml or "")
```

- [ ] **Step 2: 跑确认失败**（字段不存在 / XML 仍空）

- [ ] **Step 3: 实现**

`ProjectDocument` 在 `user_vector_layers` 后加：

```python
    map_qgis_project_xml: str = ""
```

`manager.py` `FIELD_DIRTY` 加 `"map_qgis_project_xml": ProjectDirtyDomain.MAP_DOCUMENTS`。

`composite_document.py`：

- `_sync_composition_now` 在 `sync_to_project` 之后：若 `self.canvas` 有 `stack` 且有 `write_project_xml`，写入 `self._project.map_qgis_project_xml`。
- `set_project` 在 `_sync_composition_now()` 之后：读取 XML，非空则 `self.canvas.stack.apply_project_xml(xml)`。用 `_loading` 或一次性标志避免 apply 触发的树回调再把 XML 写成空。apply 期间保持 `_loading=True` 或只在 `not self._loading` 时写 XML（set_project 里 apply 时 `_loading` 已 False——把 apply 放进 `try/finally` 的 `_loading=True` 段之后、再 sync 一次不写？更简单：`_sync_composition_now` 只在 `not self._loading` 时写 XML；`set_project` 先 sync（loading False 会写一份当前镜像），再 apply，再 `_loading=True` 包一层 apply。正确顺序：

```
_loading = True
load layers
_loading = False
_sync_composition_now()          # 镜像 + 若已有 xml 先不 apply
xml = project.map_qgis_project_xml
if xml:
    stack.apply_project_xml(xml)
    # apply 后不要立刻用 write 覆盖：当前 _sync 已在 apply 前写出，可能是默认可见性。
```

因此 **load 时必须先 apply 再允许 write**：

```
_loading = True
load layers
_sync_composition_now()          # bind 画布，因 _loading 不写 XML、不 sync_to_project
xml = project.map_qgis_project_xml
if xml:
    stack.apply_project_xml(xml)
_loading = False
```

现有 `set_project` 已在 `_loading` 下 `load_from_project`，finally 设 False 后才 `_sync_composition_now`。改成：finally 前不要提前 False；sync 仍在 loading 下跑（不写工程），apply XML，然后 `_loading=False`。

- [ ] **Step 4: 跑测试通过**

- [ ] **Step 5: 提交** `m5(project): persist map_qgis_project_xml on composite save/load`

---

### Task 3: 生产路径去掉环境变量降级

**Files:**
- Modify: `paleo_workbench/mapping/map_render_backend.py`
- Modify: `tests/test_issue_937_qgis_ui_batch.py`（若有环境变量断言则改为直接构造 fallback）
- Modify: `README.md`

- [ ] **Step 1: 写/改失败测试**

在 `tests/test_audit_fix_regressions.py` 的 `test_create_map_render_backend_degrades_on_broken_bridge` 旁新增：

```python
def test_create_map_render_backend_ignores_disable_env(monkeypatch):
    import paleo_workbench.mapping.map_render_backend as mrb
    monkeypatch.setenv("PALEO_DISABLE_QGIS_RENDERER", "1")
    monkeypatch.setenv("PALEO_USE_QGIS_RENDERER", "0")
    # 不因环境变量把 prefer_qgis 打成 False；无桥时仍 fallback。
    backend = mrb.create_map_render_backend(prefer_qgis=True)
    assert backend is not None
```

无桥时该测试仍绿（fallback）。有桥时 backend 必须是 QGIS，不能因 env 变成 fallback——用 `qgis_bridge_available()` 分支断言。

- [ ] **Step 2: 删 `create_map_render_backend` 里两段 env 降级。** README 删除 Runtime opt-out 段，改为：测试直接构造 `FallbackMapRenderBackend`；无桥才走 fallback。

- [ ] **Step 3: 跑** `tests/test_audit_fix_regressions.py tests/test_issue_937_qgis_ui_batch.py -q`

- [ ] **Step 4: 提交** `m5(render): drop PALEO_DISABLE_QGIS_RENDERER production opt-out`

---

### Task 4: pytest.mark.qgis 覆盖 mapstack 测试 + workflow 路径

**Files:**
- Modify: 所有需要桥的 `tests/test_qgis_*.py`（见仓库侦察：canvas/digitize/display/layer*/mapstack*/select/snapping/tool/vertex 等）
- 不改：`test_qgis_style_payload.py`（纯 Python）、`test_qgis_vendor_source.py`（workflow 已单独跑）
- Modify: `.github/workflows/qgis-renderer.yml`
- Modify: `native/qgis_render_bridge/setup.py`

- [ ] **Step 1:** 每个需桥文件在 `importorskip` 之后加 `pytestmark = pytest.mark.qgis`（已有 pytestmark 的跳过）。

- [ ] **Step 2:** `setup.py` `_build_vendored_qgis` 的 `cmake_args` 追加：

```python
    prefix = os.environ.get("PALEO_QGIS_CMAKE_PREFIX", "").strip() or os.environ.get("CMAKE_PREFIX_PATH", "").strip().split(os.pathsep)[0]
    if prefix:
        cmake_args.append(f"-DCMAKE_PREFIX_PATH={prefix}")
```

- [ ] **Step 3:** workflow

- path filter 增加 `paleo_workbench/ui/qgis_stack/**`
- conda create 增加 `"qt6-main=6.11.1"`（已随 pyside6 来则再显式装一次无妨）并确认 Multimedia：`ls /tmp/qgisqt/lib/libQt6Multimedia.so.6`
- Build 步骤 env：`CMAKE_PREFIX_PATH: /tmp/qgisqt`，`PKG_CONFIG_PATH: /tmp/qgisqt/lib/pkgconfig`
- 注释更新：不再把 6.4/6.11 混链写成 known remaining gap，改写为「构建与运行同一 conda Qt prefix」

- [ ] **Step 4: 提交** `m5(ci): mark mapstack tests qgis; build vendored QGIS against CMAKE_PREFIX_PATH`

---

### Task 5: 文档与已完成计划状态

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md` 里程碑段
- Modify: `docs/superpowers/plans/2026-09-03-qgis-native-map-stack-m1.md`（文首 Status: COMPLETE）
- Modify: `docs/superpowers/plans/2026-09-03-qgis-native-map-stack-m2.md`
- Modify: `docs/superpowers/plans/2026-09-04-qgis-native-map-stack-m3.md`（已有 [x]，补 Status）
- Modify: `docs/superpowers/plans/2026-09-04-qgis-native-map-stack-m4.md`（文首 Status: COMPLETE，checkbox 保持 as-built 已合入）
- Modify: `README.md` / `CLAUDE.md`

- [ ] **Step 1:** 父 spec §10 M4 行保持切片指针；新增 M5 行指向本文。里程碑进度改 M1–M4 完成、M5 进行中→完成后改完成。
- [ ] **Step 2:** README 地图栈段：M5 起工程文件含 `map_qgis_project_xml`；无桥仍 fallback；无 `PALEO_DISABLE` opt-out。
- [ ] **Step 3: 提交** `docs(qgis): M5 收尾状态`

---

### Task 6: 回归 + 合回

- [ ] **Step 1:** 相关套件

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  /opt/miniconda3/bin/python3.13 -m pytest \
  tests/test_qgis_project_xml.py tests/test_qgis_project_xml_persist.py \
  tests/test_qgis_mapstack_style.py tests/test_qgis_layer_panel.py \
  tests/test_qgis_display_canvas.py tests/test_composite_editing.py \
  tests/test_audit_fix_regressions.py -q --basetemp=$(mktemp -d)
```

- [ ] **Step 2:** 终局审查（C/I/M）。With fixes 才合。
- [ ] **Step 3:** fast-forward 合 main，删功能分支。

## Spec coverage

| Spec 条目 | Task |
|---|---|
| write/apply XML | 1 |
| ProjectDocument 字段 + composite | 2 |
| 旧工程 qgis_style 迁移（空 XML） | 2（load 跳过 apply） |
| 去掉 PALEO_DISABLE | 3 |
| 无桥 UnifiedMapCanvas 保留 | 3（不改工厂） |
| mark.qgis + CMAKE_PREFIX_PATH + workflow | 4 |
| 文档 | 5 |

不在切片：MapEditView、instance() 迁出、VectorEditSession、删 fallback 类、provider_gdal/ogr。
