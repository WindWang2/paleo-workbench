# Context Menu + Format Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-click context menu to the data page asset table with 6 actions (preview, rescan, export, open-folder, visualize, remove) + 4 format-conversion exporters.

**Architecture:** New `exporters.py` module with 4 pure converter functions + `get_available_formats()`. New `AssetContextMenu(QMenu)` with dynamic item visibility. `DataAssetTable` gains `customContextMenuRequested` support. `DataPage` wires menu signals to existing methods + new `_export_selected_asset`.

**Tech Stack:** PySide6 (QMenu, customContextMenuRequested), lasio, pandas, Pillow, rasterio.

**Spec:** `docs/superpowers/specs/2026-07-15-context-menu-export-design.md`

## Global Constraints

- Exporters are pure functions `convert(input_path: Path, output_path: Path) -> None` raising `ExportError` on failure.
- `get_available_formats(asset) -> list[tuple[str, callable]]` returns `[(label, convert_fn)]`; empty list for unsupported/artifact.
- AssetContextMenu signals: `preview_requested`, `rescan_requested`, `export_requested(str)`, `open_folder_requested`, `visualize_requested`, `remove_requested`.
- DataAssetTable gains `context_menu_requested = Signal(QPoint, object)` (global pos, asset).
- No selection -> no menu.
- Export submenu only shows formats with available converters for the asset.
- Stay on `main`. TDD. Frequent commits.

---

## Task 1: Format converters (exporters.py)

**Files:**
- Create: `paleo_workbench/resources/exporters.py`
- Test: `tests/test_exporters.py`

**Interfaces:**
- Produces: `ExportError`, `las_to_csv(path, out)`, `table_to_json(path, out)`, `image_to_png(path, out)`, `text_to_txt(path, out)`, `get_available_formats(asset) -> list[tuple[str, callable]]`.

- [ ] **Step 1: Write failing tests**

In `tests/test_exporters.py`:
```python
import json
from pathlib import Path
import pytest
from paleo_workbench.resources.exporters import (
    ExportError, las_to_csv, table_to_json, image_to_png, text_to_txt,
    get_available_formats,
)
from paleo_workbench.project.models import ResourceItem, ExportArtifact


def test_las_to_csv(tmp_path):
    las_content = "~V\nSTRT.M 0:\nSTOP.M 100:\nSTEP.M 1:\n~C\nDEPT.M  :\nGR.US/API  :\n~A\n0 50\n1 55\n"
    src = tmp_path / "well.las"
    src.write_text(las_content)
    out = tmp_path / "well.csv"
    las_to_csv(src, out)
    assert out.exists()
    text = out.read_text()
    assert "," in text  # CSV format


def test_table_to_json_csv(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("name,value\nalpha,1\nbeta,2\n")
    out = tmp_path / "data.json"
    table_to_json(src, out)
    data = json.loads(out.read_text())
    assert len(data) == 2
    assert data[0]["name"] == "alpha"


def test_image_to_png(tmp_path):
    from PIL import Image
    import numpy as np
    src = tmp_path / "img.bmp"
    Image.fromarray(np.zeros((4, 4, 3), dtype="uint8")).save(src)
    out = tmp_path / "img.png"
    image_to_png(src, out)
    assert out.exists()
    # Verify it's a valid PNG
    Image.open(out).verify()


def test_text_to_txt(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("# Title\n\nSome text.")
    out = tmp_path / "notes.txt"
    text_to_txt(src, out)
    assert out.read_text() == "# Title\n\nSome text."


def test_get_available_formats_las():
    res = ResourceItem(name="w.las", path="/w.las", type="well_log", format="las", status="parsed")
    fmts = get_available_formats(res)
    assert any(label == "CSV" for label, _ in fmts)


def test_get_available_formats_unknown():
    res = ResourceItem(name="x.xyz", path="/x.xyz", type="unknown", format="xyz", status="parsed")
    assert get_available_formats(res) == []


def test_get_available_formats_artifact():
    art = ExportArtifact(linked_id="m1", format="PDF", output_path="/m.pdf")
    assert get_available_formats(art) == []


def test_export_error_on_missing_file(tmp_path):
    with pytest.raises(ExportError):
        text_to_txt(tmp_path / "nonexistent.md", tmp_path / "out.txt")
```

- [ ] **Step 2: Run - expect FAIL (module missing)**

- [ ] **Step 3: Implement exporters.py**

```python
"""Format conversion exporters for the data page."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from paleo_workbench.project.models import ExportArtifact, ResourceItem


class ExportError(Exception):
    """Raised when a format conversion fails."""


# Input format sets
_LAS_FORMATS = {"las"}
_TABLE_FORMATS = {"csv", "xlsx", "xls"}
_IMAGE_FORMATS = {"tif", "tiff", "png", "jpg", "jpeg", "bmp"}
_TEXT_FORMATS = {"txt", "md", "markdown", "json", "xml", "log", "dat"}


def las_to_csv(input_path: Path, output_path: Path) -> None:
    try:
        import lasio
        import pandas as pd
        las = lasio.read(str(input_path))
        df = las.df()
        df.to_csv(output_path, index=True)
    except Exception as exc:
        raise ExportError(f"LAS -> CSV 失败: {exc}") from exc


def table_to_json(input_path: Path, output_path: Path) -> None:
    try:
        import pandas as pd
        ext = input_path.suffix.lower()
        if ext == "csv":
            df = pd.read_csv(input_path)
        else:
            df = pd.read_excel(input_path)
        df.to_json(output_path, orient="records", force_ascii=False)
    except Exception as exc:
        raise ExportError(f"表格 -> JSON 失败: {exc}") from exc


def image_to_png(input_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image
        img = Image.open(input_path)
        img.save(output_path, "PNG")
    except Exception as exc:
        raise ExportError(f"图像 -> PNG 失败: {exc}") from exc


def text_to_txt(input_path: Path, output_path: Path) -> None:
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
        output_path.write_text(text, encoding="utf-8")
    except Exception as exc:
        raise ExportError(f"文本 -> TXT 失败: {exc}") from exc


# Registry: (label, input_formats, convert_fn)
_CONVERTERS: list[tuple[str, set[str], Callable]] = [
    ("CSV", _LAS_FORMATS, las_to_csv),
    ("JSON", _TABLE_FORMATS, table_to_json),
    ("PNG", _IMAGE_FORMATS, image_to_png),
    ("TXT", _TEXT_FORMATS, text_to_txt),
]


def get_available_formats(asset: ResourceItem | ExportArtifact) -> list[tuple[str, Callable]]:
    """Return [(label, convert_fn), ...] for formats the asset can export to."""
    if isinstance(asset, ExportArtifact):
        return []
    fmt = asset.format.lower()
    return [(label, fn) for label, inputs, fn in _CONVERTERS if fmt in inputs]
```

- [ ] **Step 4: Run - expect PASS + full suite (safe tests) + commit**

```bash
source .venv/bin/activate && python -m pytest tests/test_exporters.py -q
git add paleo_workbench/resources/exporters.py tests/test_exporters.py
git commit -m "feat: add format conversion exporters (LAS->CSV, table->JSON, image->PNG, text->TXT)"
```

---

## Task 2: AssetContextMenu

**Files:**
- Create: `paleo_workbench/ui/pages/asset_context_menu.py`
- Test: `tests/test_asset_context_menu.py`

**Interfaces:**
- Produces: `AssetContextMenu(QMenu)` with `build(asset, viz_supported)` + 6 signals.

- [ ] **Step 1: Write failing tests**

In `tests/test_asset_context_menu.py`:
```python
from paleo_workbench.project.models import ResourceItem, ExportArtifact
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu


def _res(fmt="las", rtype="well_log"):
    return ResourceItem(name="x", path=f"/x.{fmt}", type=rtype, format=fmt, status="parsed")


def test_menu_empty_when_no_asset(qtbot):
    menu = AssetContextMenu()
    menu.build(None, viz_supported=False)
    assert menu.actions() == []


def test_menu_has_preview_always(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert any(a.text() == "预览" for a in menu.actions())


def test_menu_rescan_only_for_resource(qtbot):
    menu = AssetContextMenu()
    art = ExportArtifact(linked_id="m1", format="PDF", output_path="/m.pdf")
    menu.build(art, viz_supported=False)
    assert not any(a.text() == "重新扫描" for a in menu.actions())

    menu2 = AssetContextMenu()
    menu2.build(_res(), viz_supported=False)
    assert any(a.text() == "重新扫描" for a in menu2.actions())


def test_menu_export_hidden_when_no_converters(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(fmt="unknown"), viz_supported=False)
    assert not any(a.text() == "导出" for a in menu.actions())


def test_menu_export_shown_with_subitems(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(fmt="las"), viz_supported=False)
    export_action = next(a for a in menu.actions() if a.text() == "导出")
    assert export_action.menu() is not None
    sub_labels = [a.text() for a in export_action.menu().actions()]
    assert "CSV" in sub_labels


def test_menu_visualize_hidden_when_unsupported(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert not any("可视化" in a.text() for a in menu.actions())


def test_menu_remove_always_present(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert any(a.text() == "移出项目" for a in menu.actions())
```

- [ ] **Step 2: Run - expect FAIL**

- [ ] **Step 3: Implement AssetContextMenu**

```python
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.exporters import get_available_formats
from paleo_workbench.ui import tokens


class AssetContextMenu(QMenu):
    """Right-click context menu for the data page asset table."""

    # Signals are defined on the parent QMenu implicitly via actions.
    # DataPage connects action.triggered to its methods.

    def __init__(self, parent=None):
        super().__init__(parent)
        self._export_actions: list[tuple[str, QAction]] = []

    def build(self, asset: ResourceItem | ExportArtifact | None, viz_supported: bool) -> None:
        """Populate menu items based on the selected asset."""
        self.clear()
        self._export_actions = []
        if asset is None:
            return

        # 预览
        preview = QAction("预览", self)
        preview.setObjectName("ctx_preview")
        self.addAction(preview)

        # 重新扫描 (ResourceItem only)
        if isinstance(asset, ResourceItem):
            rescan = QAction("重新扫描", self)
            rescan.setObjectName("ctx_rescan")
            self.addAction(rescan)

        # 导出 (only when converters available)
        formats = get_available_formats(asset)
        if formats:
            export_menu = QMenu("导出", self)
            for label, _fn in formats:
                sub = QAction(label, export_menu)
                sub.setObjectName(f"ctx_export_{label}")
                export_menu.addAction(sub)
                self._export_actions.append((label, sub))
            export_action = QAction("导出", self)
            export_action.setMenu(export_menu)
            self.addAction(export_action)

        # 打开目录
        open_folder = QAction("打开目录", self)
        open_folder.setObjectName("ctx_open_folder")
        self.addAction(open_folder)

        # 在可视化页面打开 (ResourceItem + viz supported)
        if viz_supported:
            visualize = QAction("在可视化页面打开", self)
            visualize.setObjectName("ctx_visualize")
            self.addAction(visualize)

        # Separator
        self.addSeparator()

        # 移出项目
        remove = QAction("移出项目", self)
        remove.setObjectName("ctx_remove")
        self.addAction(remove)

    def find_action(self, object_name: str) -> QAction | None:
        """Find a top-level action by objectName."""
        for action in self.actions():
            if action.objectName() == object_name:
                return action
        return None

    def find_export_action(self, label: str) -> QAction | None:
        """Find a sub-menu export action by label."""
        for lbl, action in self._export_actions:
            if lbl == label:
                return action
        return None
```

- [ ] **Step 4: Run - expect PASS + commit**

```bash
python -m pytest tests/test_asset_context_menu.py -q
git add paleo_workbench/ui/pages/asset_context_menu.py tests/test_asset_context_menu.py
git commit -m "feat: add AssetContextMenu with dynamic item visibility"
```

---

## Task 3: DataAssetTable context menu support + DataPage wiring

**Files:**
- Modify: `paleo_workbench/ui/pages/data_asset_table.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Test: `tests/test_data_page.py` (extend)

**Interfaces:**
- DataAssetTable gains `context_menu_requested = Signal(QPoint, object)`.
- DataPage gains `_show_context_menu(global_pos, asset)` + `_export_selected_asset(format_label)`.

- [ ] **Step 1: Add context menu support to DataAssetTable**

In `data_asset_table.py`:
- Add import: `from PySide6.QtCore import QPoint, Qt, Signal` (Signal already imported; add QPoint, Qt if missing).
- Add class-level signal: `context_menu_requested = Signal(QPoint, object)`.
- In `__init__`, after table setup: `self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)`.
- Connect: `self.table.customContextMenuRequested.connect(self._on_context_menu)`.
- Add method:
```python
    def _on_context_menu(self, pos: QPoint) -> None:
        view_row = self.table.rowAt(pos.y())
        if view_row < 0:
            return
        # Select the row under cursor
        self.table.selectRow(view_row)
        asset = self.asset_at(view_row)
        if asset is None:
            return
        global_pos = self.table.viewport().mapToGlobal(pos)
        self.context_menu_requested.emit(global_pos, asset)
```

- [ ] **Step 2: Wire context menu in DataPage**

In `data_page.py`:
- Import `AssetContextMenu`.
- In `__init__`, after existing signal wiring: `self.asset_table.context_menu_requested.connect(self._show_context_menu)`.
- Add method:
```python
    def _show_context_menu(self, global_pos, asset) -> None:
        viz_supported = isinstance(asset, ResourceItem) and self._viz_adapter.supports_resource(asset)
        menu = AssetContextMenu(self)
        menu.build(asset, viz_supported)

        # Wire actions
        preview_act = menu.find_action("ctx_preview")
        if preview_act:
            preview_act.triggered.connect(lambda: self._preview_controller.request(asset))

        rescan_act = menu.find_action("ctx_rescan")
        if rescan_act:
            rescan_act.triggered.connect(self.rescan_selected_asset)

        open_folder_act = menu.find_action("ctx_open_folder")
        if open_folder_act:
            open_folder_act.triggered.connect(self.open_selected_folder)

        visualize_act = menu.find_action("ctx_visualize")
        if visualize_act:
            visualize_act.triggered.connect(self._emit_open_visualization)

        remove_act = menu.find_action("ctx_remove")
        if remove_act:
            remove_act.triggered.connect(self.remove_selected_asset)

        # Wire export sub-actions
        from paleo_workbench.resources.exporters import get_available_formats
        for label, _fn in get_available_formats(asset):
            sub_act = menu.find_export_action(label)
            if sub_act:
                sub_act.triggered.connect(lambda checked=False, fmt=label: self._export_selected_asset(fmt))

        menu.exec(global_pos)

    def _export_selected_asset(self, format_label: str) -> None:
        from paleo_workbench.resources.exporters import get_available_formats
        from PySide6.QtWidgets import QFileDialog
        asset = self._selected_asset
        if asset is None:
            return
        if isinstance(asset, ExportArtifact):
            return
        formats = get_available_formats(asset)
        convert_fn = next((fn for lbl, fn in formats if lbl == format_label), None)
        if convert_fn is None:
            return
        input_path = Path(asset.path)
        # Determine output extension from the converter
        ext_map = {"CSV": ".csv", "JSON": ".json", "PNG": ".png", "TXT": ".txt"}
        out_ext = ext_map.get(format_label, ".out")
        suggested = f"{input_path.stem}{out_ext}"
        output_path, _ = QFileDialog.getSaveFileName(self, "导出为", suggested)
        if not output_path:
            return
        output_path = Path(output_path)
        try:
            convert_fn(input_path, output_path)
            self._set_action_status(f"已导出: {output_path.name}")
        except Exception as exc:
            self._set_action_status(f"导出失败: {exc}")
```

- [ ] **Step 3: Write integration tests**

In `tests/test_data_page.py` (extend):
```python
def test_context_menu_triggers_remove(qtbot, tmp_path):
    project = ProjectDocument.new("Test")
    project.resources.append(ResourceItem(name="r.las", path="/r.las", type="well_log", format="las", status="parsed"))
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    # Select the resource
    page.asset_table.table.selectRow(0)
    # Build menu and trigger remove
    from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
    menu = AssetContextMenu()
    menu.build(page._selected_asset, viz_supported=False)
    remove_act = menu.find_action("ctx_remove")
    remove_act.triggered.connect(page.remove_selected_asset)
    remove_act.trigger()
    assert len(page.project.resources) == 0


def test_context_menu_export_las_to_csv(qtbot, tmp_path):
    las_content = "~V\nSTRT.M 0:\nSTOP.M 10:\nSTEP.M 1:\n~C\nDEPT.M  :\n~A\n0\n1\n"
    src = tmp_path / "well.las"
    src.write_text(las_content)
    project = ProjectDocument.new("Test")
    project.resources.append(ResourceItem(name="well.las", path=str(src), type="well_log", format="las", status="parsed"))
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)
    # Simulate export: monkeypatch QFileDialog to return a path
    out_path = tmp_path / "out.csv"
    from unittest.mock import patch
    with patch("paleo_workbench.ui.pages.data_page.QFileDialog.getSaveFileName", return_value=(str(out_path), "")):
        page._export_selected_asset("CSV")
    assert out_path.exists()
```

- [ ] **Step 4: Run tests + commit**

```bash
python -m pytest tests/test_data_page.py tests/test_asset_context_menu.py tests/test_exporters.py -q
git add paleo_workbench/ui/pages/data_asset_table.py paleo_workbench/ui/pages/data_page.py tests/test_data_page.py
git commit -m "feat: wire context menu into data page with export support"
```

---

## Task 4: Final review + ledger sync

**Actions:**
- Whole-branch review: menu builds correctly per asset type; converters work; export dialog + conversion flow; no regressions.
- Run safe tests (avoid WebEngine hang).
- Update `task_plan.md` / `progress.md` / `findings.md`.

**Commit:** `chore: sync SDD progress ledger (Context Menu + Export complete)`

## Self-Review (completed during authoring)

- **Spec coverage:** exporters (Task 1), AssetContextMenu (Task 2), DataAssetTable + DataPage wiring + export flow (Task 3). All 8 acceptance criteria map to tasks. ✓
- **Placeholder scan:** Every step has concrete code. No TBD. ✓
- **Consistency:** `get_available_formats` return type `list[tuple[str, Callable]]` consistent across exporters + menu + DataPage. Signal/action objectName pattern (`ctx_*`) consistent. ✓
- **Risk addressed:** QFileDialog monkeypatched in test (Task 3 Step 3) to avoid real dialog; `rowAt(pos.y())` used for viewport row mapping. ✓
