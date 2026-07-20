# P3 预览子系统归位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将预览格式解析逻辑从 UI 层下沉到 `resources/preview_parsers/`，将 `_build_preview` 的格式分派重构为注册表模式，并拆分 `preview_widgets.py` 的 12 个预览控件，实现预览子系统的职责归位与结构简化。

**Architecture:** 
1. **格式解析下沉 `resources/`**：在 `paleo_workbench/resources/` 下建立 `preview_parsers/` 包，包含 `models.py`（PreviewResult及常量）、`table_parsers.py`（CSV/TSV/Excel/DAT）、`well_log_parsers.py`（LAS/XML）、`seismic_parsers.py`（SEG-Y）、`office_parsers.py`（PPTX/DFB/ZIP/SpreadsheetML/WLP）与 `document_parsers.py`（GeoTIFF/Markdown/JSON/Audio/HTML）。斩断 `preview_provider.py ↔ fallback_preview.py` 的循环依赖。
2. **注册表模式重构 `_build_preview`**：建立 `paleo_workbench/resources/preview_parsers/registry.py`，注册格式解析器；`PreviewProvider._build_preview` 改造为调用注册表匹配。
3. **拆分 `preview_widgets.py`**：将 12 个 Widget 拆分为独立的 `ui/pages/preview_*.py` 模块，`preview_widgets.py` 转为 re-export 兼容 facade。

**Tech Stack:** Python 3.12, PySide6, pytest + pytest-qt, numpy, pandas, rasterio, segyio.

**Spec:** `docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md`（P3 节）

## Global Constraints

- 只改结构与重构分派方式，不改功能行为、UI 视觉与文案。
- 全量测试在整个 P3 保持 **1109 passed**（与 P2 完成后的基线一致）。
- 保持接口兼容：`preview_widgets.py` 保留 re-export facade 供既有引用点和测试透明使用。
- 测试运行命令统一为 `.venv/bin/python -m pytest <path> -q`。

---

### Task 1: 建立测试基线

**Files:** 无（只读验证）

- [ ] **Step 1: 跑全量测试确认基线**

Run: `.venv/bin/python -m pytest tests -q --tb=short -p no:cacheprovider 2>&1 | tail -3`
Expected: `1109 passed`

---

### Task 2: 格式解析下沉 `resources/preview_parsers/`

**Files:**
- Create: `paleo_workbench/resources/preview_parsers/__init__.py`
- Create: `paleo_workbench/resources/preview_parsers/models.py`
- Create: `paleo_workbench/resources/preview_parsers/table_parsers.py`
- Create: `paleo_workbench/resources/preview_parsers/well_log_parsers.py`
- Create: `paleo_workbench/resources/preview_parsers/seismic_parsers.py`
- Create: `paleo_workbench/resources/preview_parsers/office_parsers.py`
- Create: `paleo_workbench/resources/preview_parsers/document_parsers.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Remove / Deprecate: `paleo_workbench/ui/pages/fallback_preview.py`

**Interfaces:**
- Consumes: 无（下沉解析逻辑，脱离 UI 包）。
- Produces: `paleo_workbench.resources.preview_parsers` 包含纯逻辑格式解析器，消除 `preview_provider.py ↔ fallback_preview.py` 循环依赖。

- [ ] **Step 1: 提取 `models.py`**
将 `PreviewResult`、`PreviewMode`、`TEXT_FORMATS`、`MAX_TABLE_ROWS` 等纯数据模型与常量提取至 `paleo_workbench/resources/preview_parsers/models.py`。`preview_provider.py` 进行 re-export 保持兼容。

- [ ] **Step 2: 提取解析器模块**
- 将 CSV/TSV/Excel/DAT 移至 `table_parsers.py`。
- 将 LAS/XML 测井解析移至 `well_log_parsers.py`。
- 将 SEG-Y 剖面/切片解析移至 `seismic_parsers.py`。
- 将 PPTX/DFB/ZIP/SpreadsheetML/WLP 解析（来自 fallback_preview.py）移至 `office_parsers.py`。
- 将 GeoTIFF/Markdown/JSON/Audio/HTML 解析移至 `document_parsers.py`。

- [ ] **Step 3: 删除 `fallback_preview.py` 或保留 re-export 导轨并运行测试**
删除 `fallback_preview.py`（若无外部依赖），更新测试 `test_fallback_preview.py` 指向 `office_parsers.py` / `well_log_parsers.py` 或做重定向。

- [ ] **Step 4: 运行预览单元测试**

Run: `.venv/bin/python -m pytest tests/test_preview_provider.py tests/test_fallback_preview.py tests/test_xml_well_log.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: 预览格式解析逻辑从 ui 下沉至 resources/preview_parsers/"
```

---

### Task 3: 注册表模式重构 `_build_preview`

**Files:**
- Create: `paleo_workbench/resources/preview_parsers/registry.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py`

**Interfaces:**
- Consumes: `resources.preview_parsers` 的解析器函数。
- Produces: `PreviewRegistry` 与 `default_registry()`。`PreviewProvider._build_preview` 使用注册表机制分派。

- [ ] **Step 1: 创建 `registry.py`**
定义 `PreviewHandler` 接口与 `PreviewRegistry` 类。注册各扩展名/资产类型到相应解析函数。

- [ ] **Step 2: 重构 `PreviewProvider._build_preview`**
使用注册表查表替代 175 行 `if fmt in ...` 巨型条件树。

- [ ] **Step 3: 运行预览提供者测试**

Run: `.venv/bin/python -m pytest tests/test_preview_provider.py tests/test_preview_settings.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: 预览分派重构为 PreviewRegistry 注册表模式"
```

---

### Task 4: 拆分 `preview_widgets.py` 12 个控件

**Files:**
- Create: `paleo_workbench/ui/pages/message_preview_widget.py`
- Create: `paleo_workbench/ui/pages/text_preview_widget.py`
- Create: `paleo_workbench/ui/pages/rich_text_preview_widget.py`
- Create: `paleo_workbench/ui/pages/web_document_preview_widget.py`
- Create: `paleo_workbench/ui/pages/table_preview_widget.py`
- Create: `paleo_workbench/ui/pages/summary_table_preview_widget.py`
- Create: `paleo_workbench/ui/pages/seismic_slice_preview_widget.py`
- Create: `paleo_workbench/ui/pages/image_preview_widget.py`
- Create: `paleo_workbench/ui/pages/pdf_preview_widget.py`
- Create: `paleo_workbench/ui/pages/geotiff_preview_widget.py`
- Create: `paleo_workbench/ui/pages/json_tree_preview_widget.py`
- Create: `paleo_workbench/ui/pages/media_preview_widget.py`
- Modify: `paleo_workbench/ui/pages/preview_widgets.py` (facade re-export)

**Interfaces:**
- Consumes: 无。
- Produces: 12 个内聚独立的 PreviewWidget 模块。`preview_widgets.py` re-export 保持 100% 向后兼容。

- [ ] **Step 1: 逐一创建 12 个独立 Widget 模块**
从 `preview_widgets.py` 提取类及所需 import 放到对应独立模块文件中。

- [ ] **Step 2: 将 `preview_widgets.py` 转为 re-export 门面**
在 `preview_widgets.py` 导入这 12 个控件并定义 `__all__`。

- [ ] **Step 3: 运行 Widget 测试**

Run: `.venv/bin/python -m pytest tests/test_preview_widgets.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: 拆分 preview_widgets.py 12 个预览控件为独立模块"
```

---

### Task 5: 全量回归与 Spec 状态更新

**Files:**
- Modify: `docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md`
- Modify: `.superpowers/sdd/progress.md`

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest tests -q --tb=short -p no:cacheprovider 2>&1 | tail -3`
Expected: `1109 passed`

- [ ] **Step 2: 更新 Spec 与 Progress 台账**
在 `docs/superpowers/specs/2026-07-20-paleo-workbench-refactor-design.md` 标记 `P3 已完成`。在 `.superpowers/sdd/progress.md` 追加 P3 完成记录。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: 标记 P3 预览子系统重构完成"
```
