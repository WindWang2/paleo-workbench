# 连井对比 P3 导出增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 连井剖面导出支持格式选择（SVG/PNG/PDF）、DPI 与尺寸选项，引擎 `export_composite` 扩展可选参数且默认行为完全不变。

**Architecture:** 引擎侧 `export_composite` 增加仅关键字可选参数（`dpi` / `width_px` / `page_size`），通过 `painter.scale()` 统一实现重采样；workbench 侧新增独立的 `CrossWellExportDialog` 组件，地层对比页"导出连井 SVG"按钮改为"导出连井剖面"并走对话框流程。

**Tech Stack:** PySide6（QSvgGenerator / QPrinter / QImage）、pytest（offscreen）。

**Spec:** `docs/superpowers/specs/2026-07-21-cross-well-correlation-optimization-design.md`（P3 部分）

## Global Constraints

- `export_composite` 新参数**仅关键字**且默认值保持现有行为：`paleo_workbench/resources/export_service.py` 以 `export_composite(str(path), fmt="png"/"svg"/"pdf")` 位置调用，不得被破坏（本计划不改 export_service）。
- 引擎所有改动默认行为不变；现有测试不得修改（只能新增）。
- 不制造 geoviz → paleo_workbench 反向依赖。
- 两个独立 git 仓库：引擎改动在 `geo-viz-engine/` 提交，workbench 改动在仓库根提交（含子模块 gitlink 联动）。
- 所有命令使用项目 venv：仓库根 `.venv/bin/python`；geo-viz-engine 内 `../.venv/bin/python`。
- 遵循 TDD：先写失败测试，再实现。

**现状事实（实现者无需再调研）：**
- 引擎 `cross_well_widget.py` 现有方法（行号约为 392-435）：`export_composite(self, path, fmt="svg")`、`_export_svg(self, path, w, h)`、`_export_pdf(self, path, w, h)`、`_export_png(self, path, w, h)`、`_paint_composite(self, painter, total_w, total_h)`；间距已从 `self._well_spacing` 读取。
- 页面 `_export_section`（`paleo_workbench/ui/pages/stratigraphy_correlation_page.py`，约 470-495 行）当前硬编码 `fmt="svg"`；按钮 `self.export_btn` 文案"导出连井 SVG"。
- 页面已有 `default_export_dir` import 与 `self._project.meta.project_root` 处理模式（见现有 `_export_section`/`_export_tops`）。

---

### Task 1: 引擎 export_composite 可选参数

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/cross_well_widget.py`（导出方法区）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_export_composite_options.py`

**Interfaces:**
- Produces（Task 2 依赖）:
  - `CrossWellWidget.export_composite(path: str, fmt: str = "svg", *, dpi: int = 96, width_px: int | None = None, page_size: str | None = None) -> None`
  - `dpi`：PNG 写入 dots-per-meter 元数据；PDF `printer.setResolution(dpi)` 且毫米换算按 dpi。SVG 忽略。
  - `width_px`：输出宽度（像素），高度等比；`None`/`0` = 自然宽度（现状）。三种格式通用（SVG 改变 viewBox 尺寸）。
  - `page_size`：仅 PDF，`"A4"` 或 `"LETTER"`（大小写不敏感）；设置后内容等比适配进该纸张（横向取较大可放置方向由内容宽高比决定：内容宽 > 高则 landscape），忽略 `width_px`。`None` = 内容尺寸页面（现状）。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_export_composite_options.py`：

```python
"""CrossWellWidget.export_composite optional-parameter tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_widget():
    from geoviz_well_log.cross_well_widget import CrossWellWidget
    from geoviz_well_log.models import CurveData
    from geoviz_well_log.renderer.canvas import WellLogCanvas
    from geoviz_well_log.renderer.curve_track import CurveTrack

    widget = CrossWellWidget()
    for i in range(2):
        curve = CurveData(
            name="GR", unit="API",
            depth=[float(d) for d in range(10)],
            values=[float(v) for v in range(10)],
            display_range=(0.0, 10.0),
        )
        canvas = WellLogCanvas()
        canvas.add_track(CurveTrack([curve], label="GR"))
        canvas.resize(200, 600)
        widget.add_canvas(canvas, f"W{i + 1}")
    widget.resize(800, 600)
    return widget


def test_default_png_unchanged(qapp, tmp_path):
    widget = _make_widget()
    out = tmp_path / "default.png"
    widget.export_composite(str(out), fmt="png")
    from PySide6.QtGui import QImage

    img = QImage(str(out))
    natural_w = sum(c.width() for c in widget._canvases) + 150 * (len(widget._canvases) - 1)
    assert img.width() == natural_w
    assert img.height() == 600


def test_width_px_scales_output(qapp, tmp_path):
    widget = _make_widget()
    out = tmp_path / "wide.png"
    widget.export_composite(str(out), fmt="png", width_px=1100)
    from PySide6.QtGui import QImage

    img = QImage(str(out))
    assert img.width() == 1100
    natural_w = sum(c.width() for c in widget._canvases) + 150
    assert img.height() == round(600 * 1100 / natural_w)


def test_png_dpi_metadata(qapp, tmp_path):
    widget = _make_widget()
    out = tmp_path / "dpi.png"
    widget.export_composite(str(out), fmt="png", dpi=300)
    from PySide6.QtGui import QImage

    img = QImage(str(out))
    assert img.dotsPerMeterX() == int(300 / 0.0254)
    assert img.dotsPerMeterY() == int(300 / 0.0254)


def test_pdf_content_sized_and_a4(qapp, tmp_path):
    widget = _make_widget()
    out1 = tmp_path / "content.pdf"
    widget.export_composite(str(out1), fmt="pdf", dpi=150)
    assert out1.exists() and out1.stat().st_size > 500
    out2 = tmp_path / "a4.pdf"
    widget.export_composite(str(out2), fmt="pdf", page_size="A4")
    assert out2.exists() and out2.stat().st_size > 500


def test_svg_width_px_changes_viewbox(qapp, tmp_path):
    widget = _make_widget()
    out = tmp_path / "scaled.svg"
    widget.export_composite(str(out), fmt="svg", width_px=1000)
    text = out.read_text(encoding="utf-8")
    assert 'width="1000"' in text or "width='1000'" in text


def test_positional_call_still_works(qapp, tmp_path):
    """export_service compatibility: positional (path, fmt) call."""
    widget = _make_widget()
    out = tmp_path / "pos.svg"
    widget.export_composite(str(out), "svg")
    assert out.exists()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_export_composite_options.py -v
```

预期：FAIL（`TypeError: export_composite() got an unexpected keyword argument 'dpi'` 等）。

- [ ] **Step 3: 实现引擎改动**

将 `cross_well_widget.py` 中 `export_composite`、`_export_svg`、`_export_pdf`、`_export_png` 四个方法整体替换为（`_paint_composite` 不动）：

```python
    def export_composite(self, path: str, fmt: str = "svg", *,
                         dpi: int = 96, width_px: int | None = None,
                         page_size: str | None = None):
        """Export all canvases + correlation polygons as a single file.

        Optional keyword args (defaults preserve legacy behavior):
        ``dpi`` — PNG dots-per-meter metadata / PDF resolution.
        ``width_px`` — rescale output width (height proportional); all formats.
        ``page_size`` — PDF only: "A4" or "LETTER", content fitted to the page.
        """
        if not self._canvases:
            return

        spacing = self._well_spacing
        natural_w = sum(c.width() for c in self._canvases) + \
                    spacing * (len(self._canvases) - 1)
        natural_h = max(c.height() for c in self._canvases)

        if width_px and width_px > 0 and not page_size:
            scale = width_px / natural_w
        else:
            scale = 1.0
        total_w = max(1, int(round(natural_w * scale)))
        total_h = max(1, int(round(natural_h * scale)))

        if fmt == "svg":
            self._export_svg(path, total_w, total_h, natural_w, natural_h)
        elif fmt == "pdf":
            self._export_pdf(path, total_w, total_h, natural_w, natural_h, dpi, page_size)
        elif fmt == "png":
            self._export_png(path, total_w, total_h, natural_w, natural_h, dpi)

    def _export_svg(self, path: str, w: int, h: int, natural_w: int, natural_h: int):
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(QSize(w, h))
        gen.setViewBox(QRectF(0, 0, w, h))
        painter = QPainter(gen)
        painter.scale(w / natural_w, h / natural_h)
        self._paint_composite(painter, natural_w, natural_h)
        painter.end()

    def _export_pdf(self, path: str, w: int, h: int, natural_w: int, natural_h: int,
                    dpi: int, page_size: str | None):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setResolution(dpi)
        if page_size:
            page_id = (
                QPageSize.PageSizeId.A4
                if page_size.upper() == "A4"
                else QPageSize.PageSizeId.Letter
            )
            qps = QPageSize(page_id)
            if natural_w > natural_h:
                qps = QPageSize(page_id, QPageSize.Orientation.Landscape)
            printer.setPageSize(qps)
            size_pt = qps.size(QPageSize.Unit.Point)
            px_w = size_pt.width() * dpi / 72.0
            px_h = size_pt.height() * dpi / 72.0
            fit = min(px_w / natural_w, px_h / natural_h)
        else:
            mm_w = w * 25.4 / dpi
            mm_h = h * 25.4 / dpi
            printer.setPageSize(QPageSize(QSizeF(mm_w, mm_h), QPageSize.Unit.Millimeter))
            fit = w / natural_w
        painter = QPainter(printer)
        painter.scale(fit, fit)
        self._paint_composite(painter, natural_w, natural_h)
        painter.end()

    def _export_png(self, path: str, w: int, h: int, natural_w: int, natural_h: int,
                    dpi: int):
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))
        painter = QPainter(img)
        painter.scale(w / natural_w, h / natural_h)
        self._paint_composite(painter, natural_w, natural_h)
        painter.end()
        img.save(path)
```

行为核对（默认值 = 现状）：默认 `dpi=96, width_px=None, page_size=None` 时 `scale=1.0`，`total_w/h = natural_w/h`，各 `painter.scale(1,1)` 与原实现等价；PDF 毫米换算 `25.4/96` 与原硬编码一致。

- [ ] **Step 4: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests -q
```

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_cross_well_export.py -q
```

预期：全绿（既有 export 测试走默认参数，必须不受影响）。

- [ ] **Step 5: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/cross_well_widget.py packages/geoviz_well_log/tests/test_export_composite_options.py && git commit -m "feat(cross-well): optional dpi/width_px/page_size for export_composite"
```

---

### Task 2: 导出对话框与页面接线

**Files:**
- Create: `paleo_workbench/ui/pages/cross_well_export_dialog.py`
- Modify: `paleo_workbench/ui/pages/stratigraphy_correlation_page.py`（import、按钮文案、`_export_section` 方法）
- Test: `tests/test_cross_well_export_dialog.py`

**Interfaces:**
- Consumes: Task 1 的 `export_composite(path, fmt, *, dpi, width_px, page_size)`。
- Produces:
  - `paleo_workbench.ui.pages.cross_well_export_dialog.CrossWellExportDialog` — `QDialog`；控件 `format_combo` / `dpi_combo` / `width_spin` / `page_size_combo`；方法 `options() -> dict`，返回 `{"fmt": str, "dpi": int, "width_px": int | None, "page_size": str | None}`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cross_well_export_dialog.py`：

```python
"""Tests for CrossWellExportDialog and the rewired page export flow."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.ui.pages.cross_well_export_dialog import CrossWellExportDialog
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage


def test_dialog_defaults(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    opts = dlg.options()
    assert opts == {"fmt": "svg", "dpi": 150, "width_px": None, "page_size": None}


def test_dialog_png_enables_dpi(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    idx = dlg.format_combo.findData("png")
    dlg.format_combo.setCurrentIndex(idx)
    assert dlg.dpi_combo.isEnabled()
    assert dlg.page_size_combo.isEnabled() is False
    idx_pdf = dlg.format_combo.findData("pdf")
    dlg.format_combo.setCurrentIndex(idx_pdf)
    assert dlg.dpi_combo.isEnabled()
    assert dlg.page_size_combo.isEnabled()
    idx_svg = dlg.format_combo.findData("svg")
    dlg.format_combo.setCurrentIndex(idx_svg)
    assert dlg.dpi_combo.isEnabled() is False
    assert dlg.page_size_combo.isEnabled() is False


def test_dialog_options_roundtrip(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("png"))
    dlg.dpi_combo.setCurrentIndex(dlg.dpi_combo.findData(300))
    dlg.width_spin.setValue(2000)
    assert dlg.options() == {"fmt": "png", "dpi": 300, "width_px": 2000, "page_size": None}


def test_dialog_pdf_page_size(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))
    dlg.page_size_combo.setCurrentIndex(dlg.page_size_combo.findData("A4"))
    opts = dlg.options()
    assert opts["fmt"] == "pdf"
    assert opts["page_size"] == "A4"
    # Selecting a paper size makes explicit width meaningless
    assert opts["width_px"] is None


def test_page_export_flow(qtbot, monkeypatch, tmp_path):
    """_export_section: dialog options -> engine export_composite kwargs."""
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)

    calls = []

    class _StubInner:
        _canvases = [object()]

        def export_composite(self, path, fmt="svg", **kwargs):
            calls.append((path, fmt, kwargs))

    page.cross_host.inner = _StubInner()

    class _StubDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return 1

        def options(self):
            return {"fmt": "png", "dpi": 300, "width_px": 2000, "page_size": None}

    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setattr(mod, "CrossWellExportDialog", _StubDialog)
    monkeypatch.setattr(
        mod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "out.png"), "PNG (*.png)")),
    )
    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    page._export_section()
    assert len(calls) == 1
    path, fmt, kwargs = calls[0]
    assert path.endswith("out.png")
    assert fmt == "png"
    assert kwargs == {"dpi": 300, "width_px": 2000, "page_size": None}


def test_page_export_button_text(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert "SVG" not in page.export_btn.text()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_cross_well_export_dialog.py -v
```

预期：FAIL（`ModuleNotFoundError: paleo_workbench.ui.pages.cross_well_export_dialog`）。

- [ ] **Step 3: 实现对话框**

创建 `paleo_workbench/ui/pages/cross_well_export_dialog.py`：

```python
"""Export options dialog for the cross-well correlation section."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CrossWellExportDialog(QDialog):
    """Pick export format, DPI, width and PDF page size."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("导出连井剖面")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_combo = QComboBox()
        self.format_combo.addItem("SVG 矢量图", "svg")
        self.format_combo.addItem("PNG 位图", "png")
        self.format_combo.addItem("PDF 文档", "pdf")
        self.format_combo.currentIndexChanged.connect(self._update_enabled)
        form.addRow("格式", self.format_combo)

        self.dpi_combo = QComboBox()
        for dpi in (96, 150, 300):
            self.dpi_combo.addItem(str(dpi), dpi)
        self.dpi_combo.setCurrentIndex(1)  # 150
        form.addRow("DPI", self.dpi_combo)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(0, 20000)
        self.width_spin.setSingleStep(100)
        self.width_spin.setSpecialValueText("自然宽度")
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(0)
        form.addRow("宽度", self.width_spin)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItem("内容尺寸", None)
        self.page_size_combo.addItem("A4", "A4")
        self.page_size_combo.addItem("Letter", "LETTER")
        form.addRow("纸张", self.page_size_combo)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_enabled()

    def _update_enabled(self) -> None:
        fmt = self.format_combo.currentData()
        self.dpi_combo.setEnabled(fmt in ("png", "pdf"))
        self.page_size_combo.setEnabled(fmt == "pdf")
        self.width_spin.setEnabled(
            not (fmt == "pdf" and self.page_size_combo.currentData() is not None)
        )

    def options(self) -> dict:
        fmt = self.format_combo.currentData()
        page_size = self.page_size_combo.currentData() if fmt == "pdf" else None
        width_px = self.width_spin.value() or None
        if page_size is not None:
            width_px = None
        return {
            "fmt": fmt,
            "dpi": self.dpi_combo.currentData(),
            "width_px": width_px,
            "page_size": page_size,
        }
```

注意 `page_size_combo.currentIndexChanged` 也需连到 `_update_enabled`（选择纸张后禁用宽度 spin）——在 `__init__` 中补一行 `self.page_size_combo.currentIndexChanged.connect(self._update_enabled)`。

- [ ] **Step 4: 页面接线**

`paleo_workbench/ui/pages/stratigraphy_correlation_page.py`：

**4a.** import 区新增：

```python
from paleo_workbench.ui.pages.cross_well_export_dialog import CrossWellExportDialog
```

**4b.** 按钮文案 `"导出连井 SVG"` 改为 `"导出连井剖面"`。

**4c.** `_export_section` 方法体整体替换为：

```python
    def _export_section(self) -> None:
        inner = self.cross_host.inner
        if not getattr(inner, "_canvases", None):
            QMessageBox.warning(self, "导出", "请先加载连井剖面")
            return
        dialog = CrossWellExportDialog(self)
        if not dialog.exec():
            return
        opts = dialog.options()
        fmt = opts["fmt"]
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出连井剖面",
            str(start_dir / f"cross_well_correlation.{fmt}"),
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        try:
            inner.export_composite(
                path,
                fmt=fmt,
                dpi=opts["dpi"],
                width_px=opts["width_px"],
                page_size=opts["page_size"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")
```

- [ ] **Step 5: 运行测试确认通过 + 相关回归**

```bash
.venv/bin/python -m pytest tests/test_cross_well_export_dialog.py tests/test_stratigraphy_correlation_ui.py tests/test_stratigraphy_correlation.py -v
```

预期：全绿。

- [ ] **Step 6: workbench 全量回归**

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿（已知 flake `tests/test_project_lifecycle.py::test_save_as_writes_file_and_stores_path` 若在全量中失败、单独跑通过，记录即可，不属于本任务）。

- [ ] **Step 7: 提交（仓库根，含子模块 gitlink）**

```bash
git add paleo_workbench/ui/pages/cross_well_export_dialog.py paleo_workbench/ui/pages/stratigraphy_correlation_page.py tests/test_cross_well_export_dialog.py geo-viz-engine && git commit -m "feat(ui): cross-well export dialog with format/dpi/width/page-size options"
```

---

### Task 3: 最终回归与文档记录

**Files:**
- Modify: `task_plan.md`、`progress.md`

**Interfaces:**
- Consumes: Task 1-2 完成。
- Produces: 无代码产出。

- [ ] **Step 1: 双仓库回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests tests/test_cross_well_export.py -q
```

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿（flake 同上，记录即可）。

- [ ] **Step 2: 更新 task_plan.md 与 progress.md**

`task_plan.md` Phase 12 后追加：

```markdown
### Phase 13: 连井对比 P3 导出增强

- [x] 引擎 `export_composite` 增加仅关键字可选参数 `dpi` / `width_px` / `page_size`（默认行为不变，兼容 export_service 位置调用）
- [x] 新增 `CrossWellExportDialog`（格式 SVG/PNG/PDF、DPI 96/150/300、宽度、PDF 纸张 A4/Letter）
- [x] 地层对比页导出按钮改为对话框流程
- **Status:** complete
```

`progress.md` 追加对应一行 session 记录。

- [ ] **Step 3: 提交（仓库根）**

```bash
git add task_plan.md progress.md && git commit -m "docs(plan): record phase 13 cross-well export enhancement"
```

---

## Self-Review 记录

- **Spec 覆盖**：引擎可选参数（dpi/width_px/page_size → Task 1）；导出对话框（格式/DPI/文件名 → Task 2，文件名走 QFileDialog 与现状一致）；`export_service` 位置调用兼容（Task 1 关键字-only 设计 + `test_positional_call_still_works`）。spec 的 P3 全部条目有任务对应。
- **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致性**：`export_composite(path, fmt="svg", *, dpi=96, width_px=None, page_size=None)` 在 Task 1 定义、Task 2 消费一致；`options()` 返回 dict 的 4 个键与 `_export_section` 解包一致；对话框控件名（`format_combo`/`dpi_combo`/`width_spin`/`page_size_combo`）测试与实现一致。
- **默认行为核对**：`dpi=96/width_px=None/page_size=None` 时与原实现逐点等价（scale=1.0、PDF 毫米换算 25.4/96 一致），既有 `test_cross_well_export.py` 与 `export_service` 不受影响。
