# Data Preview Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Data page preview area so common image and text-like project files render safe inline previews while heavy professional formats remain metadata-first.

**Architecture:** Keep preview selection in `paleo_workbench/ui/pages/preview_strategy.py` as a pure helper layer. Keep file decoding bounded and synchronous for this phase because only small prefixes are read. Render visual/text preview widgets in `DataDetailPanel`, while `DataPage` continues to orchestrate selection and project state.

**Tech Stack:** Python 3.12, PySide6 6.6+, Pydantic v2, pytest, pytest-qt.

## Global Constraints

- Preview must stay lightweight, predictable, and safe.
- The strategy layer does not decode image bytes; decoding remains in the UI panel.
- Preview reads only a bounded prefix of text-like files.
- Default limits: maximum bytes `8192`, maximum lines `20`.
- Binary-looking content falls back to metadata-only with a warning.
- PDF renders a first-page thumbnail when possible; LAS, SGY, SEGY, XLSX, XLS, PPT, PPTX, WLP, and DFB are not deep-loaded by default.
- Unsupported files return `mode == "metadata"` and warning `"暂不支持预览"`.
- Missing files return metadata plus warning `"文件不存在"`.
- Preview failures must not remove the item from the project or crash the Data page.
- Use `QT_QPA_PLATFORM=offscreen pytest ...` for PySide tests in this environment.

---

## File Structure

Modify:

```text
paleo_workbench/ui/pages/preview_strategy.py       # bounded text preview, missing-file handling, professional summary modes
paleo_workbench/ui/pages/data_detail_panel.py      # image thumbnail and text/table snippet rendering
tests/test_preview_strategy.py                     # strategy unit coverage for formats and error states
tests/test_data_detail_panel.py                    # widget coverage for thumbnail/text/warning rendering
tests/test_data_page.py                            # integration selection coverage if needed
task_plan.md                                      # final progress update
progress.md                                       # final progress update
findings.md                                       # implementation notes
```

No new runtime dependency should be added for this phase.

---

### Task 1: Preview Strategy Format Coverage

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_strategy.py`
- Test: `tests/test_preview_strategy.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`, existing `PreviewState(mode, title, lines, image_path=None, warning="")`
- Produces: bounded preview modes from `preview_for_resource(resource: ResourceItem, base_path: Path | None = None) -> PreviewState`

- [ ] **Step 1: Write failing tests for text, CSV, missing file, and professional summaries**

Append to `tests/test_preview_strategy.py`:

```python
def test_preview_strategy_reads_bounded_text_lines(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("\n".join(f"line {index}" for index in range(25)), encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=text.as_posix(), type="document", format="txt")

    state = preview_for_resource(resource)

    assert state.mode == "text"
    assert "line 0" in state.lines
    assert "line 19" in state.lines
    assert "line 20" not in state.lines
    assert "仅显示前 20 行" in state.warning


def test_preview_strategy_csv_uses_table_mode(tmp_path: Path):
    csv = tmp_path / "table.csv"
    csv.write_text("well,depth\nA1,100\n", encoding="utf-8")
    resource = ResourceItem(name="table.csv", path=csv.as_posix(), type="spreadsheet", format="csv")

    state = preview_for_resource(resource)

    assert state.mode == "table"
    assert any("well,depth" in line for line in state.lines)
    assert any("A1,100" in line for line in state.lines)


def test_preview_strategy_missing_file_warns(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    resource = ResourceItem(name="missing.txt", path=missing.as_posix(), type="document", format="txt")

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "文件不存在" in state.warning


def test_preview_strategy_professional_formats_stay_summary_only(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-heavy")
    resource = ResourceItem(name="report.pdf", path=pdf.as_posix(), type="document", format="pdf")

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "安全摘要预览" in state.warning
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py::test_preview_strategy_reads_bounded_text_lines tests/test_preview_strategy.py::test_preview_strategy_csv_uses_table_mode tests/test_preview_strategy.py::test_preview_strategy_missing_file_warns tests/test_preview_strategy.py::test_preview_strategy_professional_formats_stay_summary_only -q
```

Expected: FAIL because current strategy returns metadata for TXT, does not read CSV lines, does not check missing files, and uses the old document warning.

- [ ] **Step 3: Implement bounded text preview helpers**

In `paleo_workbench/ui/pages/preview_strategy.py`, add constants and helpers:

```python
MAX_PREVIEW_BYTES = 8192
MAX_PREVIEW_LINES = 20
TEXT_FORMATS = {"txt", "xml"}
TABLE_FORMATS = {"csv", "dat"}
PROFESSIONAL_FORMATS = {"las", "sgy", "segy", "xlsx", "xls", "pdf", "ppt", "pptx", "wlp", "dfb"}


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data


def _read_preview_lines(path: str, max_bytes: int = MAX_PREVIEW_BYTES, max_lines: int = MAX_PREVIEW_LINES) -> tuple[list[str], str]:
    try:
        data = Path(path).read_bytes()[:max_bytes]
    except OSError as exc:
        return [], f"{Path(path).name}: {exc.__class__.__name__}"
    if _looks_binary(data):
        return [], "内容看起来是二进制，使用安全摘要预览"
    text = data.decode("utf-8", errors="replace")
    raw_lines = text.splitlines()
    lines = raw_lines[:max_lines]
    warning = "仅显示前 20 行" if len(raw_lines) > max_lines else ""
    return lines, warning
```

Then update `preview_for_resource()`:

```python
    exists = Path(path).exists()
    if not exists and resource.format.lower() in TEXT_FORMATS | TABLE_FORMATS | PROFESSIONAL_FORMATS:
        return PreviewState("metadata", resource.name, lines, warning="文件不存在")

    fmt = resource.format.lower()
    if fmt in TEXT_FORMATS:
        preview_lines, warning = _read_preview_lines(path)
        if preview_lines:
            return PreviewState("text", resource.name, lines + preview_lines, warning=warning)
        return PreviewState("metadata", resource.name, lines, warning=warning or "暂不支持预览")

    if fmt in TABLE_FORMATS:
        preview_lines, warning = _read_preview_lines(path)
        if preview_lines:
            return PreviewState("table", resource.name, lines + preview_lines, warning=warning)
        return PreviewState("metadata", resource.name, lines, warning=warning or "暂不支持预览")

    if fmt in PROFESSIONAL_FORMATS and resource.type not in {"well_log", "seismic"}:
        return PreviewState("metadata", resource.name, lines, warning="此格式暂使用安全摘要预览")
```

Keep existing image, well_log, seismic, table-type, artifact, and unknown behavior intact.

- [ ] **Step 4: Run strategy tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/preview_strategy.py tests/test_preview_strategy.py
git commit -m "feat: add bounded data preview strategy"
```

---

### Task 2: Data Detail Panel Image And Snippet Rendering

**Files:**
- Modify: `paleo_workbench/ui/pages/data_detail_panel.py`
- Test: `tests/test_data_detail_panel.py`

**Interfaces:**
- Consumes: `PreviewState` returned by `preview_for_resource()`
- Produces: `DataDetailPanel.update_asset(asset: object | None) -> None` rendering thumbnails, snippets, and warnings

- [ ] **Step 1: Write failing widget tests**

Append to `tests/test_data_detail_panel.py`:

```python
from PySide6.QtGui import QImage


def test_detail_panel_renders_image_thumbnail(qtbot, tmp_path):
    image_path = tmp_path / "map.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    image.save(image_path.as_posix())
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(name="map.png", path=image_path.as_posix(), type="image_reference", format="png")

    panel.update_asset(resource)

    pixmap_labels = [
        label for label in panel.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert pixmap_labels


def test_detail_panel_invalid_image_shows_warning(qtbot, tmp_path):
    image_path = tmp_path / "bad.png"
    image_path.write_text("not an image", encoding="utf-8")
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(name="bad.png", path=image_path.as_posix(), type="image_reference", format="png")

    panel.update_asset(resource)

    assert "图片预览加载失败" in "\n".join(_labels(panel))


def test_detail_panel_renders_text_preview_lines(qtbot, tmp_path):
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(name="notes.txt", path=text_path.as_posix(), type="document", format="txt")

    panel.update_asset(resource)

    texts = "\n".join(_labels(panel))
    assert "alpha" in texts
    assert "beta" in texts
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_detail_panel.py::test_detail_panel_renders_image_thumbnail tests/test_data_detail_panel.py::test_detail_panel_invalid_image_shows_warning tests/test_data_detail_panel.py::test_detail_panel_renders_text_preview_lines -q
```

Expected: FAIL because current panel only renders image paths as text and does not create pixmap labels or invalid-image warnings.

- [ ] **Step 3: Implement thumbnail and snippet rendering**

In `paleo_workbench/ui/pages/data_detail_panel.py` import:

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
```

Add helper methods:

```python
    def _add_preview_line(self, text: str) -> None:
        item = QLabel(text)
        item.setWordWrap(True)
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        item.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
            " font-family: Consolas, 'Courier New', monospace;"
        )
        self.preview_layout.addWidget(item)

    def _add_image_preview(self, path: str) -> bool:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        label = QLabel()
        label.setObjectName("DataPreviewImage")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(
            pixmap.scaled(
                220,
                160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_layout.addWidget(label)
        return True
```

Update `_update_resource()` preview rendering:

```python
        if state.mode == "image" and state.image_path:
            if not self._add_image_preview(state.image_path):
                self._add_warning("图片预览加载失败")
            self._add_muted(self.preview_layout, f"图片: {state.image_path}")
        elif state.mode in {"text", "table"}:
            for line in state.lines:
                self._add_preview_line(line)
        else:
            for line in state.lines:
                self._add_muted(self.preview_layout, line)
        if state.warning:
            self._add_warning(state.warning)
```

Do not add nested cards.

- [ ] **Step 4: Run detail panel tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_detail_panel.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_detail_panel.py tests/test_data_detail_panel.py
git commit -m "feat: render data preview details"
```

---

### Task 3: Data Page Selection Integration

**Files:**
- Modify: `tests/test_data_page.py`
- Modify only if needed: `paleo_workbench/ui/pages/data_page.py`
- Modify only if needed: `paleo_workbench/ui/pages/data_asset_table.py`

**Interfaces:**
- Consumes: `DataAssetTable.selected_asset_changed`, `DataDetailPanel.update_asset()`
- Produces: proof that imported selectable image/text resources render through the DataPage detail panel

- [ ] **Step 1: Write failing or characterization integration tests**

Append to `tests/test_data_page.py`:

```python
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel


def test_data_page_selection_renders_imported_text_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([text_path])

    page.asset_table.table.selectRow(0)

    labels = "\n".join(label.text() for label in page.detail_panel.findChildren(QLabel))
    assert "alpha" in labels
    assert "beta" in labels


def test_data_page_selection_renders_imported_image_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    image_path = tmp_path / "map.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    image.save(image_path.as_posix())
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([image_path])

    page.asset_table.table.selectRow(0)

    pixmap_labels = [
        label for label in page.detail_panel.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert pixmap_labels
```

- [ ] **Step 2: Run tests to verify red or characterization**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_selection_renders_imported_text_preview tests/test_data_page.py::test_data_page_selection_renders_imported_image_preview -q
```

Expected:
- PASS if Task 2 and existing selection wiring already satisfy this.
- FAIL if `QTableWidget.selectRow()` does not emit the expected selection signal or if imported TXT/PNG classification needs extension.

- [ ] **Step 3: Fix only gaps exposed by tests**

If TXT import is classified as unknown and preview still works by format, no classifier change is needed.

If selection does not emit reliably, update `DataAssetTable._render()` to keep row asset data and ensure `_emit_selection()` handles selected rows:

```python
    def _emit_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.selected_asset_changed.emit(None)
            return
        row = rows[0].row()
        item = self.table.item(row, 0)
        asset = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self.selected_asset_changed.emit(asset)
```

- [ ] **Step 4: Run DataPage tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/pages/data_asset_table.py tests/test_data_page.py
git commit -m "test: cover data preview selection flow"
```

---

### Task 4: Final Verification And Tracking Docs

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `findings.md`

**Interfaces:**
- Consumes: completed preview strategy and detail panel behavior
- Produces: documented completion and final verification evidence

- [ ] **Step 1: Run focused preview suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py tests/test_data_detail_panel.py tests/test_data_page.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full verification**

Run:

```bash
git diff --check
QT_QPA_PLATFORM=offscreen pytest -q
python -m compileall -q paleo_workbench
```

Expected:
- `git diff --check`: no output, exit 0.
- pytest: all tests PASS.
- compileall: no output, exit 0.

- [ ] **Step 3: Update tracking docs**

Update `task_plan.md`:

```markdown
Data Preview Formats enhancement complete; root suite count updated to the latest passing count.
```

Update `progress.md` with:

```markdown
### Data Preview Formats Enhancement — COMPLETE ✅

- Added bounded TXT/XML/CSV/DAT preview.
- Added inline image thumbnails in DataDetailPanel.
- Added PDF first-page thumbnail preview; kept LAS/SEGY/PPT/Excel safe summary-only by default.
- Verified focused preview suite and full root test suite.
```

Update `findings.md` with:

```markdown
### Data Preview Format Notes

- Text preview reads at most 8192 bytes and 20 lines.
- Image decoding is UI-only via QPixmap; strategy returns only the image path.
- Heavy professional formats remain metadata-first until dedicated parsers/viewers are introduced.
```

- [ ] **Step 4: Commit**

Run:

```bash
git add task_plan.md progress.md findings.md
git commit -m "docs: record data preview formats completion"
```

---

## Final Verification

After all tasks:

```bash
git diff --check
QT_QPA_PLATFORM=offscreen pytest -q
python -m compileall -q paleo_workbench
git status --short --branch
```

Expected:

- No whitespace errors.
- Full test suite passes.
- Compileall passes.
- Worktree clean except intentional unpushed commits.
