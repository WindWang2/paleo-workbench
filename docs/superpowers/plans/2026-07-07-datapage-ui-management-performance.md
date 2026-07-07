# Data Page UI Management Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the data page into a UI-faithful, performant project data management surface with a real multi-format reader.

**Architecture:** Split file preview preparation from Qt rendering. `PreviewProvider` produces bounded, cached preview states; `DataReaderPanel` renders those states; `DataPage` coordinates selection, management actions, and shell/sidebar context updates.

**Tech Stack:** Python, PySide6, pytest, existing `ProjectDocument`, `ResourceItem`, `ExportArtifact`, `DataPage`, `AppShell`, and `TextSidebar`.

## Global Constraints

- The data page must preserve the existing workbench shell.
- The lower data page area must remain horizontally resizable with a splitter.
- Text previews read at most 256 KiB.
- Table previews read at most 200 rows and 40 columns.
- PDF previews render only the visible page.
- Data table filtering and search must not read file contents.
- Removing an asset removes it from the project document only; it must not delete files from disk.
- Full project lifecycle actions in the top toolbar remain out of scope.
- Keep changes scoped to data page UI, preview, management, and app-shell context synchronization.

---

## File Structure

- Create `paleo_workbench/ui/pages/preview_provider.py`
  - Bounded, cacheable preview data preparation with no Qt widgets.
- Create `paleo_workbench/ui/pages/data_reader_panel.py`
  - Dedicated Qt reader panel for PDF, image, text, table, message, and empty states.
- Modify `paleo_workbench/ui/pages/data_page.py`
  - Replace metadata-heavy `DataDetailPanel` with `DataReaderPanel`.
  - Add selection/context signals and action state updates.
- Modify `paleo_workbench/ui/app_shell.py`
  - Connect data page context updates to `TextSidebar`.
  - Expose current data context when data page state changes.
- Modify `paleo_workbench/ui/sidebar.py`
  - Expand data context rendering with issue count, selected asset, type/format, and reader mode.
- Modify `paleo_workbench/ui/pages/action_panel.py`
  - Add selection-aware action state text and button enablement helper.
- Modify `paleo_workbench/ui/pages/data_asset_table.py`
  - Preserve lightweight table filtering and expose visible asset count.
- Deprecate direct reader use in `paleo_workbench/ui/pages/data_detail_panel.py`
  - Keep the file temporarily to avoid breaking imports in existing tests until migration is complete.
- Add `tests/test_preview_provider.py`
  - Unit tests for bounded text/table/missing/cache preview behavior.
- Add `tests/test_data_reader_panel.py`
  - Widget tests for reader modes.
- Modify `tests/test_data_page.py`
  - Integration tests for selection, action updates, import/remove/rescan, and splitter layout.
- Modify `tests/test_app_shell.py`
  - Tests for data context sidebar synchronization.
- Modify `tests/test_sidebar.py`
  - Tests for expanded data context rendering.

---

### Task 1: Preview Provider

**Files:**
- Create: `paleo_workbench/ui/pages/preview_provider.py`
- Test: `tests/test_preview_provider.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`
- Produces:
  - `PreviewResult`
  - `PreviewProvider.preview(asset: ResourceItem | ExportArtifact | None) -> PreviewResult`
  - `PreviewProvider.clear() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_preview_provider.py` with:

```python
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    PreviewProvider,
)


def test_preview_provider_empty_state():
    result = PreviewProvider().preview(None)

    assert result.mode == "empty"
    assert result.title == "请选择数据项"


def test_preview_provider_reads_bounded_text(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_text("a" * (MAX_TEXT_PREVIEW_BYTES + 100), encoding="utf-8")
    resource = ResourceItem(name="large.txt", path=str(path), type="document", format="txt")

    result = PreviewProvider().preview(resource)

    assert result.mode == "text"
    assert len(result.text) <= MAX_TEXT_PREVIEW_BYTES + 32
    assert result.truncated is True
    assert "仅显示" in result.warning


def test_preview_provider_reads_bounded_csv_table(tmp_path: Path):
    path = tmp_path / "table.csv"
    header = ",".join(f"c{i}" for i in range(MAX_TABLE_COLUMNS + 3))
    rows = [
        ",".join(str(column) for column in range(MAX_TABLE_COLUMNS + 3))
        for _ in range(MAX_TABLE_ROWS + 5)
    ]
    path.write_text("\n".join([header, *rows]), encoding="utf-8")
    resource = ResourceItem(name="table.csv", path=str(path), type="tabular", format="csv")

    result = PreviewProvider().preview(resource)

    assert result.mode == "table"
    assert len(result.table_rows) == MAX_TABLE_ROWS
    assert all(len(row) == MAX_TABLE_COLUMNS for row in result.table_rows)
    assert result.truncated is True


def test_preview_provider_missing_file_message(tmp_path: Path):
    resource = ResourceItem(
        name="missing.txt",
        path=str(tmp_path / "missing.txt"),
        type="document",
        format="txt",
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "message"
    assert result.status == "missing"
    assert "文件不存在" in result.message


def test_preview_provider_reuses_cached_result_for_unchanged_file(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("first", encoding="utf-8")
    resource = ResourceItem(name="sample.txt", path=str(path), type="document", format="txt")
    provider = PreviewProvider()

    first = provider.preview(resource)
    second = provider.preview(resource)

    assert first is second


def test_preview_provider_export_artifact_message(tmp_path: Path):
    artifact = ExportArtifact(linked_id="map_1", format="png", output_path=str(tmp_path / "map.png"))

    result = PreviewProvider().preview(artifact)

    assert result.mode == "message"
    assert result.title == "map.png"
    assert "成果文件" in result.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_preview_provider.py -v
```

Expected: FAIL because `paleo_workbench.ui.pages.preview_provider` does not exist.

- [ ] **Step 3: Implement the provider**

Create `paleo_workbench/ui/pages/preview_provider.py`:

```python
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from paleo_workbench.project.models import ExportArtifact, ResourceItem

MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 40

PreviewMode = Literal["empty", "pdf", "image", "text", "table", "message"]

TEXT_FORMATS = {"txt", "text", "log", "dat", "json", "xml"}
TABLE_FORMATS = {"csv", "tsv"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
PDF_FORMATS = {"pdf"}


@dataclass(frozen=True)
class PreviewResult:
    mode: PreviewMode
    title: str
    path: str = ""
    format: str = ""
    status: str = ""
    type_label: str = ""
    message: str = ""
    warning: str = ""
    text: str = ""
    table_headers: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    truncated: bool = False


class PreviewProvider:
    def __init__(self) -> None:
        self._cache: dict[tuple, PreviewResult] = {}

    def clear(self) -> None:
        self._cache.clear()

    def preview(self, asset: ResourceItem | ExportArtifact | None) -> PreviewResult:
        if asset is None:
            return PreviewResult(mode="empty", title="请选择数据项", message="从列表中选择一个数据、成果或文件")
        key = self._cache_key(asset)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._build_preview(asset)
        self._cache[key] = result
        return result

    def _cache_key(self, asset: ResourceItem | ExportArtifact) -> tuple:
        if isinstance(asset, ExportArtifact):
            path = Path(asset.output_path)
            stat = self._safe_stat(path)
            return ("artifact", asset.id, asset.output_path, stat)
        path = Path(asset.path)
        stat = self._safe_stat(path)
        return ("resource", asset.id, asset.path, asset.checksum, stat)

    def _safe_stat(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _build_preview(self, asset: ResourceItem | ExportArtifact) -> PreviewResult:
        if isinstance(asset, ExportArtifact):
            return self._artifact_preview(asset)
        path = Path(asset.path)
        fmt = asset.format.lower()
        title = asset.name
        if not path.exists():
            return PreviewResult(
                mode="message",
                title=title,
                path=asset.path,
                format=asset.format,
                status="missing",
                type_label=asset.type,
                message="文件不存在",
            )
        if fmt in PDF_FORMATS:
            return PreviewResult(mode="pdf", title=title, path=asset.path, format=asset.format, status=asset.status, type_label=asset.type)
        if fmt in IMAGE_FORMATS or asset.type in {"image_reference", "reference_map"}:
            return PreviewResult(mode="image", title=title, path=asset.path, format=asset.format, status=asset.status, type_label=asset.type)
        if fmt in TABLE_FORMATS:
            return self._table_preview(asset, delimiter="\t" if fmt == "tsv" else ",")
        if fmt in TEXT_FORMATS:
            return self._text_preview(asset)
        return PreviewResult(
            mode="message",
            title=title,
            path=asset.path,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            message="此格式暂不支持内置阅读，可使用打开目录定位文件",
        )

    def _artifact_preview(self, artifact: ExportArtifact) -> PreviewResult:
        title = Path(artifact.output_path).name or artifact.output_path
        return PreviewResult(
            mode="message",
            title=title,
            path=artifact.output_path,
            format=artifact.format,
            status="generated",
            type_label="成果",
            message=f"成果文件 · 关联对象 {artifact.linked_id}",
        )

    def _text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        data = path.read_bytes()
        truncated = len(data) > MAX_TEXT_PREVIEW_BYTES
        preview_bytes = data[:MAX_TEXT_PREVIEW_BYTES]
        text = preview_bytes.decode("utf-8", errors="replace")
        warning = f"仅显示前 {MAX_TEXT_PREVIEW_BYTES // 1024} KiB" if truncated else ""
        return PreviewResult(
            mode="text",
            title=resource.name,
            path=resource.path,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            text=text,
            warning=warning,
            truncated=truncated,
        )

    def _table_preview(self, resource: ResourceItem, delimiter: str) -> PreviewResult:
        path = Path(resource.path)
        rows: list[list[str]] = []
        truncated = False
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for index, row in enumerate(reader):
                if index >= MAX_TABLE_ROWS:
                    truncated = True
                    break
                trimmed = row[:MAX_TABLE_COLUMNS]
                if len(row) > MAX_TABLE_COLUMNS:
                    truncated = True
                rows.append(trimmed)
        headers = rows[0] if rows else []
        body = rows[1:] if rows else []
        warning = "表格预览已按行列上限截断" if truncated else ""
        return PreviewResult(
            mode="table",
            title=resource.name,
            path=resource.path,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            table_headers=headers,
            table_rows=body,
            warning=warning,
            truncated=truncated,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_preview_provider.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_provider.py tests/test_preview_provider.py
git commit -m "feat: add bounded data preview provider"
```

---

### Task 2: Data Reader Panel

**Files:**
- Create: `paleo_workbench/ui/pages/data_reader_panel.py`
- Test: `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `PreviewProvider.preview(...) -> PreviewResult`
- Produces:
  - `DataReaderPanel.update_asset(asset: ResourceItem | ExportArtifact | None) -> None`
  - `DataReaderPanel.current_mode: str`
  - `DataReaderPanel.reader_mode_changed = Signal(str)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_data_reader_panel.py`:

```python
from pathlib import Path

from PySide6.QtWidgets import QLabel, QTableWidget

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel


def test_reader_panel_empty_state():
    panel = DataReaderPanel()

    assert panel.current_mode == "empty"
    assert panel.title_label.text() == "请选择数据项"


def test_reader_panel_renders_text_resource(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("line 1\nline 2", encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    panel = DataReaderPanel()

    panel.update_asset(resource)

    assert panel.current_mode == "text"
    assert "line 1" in panel.text_preview.toPlainText()


def test_reader_panel_renders_table_resource(tmp_path: Path):
    path = tmp_path / "table.csv"
    path.write_text("a,b\n1,2", encoding="utf-8")
    resource = ResourceItem(name="table.csv", path=str(path), type="tabular", format="csv")
    panel = DataReaderPanel()

    panel.update_asset(resource)

    assert panel.current_mode == "table"
    table = panel.table_preview
    assert isinstance(table, QTableWidget)
    assert table.rowCount() == 1
    assert table.columnCount() == 2


def test_reader_panel_renders_missing_message(tmp_path: Path):
    resource = ResourceItem(name="missing.txt", path=str(tmp_path / "missing.txt"), type="document", format="txt")
    panel = DataReaderPanel()

    panel.update_asset(resource)

    assert panel.current_mode == "message"
    labels = panel.findChildren(QLabel)
    assert any("文件不存在" in label.text() for label in labels)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_data_reader_panel.py -v
```

Expected: FAIL because `data_reader_panel.py` does not exist.

- [ ] **Step 3: Implement the reader panel**

Create `paleo_workbench/ui/pages/data_reader_panel.py` with:

```python
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class DataReaderPanel(QFrame):
    reader_mode_changed = Signal(str)

    def __init__(self, provider: PreviewProvider | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataReaderPanel")
        self.setMinimumWidth(320)
        self.provider = provider or PreviewProvider()
        self.current_mode = "empty"
        self._pdf_document: QPdfDocument | None = None
        self._pdf_page = 0
        self._pdf_path = ""
        self.setStyleSheet(
            f"QFrame#DataReaderPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("请选择数据项")
        self.title_label.setObjectName("DataReaderTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("DataReaderMeta")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.meta_label)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.empty_label = self._message_widget("从列表中选择一个数据、成果或文件")
        self.stack.addWidget(self.empty_label)

        self.message_label = self._message_widget("")
        self.stack.addWidget(self.message_label)

        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_preview.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.stack.addWidget(self.text_preview)

        self.table_preview = QTableWidget()
        self.table_preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stack.addWidget(self.table_preview)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.image_label)

        self.pdf_widget = QWidget()
        pdf_layout = QVBoxLayout(self.pdf_widget)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        self.pdf_image = QLabel()
        self.pdf_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pdf_layout.addWidget(self.pdf_image, 1)
        pdf_controls = QHBoxLayout()
        self.pdf_prev_btn = QPushButton("上一页")
        self.pdf_prev_btn.clicked.connect(self.previous_pdf_page)
        self.pdf_page_label = QLabel("0 / 0")
        self.pdf_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_next_btn = QPushButton("下一页")
        self.pdf_next_btn.clicked.connect(self.next_pdf_page)
        pdf_controls.addWidget(self.pdf_prev_btn)
        pdf_controls.addWidget(self.pdf_page_label, 1)
        pdf_controls.addWidget(self.pdf_next_btn)
        pdf_layout.addLayout(pdf_controls)
        self.stack.addWidget(self.pdf_widget)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 12px;")
        layout.addWidget(self.warning_label)

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        self.render(self.provider.preview(asset))

    def render(self, result: PreviewResult) -> None:
        self.current_mode = result.mode
        self.reader_mode_changed.emit(result.mode)
        self.title_label.setText(result.title)
        self.meta_label.setText(self._meta_text(result))
        self.warning_label.setText(result.warning)
        if result.mode == "empty":
            self.stack.setCurrentWidget(self.empty_label)
            return
        if result.mode == "message":
            self.message_label.setText(result.message)
            self.stack.setCurrentWidget(self.message_label)
            return
        if result.mode == "text":
            self.text_preview.setPlainText(result.text)
            self.stack.setCurrentWidget(self.text_preview)
            return
        if result.mode == "table":
            self._render_table(result)
            self.stack.setCurrentWidget(self.table_preview)
            return
        if result.mode == "image":
            self._render_image(result.path)
            self.stack.setCurrentWidget(self.image_label)
            return
        if result.mode == "pdf":
            self._load_pdf(result.path)
            self.stack.setCurrentWidget(self.pdf_widget)
            return

    def next_pdf_page(self) -> None:
        if self._pdf_document is not None and self._pdf_page < self._pdf_document.pageCount() - 1:
            self._pdf_page += 1
            self._render_pdf_page()

    def previous_pdf_page(self) -> None:
        if self._pdf_document is not None and self._pdf_page > 0:
            self._pdf_page -= 1
            self._render_pdf_page()

    def _message_widget(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        return label

    def _meta_text(self, result: PreviewResult) -> str:
        parts = [part for part in [result.type_label, result.format, result.status, result.path] if part]
        return " · ".join(parts)

    def _render_table(self, result: PreviewResult) -> None:
        self.table_preview.setColumnCount(len(result.table_headers))
        self.table_preview.setHorizontalHeaderLabels(result.table_headers)
        self.table_preview.setRowCount(len(result.table_rows))
        for row_index, row in enumerate(result.table_rows):
            for column_index, value in enumerate(row):
                self.table_preview.setItem(row_index, column_index, QTableWidgetItem(value))
        self.table_preview.resizeColumnsToContents()

    def _render_image(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.setText("图片预览加载失败")
            return
        self.image_label.setPixmap(
            pixmap.scaled(
                max(self.width() - 48, 240),
                max(self.height() - 160, 180),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _load_pdf(self, path: str) -> None:
        if self._pdf_document is None:
            self._pdf_document = QPdfDocument(self)
        self._pdf_path = path
        self._pdf_page = 0
        error = self._pdf_document.load(path)
        if error != QPdfDocument.Error.None_ or self._pdf_document.pageCount() <= 0:
            self.pdf_image.setText("PDF 预览加载失败")
            self.pdf_page_label.setText("0 / 0")
            self.pdf_prev_btn.setEnabled(False)
            self.pdf_next_btn.setEnabled(False)
            return
        self._render_pdf_page()

    def _render_pdf_page(self) -> None:
        if self._pdf_document is None:
            return
        image = self._pdf_document.render(self._pdf_page, QSize(max(self.width() - 48, 420), max(self.height() - 160, 560)))
        if image.isNull():
            self.pdf_image.setText("PDF 页面渲染失败")
        else:
            self.pdf_image.setPixmap(QPixmap.fromImage(image))
        page_count = self._pdf_document.pageCount()
        self.pdf_page_label.setText(f"{self._pdf_page + 1} / {page_count}")
        self.pdf_prev_btn.setEnabled(self._pdf_page > 0)
        self.pdf_next_btn.setEnabled(self._pdf_page < page_count - 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_data_reader_panel.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/data_reader_panel.py tests/test_data_reader_panel.py
git commit -m "feat: add data reader panel"
```

---

### Task 3: Data Page Layout and Management Integration

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/ui/pages/action_panel.py`
- Modify: `paleo_workbench/ui/pages/data_asset_table.py`
- Test: `tests/test_data_page.py`
- Test: `tests/test_data_asset_table.py`

**Interfaces:**
- Consumes: `DataReaderPanel.update_asset(...)`
- Produces:
  - `DataPage.data_context_changed = Signal(dict)`
  - `DataPage.current_reader_mode() -> str`
  - `ActionPanel.update_selection_state(has_resource: bool, has_asset: bool, reader_mode: str) -> None`
  - `DataAssetTable.visible_asset_count() -> int`

- [ ] **Step 1: Write failing integration tests**

Append these tests to `tests/test_data_page.py`:

```python
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel


def test_data_page_uses_reader_panel():
    page = DataPage(project=ProjectDocument.new("Demo"))

    assert isinstance(page.reader_panel, DataReaderPanel)
    assert page.content_splitter.indexOf(page.reader_panel) >= 0


def test_data_page_selection_updates_reader_and_context_signal(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    project.resources.append(resource)
    page = DataPage(project=project)
    received = []
    page.data_context_changed.connect(received.append)

    page._set_selected_asset(resource)

    assert page.reader_panel.current_mode == "text"
    assert received[-1]["selected_name"] == "notes.txt"
    assert received[-1]["reader_mode"] == "text"


def test_data_page_remove_refreshes_reader_and_action_state(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    project.resources.append(resource)
    page = DataPage(project=project)
    page._set_selected_asset(resource)

    assert page.remove_selected_asset() is True

    assert project.resources == []
    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False
```

Append this test to `tests/test_data_asset_table.py`:

```python
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable


def test_data_asset_table_visible_asset_count_after_search():
    table = DataAssetTable()
    resources = [
        ResourceItem(name="alpha.txt", path="/tmp/alpha.txt", type="document", format="txt"),
        ResourceItem(name="beta.txt", path="/tmp/beta.txt", type="document", format="txt"),
    ]

    table.update_assets(resources, [])
    table.set_search_text("alpha")

    assert table.visible_asset_count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_data_page.py tests/test_data_asset_table.py -v
```

Expected: FAIL because `DataPage.reader_panel`, `data_context_changed`, `ActionPanel.update_selection_state`, and `visible_asset_count` do not exist.

- [ ] **Step 3: Implement table count and action state helpers**

Modify `paleo_workbench/ui/pages/data_asset_table.py`:

```python
    def visible_asset_count(self) -> int:
        return len(self._visible_assets)
```

Modify `paleo_workbench/ui/pages/action_panel.py`:

```python
    def update_selection_state(
        self,
        has_resource: bool,
        has_asset: bool,
        reader_mode: str,
    ) -> None:
        self.rescan_btn.setEnabled(has_resource)
        self.remove_btn.setEnabled(has_resource)
        self.open_folder_btn.setEnabled(has_resource)
        if has_asset:
            self.status_label.setText(f"阅读器: {reader_mode}")
        else:
            self.status_label.setText("等待操作")
```

- [ ] **Step 4: Replace data detail panel with reader panel**

Modify `paleo_workbench/ui/pages/data_page.py` imports:

```python
from PySide6.QtCore import Qt, Signal
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
```

Remove the `DataDetailPanel` import and replace the detail panel construction:

```python
        self.reader_panel = DataReaderPanel()
        self.content_splitter.addWidget(self.reader_panel)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 2)
        self.content_splitter.setSizes([180, 560, 520])
```

Add the signal near the class declaration:

```python
class DataPage(QWidget):
    data_context_changed = Signal(dict)
```

Update `_set_selected_asset`:

```python
    def _set_selected_asset(self, asset: object | None) -> None:
        self._selected_asset = asset
        self.reader_panel.update_asset(asset)
        has_resource = isinstance(asset, ResourceItem)
        self.action_panel.update_selection_state(
            has_resource=has_resource,
            has_asset=asset is not None,
            reader_mode=self.reader_panel.current_mode,
        )
        self._emit_data_context()
```

Replace `self.detail_panel.update_asset(...)` calls with `self.reader_panel.update_asset(...)`.

Add:

```python
    def current_reader_mode(self) -> str:
        return self.reader_panel.current_mode

    def _emit_data_context(self) -> None:
        issue_count = sum(
            1
            for resource in self.project.resources
            if resource.status in {"missing", "warning", "failed", "error"}
        )
        selected = self._selected_asset
        selected_name = "未选择"
        selected_type = ""
        selected_format = ""
        if isinstance(selected, ResourceItem):
            selected_name = selected.name
            selected_type = selected.type
            selected_format = selected.format
        elif isinstance(selected, ExportArtifact):
            selected_name = Path(selected.output_path).name
            selected_type = "成果"
            selected_format = selected.format
        self.data_context_changed.emit(
            {
                "resource_count": len(self.project.resources),
                "artifact_count": len(self.project.export_artifacts),
                "issue_count": issue_count,
                "selected_name": selected_name,
                "selected_type": selected_type,
                "selected_format": selected_format,
                "reader_mode": self.reader_panel.current_mode,
            }
        )
```

Call `_emit_data_context()` at the end of `update_state`.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
pytest tests/test_data_page.py tests/test_data_asset_table.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/pages/action_panel.py paleo_workbench/ui/pages/data_asset_table.py tests/test_data_page.py tests/test_data_asset_table.py
git commit -m "feat: integrate data reader with data page"
```

---

### Task 4: App Shell Sidebar Synchronization

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/ui/sidebar.py`
- Test: `tests/test_app_shell.py`
- Test: `tests/test_sidebar.py`

**Interfaces:**
- Consumes: `DataPage.data_context_changed`
- Produces:
  - `AppShell.update_data_context(context: dict) -> None`
  - `TextSidebar.update_data_context(resource_count: int, artifact_count: int, issue_count: int = 0, selected_name: str = "未选择", selected_type: str = "", selected_format: str = "", reader_mode: str = "empty") -> None`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sidebar.py`:

```python
from paleo_workbench.ui.sidebar import TextSidebar


def test_sidebar_renders_expanded_data_context():
    bar = TextSidebar()

    bar.update_data_context(
        resource_count=3,
        artifact_count=2,
        issue_count=1,
        selected_name="demo.pdf",
        selected_type="document",
        selected_format="pdf",
        reader_mode="pdf",
    )

    text = " ".join(label.text() for label in bar._content_labels)
    assert "资源 3" in text
    assert "成果 2" in text
    assert "异常 1" in text
    assert "当前选择: demo.pdf" in text
    assert "格式: document / pdf" in text
    assert "阅读器: pdf" in text
```

Append to `tests/test_app_shell.py`:

```python
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.app_shell import AppShell


def test_app_shell_syncs_data_page_context_to_sidebar(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    project.resources.append(resource)
    shell = AppShell(project=project)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert "当前选择: notes.txt" in text
    assert "阅读器: text" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_sidebar.py tests/test_app_shell.py -v
```

Expected: FAIL because the expanded sidebar signature and app-shell connection do not exist.

- [ ] **Step 3: Expand sidebar data context**

Modify `paleo_workbench/ui/sidebar.py` method signature and body:

```python
    def update_data_context(
        self,
        resource_count: int,
        artifact_count: int,
        issue_count: int = 0,
        selected_name: str = "未选择",
        selected_type: str = "",
        selected_format: str = "",
        reader_mode: str = "empty",
    ) -> None:
        self.context_label.setText("数据")
        format_text = f"{selected_type} / {selected_format}" if selected_type or selected_format else "未选择"
        self._render_lines(
            [
                ("数据概览", True),
                (f"资源 {resource_count}", False),
                (f"成果 {artifact_count}", False),
                (f"异常 {issue_count}", False),
                ("当前选择", True),
                (f"当前选择: {selected_name}", False),
                (f"格式: {format_text}", False),
                (f"阅读器: {reader_mode}", False),
                ("管理", True),
                ("导入文件 / 导入目录", False),
                ("重新扫描 / 移出项目", False),
                ("打开目录", False),
            ]
        )
```

- [ ] **Step 4: Wire app shell to data context changes**

Modify `paleo_workbench/ui/app_shell.py` after `DataPage(project=self.project)` creation so the page is stored before adding:

```python
        self.data_page = DataPage(project=self.project)
        self.data_page.data_context_changed.connect(self.update_data_context)
        self.page_stack.addWidget(self.data_page)
```

Replace `self.page_stack.addWidget(DataPage(project=self.project))` with the snippet above.

Add method:

```python
    def update_data_context(self, context: dict) -> None:
        self.sidebar.update_data_context(
            resource_count=context.get("resource_count", 0),
            artifact_count=context.get("artifact_count", 0),
            issue_count=context.get("issue_count", 0),
            selected_name=context.get("selected_name", "未选择"),
            selected_type=context.get("selected_type", ""),
            selected_format=context.get("selected_format", ""),
            reader_mode=context.get("reader_mode", "empty"),
        )
```

Update `update_data_page` to call sidebar with the expanded signature:

```python
        self.sidebar.update_data_context(
            resource_count=len(resources),
            artifact_count=len(artifacts or []),
            issue_count=sum(
                1
                for resource in resources
                if resource.status in {"missing", "warning", "failed", "error"}
            ),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
pytest tests/test_sidebar.py tests/test_app_shell.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/app_shell.py paleo_workbench/ui/sidebar.py tests/test_app_shell.py tests/test_sidebar.py
git commit -m "feat: sync data context sidebar"
```

---

### Task 5: UI Verification and Regression Pass

**Files:**
- Modify only files needed to fix issues found by the verification commands.

**Interfaces:**
- Consumes all previous tasks.
- Produces a verified data page implementation.

- [ ] **Step 1: Run the focused test suite**

Run:

```bash
pytest tests/test_preview_provider.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_data_asset_table.py tests/test_sidebar.py tests/test_app_shell.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
pytest
```

Expected: PASS.

- [ ] **Step 3: Run the application**

Run:

```bash
PYTHONPATH=geo-viz-engine/packages/geoviz_common:geo-viz-engine/packages/geoviz_paleo_map:geo-viz-engine/packages/geoviz_plots:geo-viz-engine/packages/geoviz_seismic:geo-viz-engine/packages/geoviz_well_log:geo-viz-engine/packages/geoviz_cross_well python -m paleo_workbench.main
```

Expected: the workbench starts and the data page shows the restored structure:

- left data context has real counts and selection state
- center catalog and table manage project assets
- right reader is large and resizable
- far-right action panel remains visible
- selecting PDF/text/table/image updates reader mode and action state

- [ ] **Step 4: Fix verification issues**

For any test or runtime failure, change only the files directly related to that failure and rerun the failing command until it passes.

- [ ] **Step 5: Commit verification fixes**

If fixes were needed:

```bash
git add paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/data_reader_panel.py paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/pages/action_panel.py paleo_workbench/ui/pages/data_asset_table.py paleo_workbench/ui/app_shell.py paleo_workbench/ui/sidebar.py tests/test_preview_provider.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_data_asset_table.py tests/test_sidebar.py tests/test_app_shell.py
git commit -m "fix: verify data page reader workflow"
```

If no fixes were needed, leave the tree unchanged.

---

## Self-Review

- Spec coverage: UI restoration, large reader, bounded preview, caching, management actions, category/search behavior, and sidebar synchronization are covered by Tasks 1 through 5.
- Scope: project lifecycle, file deletion, full-file editing, SEG-Y volume visualization, PDF text extraction, and asynchronous parsing remain out of scope.
- Type consistency: `PreviewProvider.preview`, `PreviewResult`, `DataReaderPanel.update_asset`, `DataPage.data_context_changed`, `ActionPanel.update_selection_state`, and `TextSidebar.update_data_context` are defined before use by later tasks.
- Testing: each task has a failing-test step, implementation step, pass step, and commit step.
