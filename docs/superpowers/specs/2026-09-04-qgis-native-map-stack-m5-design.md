# QGIS 原生地图栈 M5（本切片）：工程 XML 持久化 + fallback 收紧 + CI 门禁

- 日期：2026-09-04
- 状态：已批准（父 spec 原 M4 收尾项；用户 2026-09-04 要求收尾目前所有计划）
- 父 spec：`docs/superpowers/specs/2026-09-03-qgis-native-map-stack-design.md`
- 前置：M1–M4 已合入 main（HEAD `629ba15a`）

## 目标

把父 spec §7 / §8 / §10 从 M4 推迟的三项落地：

1. 工程文件新增地图图层段：mini-`QgsProject` XML（源 URI 以 `pwb/doc_id` 关联、crs、renderer/labeling、可见性/不透明度/顺序）。
2. 生产路径不再用 `PALEO_DISABLE_QGIS_RENDERER` 把已构建的桥降级成 QPainter；综合编修继续硬依赖桥。
3. QGIS CI 专轨真正选中并执行 mapstack 测试（`pytest.mark.qgis`），并把 vendored QGIS 构建指向 conda Qt prefix，消除 #1147 记录的 6.4/6.11 Multimedia 混链。

成功标准：

1. 综合编修保存后再打开：图层顺序、可见性、透明度、renderer XML 从 `map_qgis_project_xml` 恢复；要素仍来自 `user_vector_layers`（Python 权威）。
2. 旧工程没有 XML 字段时走现有 `qgis_style` 路径，下一次保存写出 XML。
3. 设置 `PALEO_DISABLE_QGIS_RENDERER=1` 不再让 `create_map_render_backend()` 丢掉已构建的桥。
4. 无桥环境（主 CI）首页/工区/编图预览仍走 `UnifiedMapCanvas`（`ImportError` 工厂回落保留）。
5. 所有需要桥的 `tests/test_qgis_*.py` 带 `pytest.mark.qgis`；workflow 路径过滤覆盖 `paleo_workbench/ui/qgis_stack/**`。

## 非目标

- 把 `mapping_page` 的 `MapEditView` 换成原生编辑工具。
- 综合编修迁出 `QgsProject::instance()`。
- 退役 `VectorEditSession`（M3 铁律，父 spec §6 已否决）。
- 补编 `provider_gdal` / `provider_ogr`（XML 叠在既有 memory 镜像上，不改源 URI 模型）。
- 从代码库删除 `FallbackMapRenderBackend` / `UnifiedMapCanvas`（主 CI 仍不编桥）。
- 在本机重跑 50 分钟 GitHub Actions；CI 是否全绿以推送后的 workflow 为准。

## 权威模型

不变：要素 / undo / 修订日志 = Python `VectorEditSession` + `user_vector_layers`。

新增：QGIS 呈现态（renderer、labeling、树序、可见性、透明度、图层名）的工程文件信封 = `ProjectDocument.map_qgis_project_xml`。运行时仍先按快照镜像，再 `apply_project_xml` 覆盖呈现态。

## 接口

C++ `QgisMapStack`：

- `write_project_xml() -> str`：`QgsProject::write` 到临时 `.qgs`，读回 UTF-8。空工程也返回合法 XML（含 `<qgis`）。未 initialize 抛 `runtime_error`。
- `apply_project_xml(xml: str) -> int`：空串返回 0。否则读入**临时** `QgsProject`（不碰 live `instance()` / owned project 的图层集合），按 `pwb/doc_id` 把 donor 的 renderer/labeling/opacity/name/visibility/tree order 拷到 live 镜像。返回成功套用的图层数。损坏 XML 抛 `runtime_error`。全程 `SuppressGuard`。

Python：

- `ProjectDocument.map_qgis_project_xml: str = ""`
- dirty domain：`MAP_DOCUMENTS`
- `CompositeDocument._sync_composition_now` 在 `sync_to_project` 之后写 XML。
- `CompositeDocument.set_project` 在首次 `_sync_composition_now` 之后若 XML 非空则 `apply_project_xml`。

## Fallback 收紧

- 删除 `create_map_render_backend` 对 `PALEO_DISABLE_QGIS_RENDERER` / `PALEO_USE_QGIS_RENDERER=0` 的生产降级。
- 测试继续可直接构造 `FallbackMapRenderBackend(...)`。
- `create_display_canvas` 的 `ImportError → UnifiedMapCanvas` 保留。
- `QgisCanvasShim` 继续硬失败。

## CI

- 无桥也能跑的纯 Python 测试（`test_qgis_style_payload.py`、`test_qgis_vendor_source.py`）不强制 `mark.qgis`。
- 其余 `test_qgis_*` 加 `pytestmark = pytest.mark.qgis`。
- `setup.py`：若环境有 `CMAKE_PREFIX_PATH` 或 `PALEO_QGIS_CMAKE_PREFIX`，传给 vendored QGIS configure。
- `.github/workflows/qgis-renderer.yml`：conda 环境补 Qt Multimedia；构建步骤 export `CMAKE_PREFIX_PATH=/tmp/qgisqt`；path filter 加 `paleo_workbench/ui/qgis_stack/**`。
