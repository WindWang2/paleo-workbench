# CONV-29 — Composer / Layout / Export C++ 化（findings & 分类账本）

## 盘点（Python production surface → 处置）

| Python surface | 分类 | 处置 |
| --- | --- | --- |
| `mapping/layout_export.py::build_layout_spec` | **migrated** | `pwb::layout_export::build_layout_spec`（libs/layout_export），41 个 oracle 用例逐键冻结（tools/oracle/generate_layout_export_fixtures.py） |
| `layout_export.py::hybrid_element_types` + 三桶分类表 | **migrated** | `native_wire_type/is_hybrid_type/is_legend_backed_type/hybrid_element_types`，完整性 assert 移植到内核单测 |
| `layout_export.py::_mirror_proves/_legend_filter_doc_ids` | **migrated** | `mirror_proves/legend_filter_doc_ids`（D-04 JSON 契约） |
| `layout_export.py::MAX_EXPORT_PIXELS/_check_pixel_budget` | **migrated** | `kMaxExportPixels/check_pixel_budget`（%g 消息逐字对齐） |
| `layout_export.py::LayoutExportReport` | **migrated** | `LayoutExportReport`（Python 九键逐一保形 + failure/dimensions/filter_layers C++ 超集，D-06） |
| `layout_export.py::export_composition_reported`（qgis_layout 引擎路径、警告语序） | **migrated（策略偏差 D-03）** | `export_composition_reported`（executor 注入）；composer SVG 兜底路径改为 honest ok=false 报告 |
| `layout_export.py::_north_arrow_svg_path` | **migrated** | `north_arrow_svg_path()`（字节一致 SVG、同文件名、同失败语义→""） |
| QGIS layout bridge（`QgisMapStack.layoutExport`，C++） | **single-authority refactor** | 主体原样抽到 `layout_spec_exec.cpp`；桥与产品共用同一翻译单元（D-02），行为零变化 + force_vector/PNG 尺寸扩展 |
| `composer/models.py`（Composition/ComposerElement） | already migrated（CONV-02） | 复用 `pwb::mapping_document`，未复制 |
| `composer/renderer.py`（SVG 字符串渲染器，1341 行） | **oracle-only / removal-candidate** | C++ fail-closed 策略（D-03）取代 all-or-nothing SVG 兜底；仅当 Python 侧继续维护构图编辑器时保留为 legacy |
| `composer/export.py`（QSvgRenderer/QPdfWriter 页面导出） | **oracle-only / removal-candidate** | 原生链 PDF/SVG/PNG 经 QgsLayoutExporter；物理尺寸契约由 spec page_mm 承接；透明背景经页面填充 |
| `composer/registry.py / templates.py / components.py` | **Python-only（构图编辑器 UI 层）** | 归属构图编辑 UI（Python 面板），非导出链；C++ 侧暂无构图编辑器，接入时另行切片 |
| `ui/pages/composition_panel.py::_export`（Python 构图面板导出） | **legacy path** | 该路径今天无 stack 即 composer_fallback；C++ 产品的等价入口是 MainWindow 导出布局 → CompositionLayoutService |
| `ui/unified_map_canvas.py::export_png/_export_via_backend/export_map_body` | **migrated（产品入口）** | `CompositionLayoutService::export_map_body`（map-body-only、透明背景、frame 关闭）——注意 Python 该面属 render-backend 链，C++ 产品统一走原生执行器 |
| screen/export parity（tests/test_qgis_screen_export_parity.py 的状态等价面） | **migrated（状态级，D-07）** | `screen_export_parity` 内核比对 + `MapSession::canvas_state_json` + 服务 `parity_report`；像素级颜色采样 parity 留给 Python oracle |

## 产品接线

- `apps/paleo_workbench_platform` “导出布局…”（CONV-29 编译期）：A4 构图（标题/主图/图例/比例尺/指北针/图廓）由会话实时状态组装 → `validate_layout`（fail-closed 预检）→ `parity_report`（画布/导出差异）→ `export_layout`（原生链）→ 状态栏报告（items/dimensions/警告数/parity）。
- 服务暴露：`validate_layout / export_layout / preview / export_map_body / parity_report`，供 C++ UI 直接调用（composition JSON 契约与 CONV-02 内核一致）。

## 其他关键发现

1. 本机 Linux 平台构建需要 PwbQgisSdk 增加 QGIS external 头目录（nlohmann/json_fwd、qwt、spatialindex、deps prefix）——本地分支 cpp-ui-workbench-closure 有同一修复；本切片带入了等价内容（共享冲突文件，内容保持一致以便合并）。
2. CONV 编号 26（两个在开 PR）、27（ui-workbench 本地分支）、28（science 分支）已被占用，本切片取 CONV-29。
3. `QgsRectangle::include` 在 QGIS 4.2 只收 `QgsPointXY`；矩形并集用 `combineExtentWith`。
4. `composition_page_pixels` 的 falsy 强制（width_mm=0 → 1.0）意味着零尺寸元素经 JSON wire 后不可达——oracle 生成器必须先 `from_dict(to_dict(doc))` 再冻结，否则两侧输入形态不一致。
5. nlohmann 把 JSON 整数 parse 成 unsigned，而内核常量是 signed——沿用 CONV-02 的 `py_int_json` 约定（非负 → uint64），oracle 才能语义相等。
