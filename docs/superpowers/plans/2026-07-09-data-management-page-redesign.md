# Data Management Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the data page as a file/data/results manager with a left data table, right multi-format reader, and floating catalog/action panels.

**Architecture:** Introduce a `DataWorkspace` container that owns the table/reader splitter and overlay panels. Keep `DataPage` as the orchestration layer for project state, import threading, selection, and signals. Upgrade preview rendering incrementally by adding focused preview widgets and library-backed provider modes.

**Tech Stack:** Python, PySide6, pytest-qt, `PySide6.QtPdfWidgets.QPdfView`, `pandas`, `openpyxl`, `lasio`, optional `segyio`/geo-viz-engine hooks.

## Global Constraints

- Keep import, scanning, checksum, and heavy parsing off the UI thread.
- Keep existing async import behavior and tests passing.
- Catalog and action panels must be overlays, not splitter children.
- Table and reader are the dominant first-viewport content.
- `DataAssetTable` keeps existing column customization behavior.
- Supported formats render in the reader using format-specific library-backed widgets.
- Missing preview dependencies degrade to a message view and never crash the page.
- Full SEG-Y trace visualization, full LAS curve plotting, drag-resizing floating panels, and persisted panel positions are out of scope for this implementation.

---

## File Structure

- Create `paleo_workbench/ui/pages/floating_panel.py`: reusable overlay frame with collapsed/expanded state and a tab button.
- Create `paleo_workbench/ui/pages/data_toolbar.py`: top data page toolbar with import/search/column/reader/catalog controls.
- Create `paleo_workbench/ui/pages/data_workspace.py`: owns splitter, table, reader, floating catalog panel, and floating action panel.
- Modify `paleo_workbench/ui/pages/data_page.py`: replace fixed side-by-side layout with toolbar + workspace, keep import/selection orchestration.
- Modify `paleo_workbench/ui/pages/data_reader_panel.py`: delegate rendering to format-specific widgets while preserving existing public fields used by tests.
- Modify `paleo_workbench/ui/pages/preview_provider.py`: add library-backed Excel/LAS/SEG-Y preview modes and richer metadata.
- Create `paleo_workbench/ui/pages/preview_widgets.py`: `PdfPreviewWidget`, `ImagePreviewWidget`, `TablePreviewWidget`, `TextPreviewWidget`, `MessagePreviewWidget`, `SummaryTablePreviewWidget`.
- Modify `paleo_workbench/ui/pages/__init__.py`: export `DataToolbar`, `DataWorkspace`, and `FloatingPanel`.
- Modify tests:
  - `tests/test_data_page.py`
  - `tests/test_data_reader_panel.py`
  - `tests/test_preview_provider.py`
  - add `tests/test_data_workspace.py`
  - add `tests/test_floating_panel.py`
  - add `tests/test_data_toolbar.py`

---

### Task 1: Floating Panel Component

**Files:**
- Create: `paleo_workbench/ui/pages/floating_panel.py`
- Create: `tests/test_floating_panel.py`

**Interfaces:**
- Produces: `FloatingPanel(title: str, tab_text: str, content: QWidget | None = None, parent=None)`
- Produces: `FloatingPanel.set_content(widget: QWidget) -> None`
- Produces: `FloatingPanel.set_expanded(expanded: bool) -> None`
- Produces: `FloatingPanel.is_expanded() -> bool`
- Produces signal: `expanded_changed = Signal(bool)`
- Produces attributes for tests and wiring: `tab_button`, `content_frame`, `title_label`

- [ ] **Step 1: Write failing component tests**

Add `tests/test_floating_panel.py`:

```python
from PySide6.QtWidgets import QLabel

from paleo_workbench.ui.pages.floating_panel import FloatingPanel


def test_floating_panel_starts_collapsed_with_tab_visible(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)

    assert panel.is_expanded() is False
    assert panel.tab_button.isVisible() is True
    assert panel.content_frame.isVisible() is False
    assert panel.tab_button.text() == "目录"


def test_floating_panel_expands_and_collapses(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)
    received = []
    panel.expanded_changed.connect(received.append)

    panel.set_expanded(True)
    panel.set_expanded(False)

    assert received == [True, False]
    assert panel.is_expanded() is False
    assert panel.content_frame.isVisible() is False


def test_floating_panel_accepts_content_widget(qtbot):
    label = QLabel("内容")
    panel = FloatingPanel(title="操作", tab_text="操作", content=label)
    qtbot.addWidget(panel)

    panel.set_expanded(True)

    assert label.parent() is panel.content_frame
    assert label.isVisible() is True
    assert panel.title_label.text() == "操作"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'paleo_workbench.ui.pages.floating_panel'`.

- [ ] **Step 3: Implement `FloatingPanel`**

Create `paleo_workbench/ui/pages/floating_panel.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class FloatingPanel(QFrame):
    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        tab_text: str,
        content: QWidget | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("FloatingPanel")
        self._expanded = False
        self.setStyleSheet(
            f"QFrame#FloatingPanel {{ background: transparent; border: none; }}"
            f"QFrame#FloatingPanelContent {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_PANEL}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.tab_button = QPushButton(tab_text)
        self.tab_button.setObjectName("PrimaryButton")
        self.tab_button.clicked.connect(lambda: self.set_expanded(not self._expanded))
        layout.addWidget(self.tab_button)

        self.content_frame = QFrame()
        self.content_frame.setObjectName("FloatingPanelContent")
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        content_layout.addWidget(self.title_label)

        if content is not None:
            self.set_content(content)

        layout.addWidget(self.content_frame)
        self.set_expanded(False)

    def set_content(self, widget: QWidget) -> None:
        widget.setParent(self.content_frame)
        self.content_frame.layout().addWidget(widget)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            self.content_frame.setVisible(expanded)
            return
        self._expanded = expanded
        self.content_frame.setVisible(expanded)
        self.expanded_changed.emit(expanded)
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/floating_panel.py tests/test_floating_panel.py
git commit -m "feat: add floating panel component"
```

---

### Task 2: Data Toolbar

**Files:**
- Create: `paleo_workbench/ui/pages/data_toolbar.py`
- Create: `tests/test_data_toolbar.py`

**Interfaces:**
- Produces: `DataToolbar(QWidget)`
- Produces signals: `import_files_requested`, `import_folder_requested`, `rescan_requested`, `catalog_toggled`, `reader_toggled`, `search_changed = Signal(str)`
- Produces attributes: `import_btn`, `import_folder_btn`, `rescan_btn`, `search_box`, `column_settings_slot`, `catalog_btn`, `reader_btn`
- Produces: `DataToolbar.set_column_settings_button(button: QPushButton) -> None`

- [ ] **Step 1: Write failing toolbar tests**

Add `tests/test_data_toolbar.py`:

```python
from PySide6.QtWidgets import QPushButton

from paleo_workbench.ui.pages.data_toolbar import DataToolbar


def test_data_toolbar_exposes_actions_and_search(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    received = []
    toolbar.search_changed.connect(received.append)

    toolbar.search_box.setText("well")

    assert toolbar.import_btn.text() == "导入文件"
    assert toolbar.import_folder_btn.text() == "导入目录"
    assert toolbar.rescan_btn.text() == "重新扫描"
    assert toolbar.catalog_btn.text() == "目录"
    assert toolbar.reader_btn.text() == "阅读器"
    assert received[-1] == "well"


def test_data_toolbar_rehomes_column_settings_button(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    button = QPushButton("列设置")

    toolbar.set_column_settings_button(button)

    assert button.parent() is toolbar
    assert toolbar.column_settings_slot.layout().indexOf(button) >= 0
```

- [ ] **Step 2: Run tests to verify RED**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_toolbar.py -q`

Expected: FAIL with missing `data_toolbar` module.

- [ ] **Step 3: Implement `DataToolbar`**

Create `paleo_workbench/ui/pages/data_toolbar.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class DataToolbar(QWidget):
    import_files_requested = Signal()
    import_folder_requested = Signal()
    rescan_requested = Signal()
    catalog_toggled = Signal()
    reader_toggled = Signal()
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataToolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.import_btn = QPushButton("导入文件")
        self.import_btn.setObjectName("PrimaryButton")
        self.import_btn.clicked.connect(self.import_files_requested)
        layout.addWidget(self.import_btn)

        self.import_folder_btn = QPushButton("导入目录")
        self.import_folder_btn.setObjectName("SecondaryButton")
        self.import_folder_btn.clicked.connect(self.import_folder_requested)
        layout.addWidget(self.import_folder_btn)

        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.setObjectName("SecondaryButton")
        self.rescan_btn.clicked.connect(self.rescan_requested)
        layout.addWidget(self.rescan_btn)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索文件名 / 类型 / 格式 / 路径...")
        self.search_box.textChanged.connect(self.search_changed)
        layout.addWidget(self.search_box, 1)

        self.column_settings_slot = QWidget()
        self.column_settings_slot.setLayout(QHBoxLayout())
        self.column_settings_slot.layout().setContentsMargins(0, 0, 0, 0)
        self.column_settings_slot.layout().setSpacing(0)
        layout.addWidget(self.column_settings_slot)

        self.catalog_btn = QPushButton("目录")
        self.catalog_btn.setObjectName("SecondaryButton")
        self.catalog_btn.clicked.connect(self.catalog_toggled)
        layout.addWidget(self.catalog_btn)

        self.reader_btn = QPushButton("阅读器")
        self.reader_btn.setObjectName("SecondaryButton")
        self.reader_btn.clicked.connect(self.reader_toggled)
        layout.addWidget(self.reader_btn)

    def set_column_settings_button(self, button: QPushButton) -> None:
        button.setParent(self)
        self.column_settings_slot.layout().addWidget(button)
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_toolbar.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/data_toolbar.py tests/test_data_toolbar.py
git commit -m "feat: add data page toolbar"
```

---

### Task 3: Data Workspace Layout With Floating Overlays

**Files:**
- Create: `paleo_workbench/ui/pages/data_workspace.py`
- Create: `tests/test_data_workspace.py`
- Modify: `tests/test_data_page.py`

**Interfaces:**
- Consumes: `FloatingPanel`
- Consumes: `DataAssetTable`, `DataReaderPanel`, `DataCatalogPanel`, `ActionPanel`
- Produces: `DataWorkspace(QWidget)`
- Produces attributes: `content_splitter`, `asset_table`, `reader_panel`, `catalog_panel`, `action_panel`, `catalog_floating_panel`, `actions_floating_panel`
- Produces: `DataWorkspace.toggle_catalog_panel() -> None`
- Produces: `DataWorkspace.toggle_actions_panel() -> None`
- Produces: `DataWorkspace.set_reader_visible(visible: bool) -> None`

- [ ] **Step 1: Write failing workspace tests**

Add `tests/test_data_workspace.py`:

```python
from PySide6.QtWidgets import QSplitter

from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_workspace import DataWorkspace


def test_data_workspace_uses_splitter_for_table_and_reader_only(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    assert isinstance(workspace.content_splitter, QSplitter)
    assert isinstance(workspace.asset_table, DataAssetTable)
    assert isinstance(workspace.reader_panel, DataReaderPanel)
    assert workspace.content_splitter.indexOf(workspace.asset_table) == 0
    assert workspace.content_splitter.indexOf(workspace.reader_panel) == 1
    assert workspace.content_splitter.indexOf(workspace.catalog_panel) == -1
    assert workspace.content_splitter.indexOf(workspace.action_panel) == -1


def test_data_workspace_wraps_catalog_and_actions_in_floating_panels(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    assert isinstance(workspace.catalog_panel, DataCatalogPanel)
    assert isinstance(workspace.action_panel, ActionPanel)
    assert workspace.catalog_floating_panel.is_expanded() is False
    assert workspace.actions_floating_panel.is_expanded() is True


def test_data_workspace_toggles_catalog_and_reader(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    workspace.toggle_catalog_panel()
    workspace.set_reader_visible(False)

    assert workspace.catalog_floating_panel.is_expanded() is True
    assert workspace.reader_panel.isVisible() is False
```

- [ ] **Step 2: Run tests to verify RED**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py -q`

Expected: FAIL with missing `data_workspace` module.

- [ ] **Step 3: Implement `DataWorkspace`**

Create `paleo_workbench/ui/pages/data_workspace.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSplitter, QWidget

from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.floating_panel import FloatingPanel


class DataWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataWorkspace")

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("DataContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.asset_table = DataAssetTable()
        self.reader_panel = DataReaderPanel()
        self.content_splitter.addWidget(self.asset_table)
        self.content_splitter.addWidget(self.reader_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([720, 520])
        layout.addWidget(self.content_splitter, 0, 0)

        self.catalog_panel = DataCatalogPanel()
        self.catalog_floating_panel = FloatingPanel(
            title="目录 / 筛选",
            tab_text="目录",
            content=self.catalog_panel,
        )
        layout.addWidget(self.catalog_floating_panel, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.action_panel = ActionPanel()
        self.actions_floating_panel = FloatingPanel(
            title="导入 / 操作",
            tab_text="操作",
            content=self.action_panel,
        )
        self.actions_floating_panel.set_expanded(True)
        layout.addWidget(self.actions_floating_panel, 0, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

    def toggle_catalog_panel(self) -> None:
        self.catalog_floating_panel.set_expanded(
            not self.catalog_floating_panel.is_expanded()
        )

    def toggle_actions_panel(self) -> None:
        self.actions_floating_panel.set_expanded(
            not self.actions_floating_panel.is_expanded()
        )

    def set_reader_visible(self, visible: bool) -> None:
        self.reader_panel.setVisible(visible)
```

- [ ] **Step 4: Run workspace tests to verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Add DataPage assembly failing test**

Modify `tests/test_data_page.py`:

```python
from paleo_workbench.ui.pages.data_workspace import DataWorkspace


def test_data_page_uses_workspace_toolbar_and_floating_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.workspace, DataWorkspace)
    assert page.catalog_panel is page.workspace.catalog_panel
    assert page.action_panel is page.workspace.action_panel
    assert page.content_splitter.indexOf(page.asset_table) == 0
    assert page.content_splitter.indexOf(page.reader_panel) == 1
    assert page.content_splitter.indexOf(page.catalog_panel) == -1
    assert page.content_splitter.indexOf(page.action_panel) == -1
```

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_uses_workspace_toolbar_and_floating_panels -q`

Expected: FAIL because `DataPage` has no `workspace`.

- [ ] **Step 6: Wire `DataPage` to `DataWorkspace`**

Modify `paleo_workbench/ui/pages/data_page.py`:

```python
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
```

Replace the current `bottom = QHBoxLayout()` through action panel creation with:

```python
self.data_toolbar = DataToolbar()
layout.addWidget(self.data_toolbar)

self.workspace = DataWorkspace()
layout.addWidget(self.workspace, 1)

self.content_splitter = self.workspace.content_splitter
self.catalog_panel = self.workspace.catalog_panel
self.asset_table = self.workspace.asset_table
self.reader_panel = self.workspace.reader_panel
self.action_panel = self.workspace.action_panel

self.column_settings_btn = self.asset_table.column_settings_btn
self.column_settings_menu = self.asset_table.column_settings_menu
self.column_actions = self.asset_table.column_actions
self.reset_columns_action = self.asset_table.reset_columns_action
self.data_toolbar.set_column_settings_button(self.column_settings_btn)

self.import_btn = self.action_panel.import_btn
self.import_folder_btn = self.action_panel.import_folder_btn
self.rescan_btn = self.action_panel.rescan_btn
self.remove_btn = self.action_panel.remove_btn
```

Update signal wiring:

```python
self.data_toolbar.import_files_requested.connect(self.begin_import_files_from_dialog)
self.data_toolbar.import_folder_requested.connect(self.begin_import_folder_from_dialog)
self.data_toolbar.rescan_requested.connect(self.rescan_selected_asset)
self.data_toolbar.search_changed.connect(self.asset_table.set_search_text)
self.data_toolbar.catalog_toggled.connect(self.workspace.toggle_catalog_panel)
self.data_toolbar.reader_toggled.connect(
    lambda: self.workspace.set_reader_visible(not self.reader_panel.isVisible())
)
self.import_btn.clicked.connect(self.begin_import_files_from_dialog)
self.import_folder_btn.clicked.connect(self.begin_import_folder_from_dialog)
self.rescan_btn.clicked.connect(self.rescan_selected_asset)
```

Keep existing action panel button wiring for remove/open directory.

- [ ] **Step 7: Run focused tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py tests/test_data_toolbar.py tests/test_data_page.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add paleo_workbench/ui/pages/data_workspace.py paleo_workbench/ui/pages/data_page.py tests/test_data_workspace.py tests/test_data_page.py
git commit -m "feat: rebuild data page workspace layout"
```

---

### Task 4: Preview Widgets Shell And QPdfView Reader

**Files:**
- Create: `paleo_workbench/ui/pages/preview_widgets.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `tests/test_data_reader_panel.py`

**Interfaces:**
- Produces: `PdfPreviewWidget(QWidget)` with `load(path: str, revision: tuple[object, ...] | None = None) -> None`
- Produces: `ImagePreviewWidget(QWidget)` with `load(path: str, revision: tuple[object, ...] | None = None) -> None`
- Produces: `TextPreviewWidget(QTextEdit)` with `load_text(text: str) -> None`
- Produces: `TablePreviewWidget(QTableWidget)` with `load_table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None`
- Produces: `MessagePreviewWidget(QLabel)` with `set_message(text: str) -> None`
- `DataReaderPanel` keeps public test attributes: `text_preview`, `table_preview`, `image_label`, `pdf_widget`, `pdf_prev_btn`, `pdf_next_btn`, `pdf_page_label`.

- [ ] **Step 1: Write failing test for QPdfView-backed PDF widget**

Modify `tests/test_data_reader_panel.py`:

```python
def test_reader_panel_uses_pdf_preview_widget(qtbot, tmp_path: Path):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    panel.render(
        PreviewResult(
            mode="pdf",
            title="report.pdf",
            path=str(pdf_path),
            format="pdf",
            status="indexed",
            type_label="document",
        )
    )

    assert panel.current_mode == "pdf"
    assert panel.pdf_preview_widget is panel.pdf_widget
    assert hasattr(panel.pdf_preview_widget, "pdf_view")
```

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_uses_pdf_preview_widget -q`

Expected: FAIL because `pdf_preview_widget` does not exist.

- [ ] **Step 2: Implement preview widgets**

Create `paleo_workbench/ui/pages/preview_widgets.py` with:

```python
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
try:
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfView = None
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MessagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)

    def set_message(self, text: str) -> None:
        self.setText(text)


class TextPreviewWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

    def load_text(self, text: str) -> None:
        self.setPlainText(text)


class TablePreviewWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def load_table(self, headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None:
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(list(headers))
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.setItem(row_index, column_index, QTableWidgetItem(value))
        self.resizeColumnsToContents()


class ImagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._pixmap: QPixmap | None = None

    def load(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        if path != self._path or revision != self._revision or self._pixmap is None:
            self._path = path
            self._revision = revision
            self._pixmap = QPixmap(path)
        self.render_current()

    def render_current(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.setText("图片预览加载失败")
            return
        self.setPixmap(
            self._pixmap.scaled(
                max(self.width(), 240),
                max(self.height(), 180),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path:
            self.render_current()


class PdfPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = QPdfDocument(self)
        self.pdf_view = QPdfView(self) if QPdfView is not None else None
        self.fallback_image = QLabel()
        self.fallback_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page = 0
        self._path = ""
        self._revision: tuple[object, ...] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.pdf_view is not None:
            self.pdf_view.setDocument(self.document)
            layout.addWidget(self.pdf_view, 1)
        else:
            layout.addWidget(self.fallback_image, 1)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.previous_page)
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.page_label, 1)
        controls.addWidget(self.next_btn)
        layout.addLayout(controls)

    def load(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        if path != self._path or revision != self._revision:
            self._path = path
            self._revision = revision
            self._page = 0
            error = self.document.load(path)
            if error != QPdfDocument.Error.None_ or self.document.pageCount() <= 0:
                self.fallback_image.setText("PDF 预览加载失败")
                self.page_label.setText("0 / 0")
                self.prev_btn.setEnabled(False)
                self.next_btn.setEnabled(False)
                return
        self._render_page()

    def next_page(self) -> None:
        if self._page < self.document.pageCount() - 1:
            self._page += 1
            self._render_page()

    def previous_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _render_page(self) -> None:
        page_count = self.document.pageCount()
        if self.pdf_view is not None:
            self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
            navigator = self.pdf_view.pageNavigator()
            navigator.jump(self._page, navigator.currentLocation(), 0)
        else:
            image = self.document.render(
                self._page,
                QSize(max(self.width(), 420), max(self.height(), 560)),
            )
            self.fallback_image.setPixmap(QPixmap.fromImage(image))
        self.page_label.setText(f"{self._page + 1} / {page_count}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)
```

- [ ] **Step 3: Refactor `DataReaderPanel` to use widgets**

Modify `paleo_workbench/ui/pages/data_reader_panel.py`:

```python
from paleo_workbench.ui.pages.preview_widgets import (
    ImagePreviewWidget,
    MessagePreviewWidget,
    PdfPreviewWidget,
    TablePreviewWidget,
    TextPreviewWidget,
)
```

Replace direct `QTextEdit`, `QTableWidget`, `QLabel` PDF/image setup with:

```python
self.message_label = MessagePreviewWidget()
self.text_preview = TextPreviewWidget()
self.table_preview = TablePreviewWidget()
self.image_preview_widget = ImagePreviewWidget()
self.image_label = self.image_preview_widget
self.pdf_preview_widget = PdfPreviewWidget()
self.pdf_widget = self.pdf_preview_widget
self.pdf_prev_btn = self.pdf_preview_widget.prev_btn
self.pdf_next_btn = self.pdf_preview_widget.next_btn
self.pdf_page_label = self.pdf_preview_widget.page_label
```

Update render helpers:

```python
if result.mode == "message":
    self.message_label.set_message(result.message)
    self.stack.setCurrentWidget(self.message_label)
    return
if result.mode == "text":
    self.text_preview.load_text(result.text)
    self.stack.setCurrentWidget(self.text_preview)
    return
if result.mode == "table":
    self.table_preview.load_table(result.table_headers, result.table_rows)
    self.stack.setCurrentWidget(self.table_preview)
    return
if result.mode == "image":
    self.image_preview_widget.load(result.path, result.revision)
    self.stack.setCurrentWidget(self.image_preview_widget)
    return
if result.mode == "pdf":
    self.pdf_preview_widget.load(result.path, result.revision)
    self.stack.setCurrentWidget(self.pdf_preview_widget)
    return
```

Keep `next_pdf_page()` and `previous_pdf_page()` as wrappers:

```python
def next_pdf_page(self) -> None:
    self.pdf_preview_widget.next_page()

def previous_pdf_page(self) -> None:
    self.pdf_preview_widget.previous_page()
```

- [ ] **Step 4: Run reader tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q`

Expected: all reader tests pass after updating resize tests to assert widget reload behavior through public `image_preview_widget` and `pdf_preview_widget` attributes.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_data_reader_panel.py
git commit -m "feat: add library-backed preview widgets"
```

---

### Task 5: Library-Backed Table, Excel, LAS, And SEG-Y Preview Selection

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Modify: `tests/test_preview_provider.py`

**Interfaces:**
- Extends `PreviewMode` to include `"well_log"` and `"seismic"`.
- Extends `PreviewResult` with:
  - `sheets: tuple[str, ...] = field(default_factory=tuple)`
  - `summary_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)`
- Produces provider behavior:
  - `xlsx`/`xlsm` -> mode `"table"` with headers/rows from first sheet
  - LAS -> mode `"well_log"` with summary and curve rows
  - SEG-Y -> mode `"seismic"` with summary rows or message fallback

- [ ] **Step 1: Write failing provider tests**

Modify `tests/test_preview_provider.py`:

```python
from pathlib import Path

import pandas as pd

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider


def test_preview_provider_reads_excel_with_pandas(tmp_path: Path):
    path = tmp_path / "table.xlsx"
    pd.DataFrame({"well": ["A1"], "depth": [1200]}).to_excel(path, index=False)
    resource = ResourceItem(
        name="table.xlsx",
        path=str(path),
        type="tabular",
        format="xlsx",
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "table"
    assert result.table_headers == ("well", "depth")
    assert result.table_rows[0] == ("A1", "1200")
    assert result.sheets


def test_preview_provider_reads_las_summary_with_lasio(tmp_path: Path):
    path = tmp_path / "well.las"
    path.write_text(
        "~Version\nVERS. 2.0\n~Well\nWELL. A1\n~Curve\nDEPT.M\nGR.API\n~Ascii\n1 80\n",
        encoding="utf-8",
    )
    resource = ResourceItem(
        name="well.las",
        path=str(path),
        type="well_log",
        format="las",
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "well_log"
    assert ("井名", "A1") in result.summary_rows
    assert result.table_headers == ("曲线", "单位")
    assert ("GR", "API") in result.table_rows


def test_preview_provider_segy_degrades_to_summary_message(tmp_path: Path, monkeypatch):
    path = tmp_path / "cube.sgy"
    path.write_bytes(b"not a real segy")
    resource = ResourceItem(
        name="cube.sgy",
        path=str(path),
        type="seismic",
        format="sgy",
    )
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.preview_provider.segyio",
        None,
        raising=False,
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "seismic"
    assert result.message == "地震数据预览需要 SEG-Y 支持库或地震工作流打开"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_provider.py::test_preview_provider_reads_excel_with_pandas tests/test_preview_provider.py::test_preview_provider_reads_las_summary_with_lasio tests/test_preview_provider.py::test_preview_provider_segy_degrades_to_summary_message -q`

Expected: FAIL because Excel/LAS/SEG-Y modes are not implemented.

- [ ] **Step 3: Implement provider modes**

Modify `paleo_workbench/ui/pages/preview_provider.py`:

```python
import pandas as pd
import lasio
try:
    import segyio
except ImportError:
    segyio = None

EXCEL_FORMATS = {"xlsx", "xlsm", "xls"}
LAS_FORMATS = {"las"}
SEISMIC_FORMATS = {"sgy", "segy"}
PreviewMode = Literal["empty", "pdf", "image", "text", "table", "well_log", "seismic", "message"]
```

Extend `PreviewResult`:

```python
sheets: tuple[str, ...] = field(default_factory=tuple)
summary_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)
```

Add branches in `_build_preview()` before generic message:

```python
if fmt in EXCEL_FORMATS:
    return self._excel_preview(asset)
if fmt in LAS_FORMATS or asset.type == "well_log":
    return self._las_preview(asset)
if fmt in SEISMIC_FORMATS or asset.type == "seismic":
    return self._seismic_preview(asset)
```

Add helper methods:

```python
def _excel_preview(self, resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    workbook = pd.ExcelFile(path)
    frame = pd.read_excel(workbook, sheet_name=workbook.sheet_names[0], nrows=MAX_TABLE_ROWS)
    frame = frame.iloc[:, :MAX_TABLE_COLUMNS]
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=self._safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=tuple(str(column) for column in frame.columns),
        table_rows=tuple(tuple(str(value) for value in row) for row in frame.fillna("").to_numpy()),
        sheets=tuple(workbook.sheet_names),
        warning="表格预览已按行列上限截断" if len(frame) >= MAX_TABLE_ROWS else "",
    )

def _las_preview(self, resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    las = lasio.read(path)
    well_name = str(las.well.WELL.value) if "WELL" in las.well else ""
    curve_rows = tuple(
        (str(curve.mnemonic), str(curve.unit))
        for curve in las.curves
    )
    return PreviewResult(
        mode="well_log",
        title=resource.name,
        path=resource.path,
        revision=self._safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=(("井名", well_name), ("曲线数", str(len(curve_rows)))),
        table_headers=("曲线", "单位"),
        table_rows=curve_rows,
    )

def _seismic_preview(self, resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    if segyio is None:
        return PreviewResult(
            mode="seismic",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            message="地震数据预览需要 SEG-Y 支持库或地震工作流打开",
            summary_rows=(("文件", resource.name), ("格式", resource.format)),
        )
    try:
        with segyio.open(path, ignore_geometry=True) as handle:
            trace_count = len(handle.trace)
            sample_count = len(handle.samples)
    except Exception as exc:
        return PreviewResult(
            mode="seismic",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            message=f"SEG-Y 读取失败: {exc}",
            summary_rows=(("文件", resource.name), ("格式", resource.format)),
        )
    return PreviewResult(
        mode="seismic",
        title=resource.name,
        path=resource.path,
        revision=self._safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=(("道数", str(trace_count)), ("采样点", str(sample_count))),
    )
```

- [ ] **Step 4: Run provider tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_provider.py -q`

Expected: all provider tests pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_provider.py tests/test_preview_provider.py
git commit -m "feat: add library-backed preview provider modes"
```

---

### Task 6: Reader Rendering For Well Log And Seismic Summaries

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_widgets.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `tests/test_data_reader_panel.py`

**Interfaces:**
- Produces: `SummaryTablePreviewWidget(QWidget)` or equivalent for summary rows plus detail table.
- `DataReaderPanel.render()` handles `result.mode in {"well_log", "seismic"}`.
- Test-visible attributes: `well_log_preview`, `seismic_preview`.

- [ ] **Step 1: Write failing reader tests**

Modify `tests/test_data_reader_panel.py`:

```python
def test_reader_panel_renders_well_log_summary(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="well_log",
            title="well.las",
            summary_rows=(("井名", "A1"), ("曲线数", "2")),
            table_headers=("曲线", "单位"),
            table_rows=(("GR", "API"), ("RHOB", "G/C3")),
        )
    )

    assert panel.current_mode == "well_log"
    assert panel.well_log_preview.summary_table.item(0, 1).text() == "A1"
    assert panel.well_log_preview.detail_table.item(0, 0).text() == "GR"


def test_reader_panel_renders_seismic_summary_message(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="seismic",
            title="cube.sgy",
            message="地震数据预览需要 SEG-Y 支持库或地震工作流打开",
            summary_rows=(("文件", "cube.sgy"), ("格式", "sgy")),
        )
    )

    assert panel.current_mode == "seismic"
    assert "SEG-Y" in panel.seismic_preview.message_label.text()
```

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_renders_well_log_summary tests/test_data_reader_panel.py::test_reader_panel_renders_seismic_summary_message -q`

Expected: FAIL because these preview widgets do not exist.

- [ ] **Step 2: Implement summary preview widget**

Add to `paleo_workbench/ui/pages/preview_widgets.py`:

```python
class SummaryTablePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.summary_table = TablePreviewWidget()
        self.detail_table = TablePreviewWidget()
        layout.addWidget(self.summary_table)
        layout.addWidget(self.detail_table, 1)

    def load_summary(
        self,
        summary_rows: tuple[tuple[str, str], ...],
        detail_headers: tuple[str, ...],
        detail_rows: tuple[tuple[str, ...], ...],
        message: str = "",
    ) -> None:
        self.message_label.setText(message)
        self.summary_table.load_table(("属性", "值"), summary_rows)
        self.detail_table.load_table(detail_headers, detail_rows)
```

- [ ] **Step 3: Wire `DataReaderPanel` modes**

Modify imports:

```python
from paleo_workbench.ui.pages.preview_widgets import SummaryTablePreviewWidget
```

In `__init__`:

```python
self.well_log_preview = SummaryTablePreviewWidget()
self.stack.addWidget(self.well_log_preview)
self.seismic_preview = SummaryTablePreviewWidget()
self.stack.addWidget(self.seismic_preview)
```

In `render()`:

```python
if result.mode == "well_log":
    self.well_log_preview.load_summary(
        result.summary_rows,
        result.table_headers,
        result.table_rows,
        result.message,
    )
    self.stack.setCurrentWidget(self.well_log_preview)
    return

if result.mode == "seismic":
    self.seismic_preview.load_summary(
        result.summary_rows,
        result.table_headers,
        result.table_rows,
        result.message,
    )
    self.stack.setCurrentWidget(self.seismic_preview)
    return
```

- [ ] **Step 4: Run reader tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q`

Expected: all reader tests pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_data_reader_panel.py
git commit -m "feat: render well log and seismic reader summaries"
```

---

### Task 7: DataPage Integration Regression Pass

**Files:**
- Modify: `tests/test_data_page.py`
- Modify: `tests/test_ui_exports.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`

**Interfaces:**
- Exports `DataToolbar`, `DataWorkspace`, and `FloatingPanel` from `paleo_workbench.ui.pages`.
- Confirms toolbar, floating panels, async import, table, reader, and context signals all work together.

- [ ] **Step 1: Add integration regression tests**

Modify `tests/test_data_page.py`:

```python
def test_data_page_toolbar_search_filters_asset_table(qtbot, tmp_path: Path):
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    project.resources.extend(
        [
            ResourceItem(name="alpha.txt", path=str(first), type="document", format="txt"),
            ResourceItem(name="beta.txt", path=str(second), type="document", format="txt"),
        ]
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    page.data_toolbar.search_box.setText("beta")

    assert page.asset_table.table.rowCount() == 1
    assert page.asset_table.table.item(0, 0).text() == "beta.txt"


def test_data_page_floating_action_import_button_uses_background_import(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_files", lambda: [path])

    with qtbot.waitSignal(page.import_finished, timeout=1000):
        page.action_panel.import_btn.click()

    assert project.resources[0].name == "notes.txt"
```

- [ ] **Step 2: Run integration tests to verify RED or PASS**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_toolbar_search_filters_asset_table tests/test_data_page.py::test_data_page_floating_action_import_button_uses_background_import -q`

Expected: PASS with the Task 3 wiring complete.

- [ ] **Step 3: Update UI exports**

Modify `paleo_workbench/ui/pages/__init__.py`:

```python
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.floating_panel import FloatingPanel

__all__ = [
    # keep existing names
    "DataToolbar",
    "DataWorkspace",
    "FloatingPanel",
]
```

Preserve all existing exports in the file.

- [ ] **Step 4: Run page/export tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_workspace.py tests/test_data_toolbar.py tests/test_floating_panel.py tests/test_ui_exports.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_data_page.py tests/test_ui_exports.py paleo_workbench/ui/pages/__init__.py
git commit -m "test: cover redesigned data page integration"
```

---

### Task 8: Full Verification, App Launch, And Push

**Files:**
- No planned production changes.

**Interfaces:**
- Confirms all tasks integrate.

- [ ] **Step 1: Run focused data page suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_data_page.py \
  tests/test_data_workspace.py \
  tests/test_data_toolbar.py \
  tests/test_floating_panel.py \
  tests/test_data_reader_panel.py \
  tests/test_preview_provider.py \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest`

Expected: all tests pass.

- [ ] **Step 3: Launch the app**

Run:

```bash
PYTHONPATH=geo-viz-engine/packages/geoviz_common:geo-viz-engine/packages/geoviz_paleo_map:geo-viz-engine/packages/geoviz_plots:geo-viz-engine/packages/geoviz_seismic:geo-viz-engine/packages/geoviz_well_log:geo-viz-engine/packages/geoviz_cross_well python -m paleo_workbench.main
```

Expected: the application starts without import, Qt, or widget assembly errors. Stop the verification process after confirming startup.

- [ ] **Step 4: Check git status**

Run: `git status --short --branch`

Expected: branch is ahead by the implementation commits and has no uncommitted changes.

- [ ] **Step 5: Push**

Run: `git push`

Expected: push succeeds and `git status --short --branch` reports `main...origin/main`.
