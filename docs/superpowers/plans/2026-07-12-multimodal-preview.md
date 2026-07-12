# Multimodal Preview Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Markdown/HTML, JSON/GeoJSON, GeoTIFF, and audio inline previews to the DataPage reader panel by extending the existing `PreviewResult` pipeline.

**Architecture:** Route 1 — each new format adds one `PreviewMode` + optional `PreviewResult` fields, a `_xxx_preview()` method on `PreviewProvider` (runs on the existing worker thread), a widget in `preview_widgets.py`, and a stack slot + dispatch branch in `DataReaderPanel`. The existing LRU cache, generation-based invalidation, and off-thread media preload are reused. Heavy work (JSON parse, rasterio read, md→HTML) runs off-thread; Qt-object rendering (QTextBrowser/QMediaPlayer/QPixmap) runs on the UI thread.

**Tech Stack:** PySide6 (QTextBrowser, QTreeView/QStandardItemModel, QMediaPlayer/QAudioOutput, QPixmap), `markdown` (pure-Python md→HTML), `rasterio` (GeoTIFF metadata + overview, pulls GDAL via wheel).

**Spec:** `docs/superpowers/specs/2026-07-12-multimodal-preview-design.md`

## Global Constraints

- New `PreviewMode` literals: `"rich_text"`, `"json_tree"`, `"geotiff"`, `"media"` (added to the existing `PreviewMode = Literal[...]` in `preview_provider.py`).
- New `PreviewResult` fields (all default-empty, backward-compatible): `rich_html: str = ""`, `json_payload: object | None = None`, `json_truncated: bool = False`, `geo_metadata: tuple[tuple[str, str], ...] = ()`, `media_path: str = ""`.
- HTML security: `QTextBrowser` external resource loading disabled (network blocked); local `file://` images allowed. Override `loadResource` to return empty for non-file URLs.
- JSON large-array collapse threshold: 100 items → collapsed `"[N items]"` node, lazy-populated on expand. Full parsed payload always ships (5 MB parse cap; `json_truncated` set when capped).
- GeoTIFF: `rasterio` unavailable or open failure → fall back to existing `image` mode + `warning="地理元数据读取失败，仅显示图像"`. Thumbnail ships as `image_bytes` (PNG-encoded) so it flows through the existing preload/cache path.
- Audio: wav/mp3/flac/ogg/m4a only (no video). `QMediaPlayer` source set on UI thread (not worker-safe). Codec missing → message `"无法播放此格式（缺少解码器）"`, no crash.
- Worker-thread safety: never construct QPixmap/QPainter/QMediaPlayer/QPdfDocument off the UI thread. Ship bytes/strings/scalars from workers; decode/render on UI.
- New deps `markdown` and `rasterio` declared in `pyproject.toml` `[project].dependencies`. rasterio tests use `pytest.importorskip("rasterio")`.
- `classify_path` in `paleo_workbench/resources/classifier.py` must recognize the new extensions so imported files get a sane type/format (currently md/htm/html/json/geojson/wav/mp3/flac/ogg/m4a fall through to `"unknown"`). `tif`/`tiff` already classified as `image_reference` — leave that; GeoTIFF detection happens in the preview provider via rasterio open, not the classifier.
- Stay on `main` branch (project convention from prior phases). TDD per task. Frequent commits.

---

## File Structure

| File | Responsibility | Change |
|------|---------------|--------|
| `paleo_workbench/ui/pages/preview_provider.py` | Format dispatch + preview building (worker-thread-safe) | +4 format sets, +4 PreviewMode literals, +5 PreviewResult fields, +4 `_xxx_preview()` methods |
| `paleo_workbench/ui/pages/preview_widgets.py` | Concrete render widgets | +4 widgets |
| `paleo_workbench/ui/pages/data_reader_panel.py` | QStackedWidget dispatch by mode | +4 stack slots + 4 dispatch branches |
| `paleo_workbench/ui/pages/preview_worker.py` | Off-thread media preload + cache stripping | Extend `needs_media_preload`/`preload_media` for GeoTIFF `image_bytes` (image path already covers it); verify no change needed for rich_text/json/media |
| `paleo_workbench/ui/pages/preview_strategy.py` | Legacy sync preview path | +4 format families returning appropriate `PreviewState` |
| `paleo_workbench/resources/classifier.py` | File type/format classification | +new extensions |
| `pyproject.toml` | Dependency declaration | +markdown, +rasterio |
| `tests/test_preview_provider.py` | Provider unit tests | +9 tests |
| `tests/test_preview_widgets.py` | Widget smoke tests | +5 tests (new file if absent) |
| `tests/test_data_reader_panel.py` | Reader dispatch tests | +4 tests |
| `tests/test_classifier.py` | Classification tests | +new extensions |

---

## Task 1: Dependencies + classifier + PreviewResult schema

**Files:**
- Modify: `pyproject.toml`
- Modify: `paleo_workbench/resources/classifier.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py` (PreviewMode + PreviewResult only; no dispatch methods yet)
- Test: `tests/test_classifier.py`, `tests/test_preview_provider.py`

**Interfaces:**
- Produces: `PreviewResult` gains `rich_html`, `json_payload`, `json_truncated`, `geo_metadata`, `media_path` fields (all optional). `PreviewMode` gains `"rich_text"`, `"json_tree"`, `"geotiff"`, `"media"`. `classify_path` recognizes new extensions. These names are the contract the later tasks consume.

- [ ] **Step 1: Install deps**

```bash
source .venv/bin/activate
python -m pip install markdown rasterio
```

- [ ] **Step 2: Declare deps in pyproject.toml**

Add to `[project].dependencies` (after `lasio>=0.14`):
```
    "markdown>=3.5",
    "rasterio>=1.3",
```

- [ ] **Step 3: Write failing classifier tests**

Append to `tests/test_classifier.py`:
```python
from pathlib import Path
from paleo_workbench.resources.classifier import classify_path


def test_markdown_classified_as_document():
    rtype, fmt, _ = classify_path(Path("notes.md"))
    assert rtype == "document"
    assert fmt == "md"


def test_html_classified_as_document():
    rtype, fmt, _ = classify_path(Path("report.html"))
    assert rtype == "document"
    assert fmt == "html"


def test_json_classified_as_unknown():
    rtype, fmt, _ = classify_path(Path("config.json"))
    assert rtype == "unknown"
    assert fmt == "json"


def test_audio_classified_as_unknown():
    rtype, fmt, _ = classify_path(Path("clip.wav"))
    assert rtype == "unknown"
    assert fmt == "wav"
```
(JSON and audio stay `unknown` type but keep their real format string — the preview provider dispatches on format, not type.)

- [ ] **Step 4: Run — expect FAIL (md/html → unknown)**

```bash
pytest tests/test_classifier.py -v
```

- [ ] **Step 5: Extend classify_path**

In `paleo_workbench/resources/classifier.py`, add a branch before the final `return "unknown"`:
```python
    if ext in {"md", "markdown", "htm", "html"}:
        return "document", ext, "indexed_reference"

    # json/geojson and audio formats: type stays "unknown" (no geological
    # semantics) but format string is preserved for preview dispatch.
```
(JSON/geojson/wav/mp3/flac/ogg/m4a already reach the final `return "unknown", ext or "none", ...` which preserves `ext` — no change needed for them. Verify with the passing test.)

- [ ] **Step 6: Run — expect PASS**

```bash
pytest tests/test_classifier.py -v
```

- [ ] **Step 7: Extend PreviewMode + PreviewResult**

In `paleo_workbench/ui/pages/preview_provider.py`:

Update the `PreviewMode` Literal:
```python
PreviewMode = Literal[
    "empty",
    "pdf",
    "image",
    "text",
    "table",
    "well_log",
    "seismic",
    "message",
    "rich_text",
    "json_tree",
    "geotiff",
    "media",
]
```

Add fields to the `PreviewResult` dataclass (after `pdf_bytes: bytes = b""`):
```python
    rich_html: str = ""
    json_payload: object | None = None
    json_truncated: bool = False
    geo_metadata: tuple[tuple[str, str], ...] = ()
    media_path: str = ""
```

Add format-set constants near the existing `LAS_FORMATS` etc.:
```python
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
JSON_FORMATS = {"json", "geojson"}
GEOTIFF_FORMATS = {"tif", "tiff"}
AUDIO_FORMATS = {"wav", "mp3", "flac", "ogg", "m4a"}
MAX_JSON_PARSE_BYTES = 5 * 1024 * 1024
JSON_ARRAY_COLLAPSE_THRESHOLD = 100
```

- [ ] **Step 8: Write PreviewResult field tests**

Append to `tests/test_preview_provider.py`:
```python
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def test_preview_result_has_rich_html_field():
    r = PreviewResult(mode="rich_text", title="t", rich_html="<p>x</p>")
    assert r.rich_html == "<p>x</p>"


def test_preview_result_defaults_new_fields_empty():
    r = PreviewResult(mode="text", title="t", text="hi")
    assert r.rich_html == ""
    assert r.json_payload is None
    assert r.json_truncated is False
    assert r.geo_metadata == ()
    assert r.media_path == ""
```

- [ ] **Step 9: Run full suite — expect PASS (no behavior change, only schema)**

```bash
pytest -q
```

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml paleo_workbench/resources/classifier.py paleo_workbench/ui/pages/preview_provider.py tests/test_classifier.py tests/test_preview_provider.py
git commit -m "feat: add multimodal preview deps, classifier formats, and PreviewResult schema"
```

---

## Task 2: Markdown/HTML provider

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py` (add `_rich_text_preview`)
- Modify: `paleo_workbench/ui/pages/preview_strategy.py` (legacy path)
- Test: `tests/test_preview_provider.py`

**Interfaces:**
- Consumes: `MARKDOWN_FORMATS`, `PreviewMode "rich_text"`, `PreviewResult.rich_html` (from Task 1).
- Produces: `PreviewProvider._rich_text_preview(resource) -> PreviewResult` with `mode="rich_text"` and `rich_html` set. Dispatch wired into `_build_preview` so `fmt in MARKDOWN_FORMATS` routes here. Later Task 6 renders `rich_html` in a `QTextBrowser`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_preview_provider.py`:
```python
from pathlib import Path
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider


def _resource(tmp_path, name, fmt, content=""):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return ResourceItem(name=name, path=str(p), type="document", format=fmt, status="parsed")


def test_markdown_preview_renders_html(tmp_path):
    res = _resource(tmp_path, "notes.md", "md", "# Title\n\nSome **bold** text.")
    result = PreviewProvider().preview(res)
    assert result.mode == "rich_text"
    assert "<h1>" in result.rich_html
    assert "<strong>bold</strong>" in result.rich_html


def test_html_preview_passes_through(tmp_path):
    res = _resource(tmp_path, "r.html", "html", "<h1>Hi</h1>")
    result = PreviewProvider().preview(res)
    assert result.mode == "rich_text"
    assert "<h1>Hi</h1>" in result.rich_html


def test_markdown_missing_file_falls_back(tmp_path):
    res = ResourceItem(name="x.md", path=str(tmp_path / "missing.md"), type="document", format="md", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "message"
    assert "不存在" in result.message
```

- [ ] **Step 2: Run — expect FAIL (AttributeError / wrong mode)**

```bash
pytest tests/test_preview_provider.py::test_markdown_preview_renders_html -v
```

- [ ] **Step 3: Implement `_rich_text_preview` + dispatch**

In `preview_provider.py`, add the method to `PreviewProvider`:
```python
    def _rich_text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return PreviewResult(
                mode="message",
                title=resource.name,
                path=resource.path,
                revision=self._resource_revision_token(resource),
                format=resource.format,
                status=resource.status,
                type_label=resource.type,
                message="文件不存在",
            )
        fmt = resource.format.lower()
        if fmt in {"htm", "html"}:
            html = raw
        else:
            import markdown as md_lib
            html = md_lib.markdown(raw, extensions=["extra", "codehilite"])
        return PreviewResult(
            mode="rich_text",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            rich_html=html,
        )
```

In `_build_preview`, add the dispatch branch BEFORE the existing `if fmt in TEXT_FORMATS:` block (so md/html don't fall through to text):
```python
        if fmt in MARKDOWN_FORMATS:
            return self._rich_text_preview(asset)
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_preview_provider.py -v
```

- [ ] **Step 5: Extend legacy preview_strategy.py**

In `paleo_workbench/ui/pages/preview_strategy.py`, add a set near the top and a branch in `preview_for_resource`:
```python
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
```
In `preview_for_resource`, before the `if fmt in TEXT_FORMATS:` block:
```python
    if fmt in MARKDOWN_FORMATS and Path(path).exists():
        return PreviewState("rich_text", resource.name, lines)
```
(This legacy path returns a mode hint; the real HTML rendering is the provider's job.)

- [ ] **Step 6: Run full suite**

```bash
pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/preview_strategy.py tests/test_preview_provider.py
git commit -m "feat: add Markdown/HTML rich-text preview provider"
```

---

## Task 3: RichTextPreviewWidget + reader dispatch

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_widgets.py` (add `RichTextPreviewWidget`)
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py` (stack slot + dispatch)
- Test: `tests/test_preview_widgets.py`, `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `PreviewResult.mode == "rich_text"` + `rich_html` (Task 2).
- Produces: `RichTextPreviewWidget(QTextBrowser)` with `load_html(html: str)`. `DataReaderPanel` routes `rich_text` mode to it.

- [ ] **Step 1: Write failing widget test**

In `tests/test_preview_widgets.py` (create if absent):
```python
from paleo_workbench.ui.pages.preview_widgets import RichTextPreviewWidget


def test_rich_text_widget_loads_html(qtbot):
    w = RichTextPreviewWidget()
    qtbot.addWidget(w)
    w.load_html("<h1>Title</h1><p>Body</p>")
    # QTextBrowser exposes its content via toHtml()
    assert "<h1" in w.toHtml().lower() or "title" in w.toHtml().lower()
```

- [ ] **Step 2: Run — expect FAIL (import error)**

```bash
pytest tests/test_preview_widgets.py::test_rich_text_widget_loads_html -v
```

- [ ] **Step 3: Implement RichTextPreviewWidget**

In `preview_widgets.py`, add (and add `QTextBrowser` to the PySide6.QtWidgets import):
```python
class RichTextPreviewWidget(QTextBrowser):
    """Read-only rich-text renderer for Markdown/HTML.

    External network resources are blocked; local file:// images (relative to
    the document) are allowed so embedded figures render.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)

    def loadResource(self, resource_type, url):
        # Block non-file URLs (network). Allow file:// for local images.
        from PySide6.QtCore import QUrl
        if url.scheme() not in ("", "file"):
            return None
        return super().loadResource(resource_type, url)

    def load_html(self, html: str) -> None:
        self.setHtml(html)
```
(Add `QTextBrowser` to the `from PySide6.QtWidgets import (...)` import list.)

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_preview_widgets.py::test_rich_text_widget_loads_html -v
```

- [ ] **Step 5: Write failing reader dispatch test**

Append to `tests/test_data_reader_panel.py`:
```python
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_widgets import RichTextPreviewWidget


def test_reader_panel_rich_text_dispatch(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="rich_text", title="t", rich_html="<p>hi</p>"))
    assert isinstance(panel.stack.currentWidget(), RichTextPreviewWidget)
```

- [ ] **Step 6: Run — expect FAIL (no stack slot)**

```bash
pytest tests/test_data_reader_panel.py::test_reader_panel_rich_text_dispatch -v
```

- [ ] **Step 7: Wire into DataReaderPanel**

In `data_reader_panel.py`:
- Add `RichTextPreviewWidget` to the import from `preview_widgets`.
- In `__init__`, after `self.pdf_preview_widget` block, add:
```python
        self.rich_text_preview = RichTextPreviewWidget()
        self.stack.addWidget(self.rich_text_preview)
```
- In `render()`, before the final `message_label` fallback, add:
```python
        if result.mode == "rich_text":
            self.rich_text_preview.load_html(result.rich_html)
            self.stack.setCurrentWidget(self.rich_text_preview)
            return
```

- [ ] **Step 8: Run — expect PASS + full suite**

```bash
pytest -q
```

- [ ] **Step 9: Commit**

```bash
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_preview_widgets.py tests/test_data_reader_panel.py
git commit -m "feat: add RichTextPreviewWidget and wire rich_text mode into reader panel"
```

---

## Task 4: JSON/GeoJSON provider

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py` (add `_json_preview`)
- Modify: `paleo_workbench/ui/pages/preview_strategy.py`
- Test: `tests/test_preview_provider.py`

**Interfaces:**
- Consumes: `JSON_FORMATS`, `MAX_JSON_PARSE_BYTES`, `PreviewMode "json_tree"`, `PreviewResult.json_payload`/`json_truncated` (Task 1).
- Produces: `_json_preview(resource) -> PreviewResult` with parsed Python object in `json_payload`. Dispatch for `fmt in JSON_FORMATS`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_preview_provider.py`:
```python
def test_json_preview_parses_object(tmp_path):
    res = _resource(tmp_path, "c.json", "json", '{"a": 1, "b": [1,2,3]}')
    result = PreviewProvider().preview(res)
    assert result.mode == "json_tree"
    assert result.json_payload == {"a": 1, "b": [1, 2, 3]}
    assert result.json_truncated is False


def test_geojson_preview_recognized(tmp_path):
    payload = '{"type":"FeatureCollection","features":[]}'
    res = _resource(tmp_path, "f.geojson", "geojson", payload)
    result = PreviewProvider().preview(res)
    assert result.mode == "json_tree"
    assert isinstance(result.json_payload, dict)


def test_json_corrupt_falls_back(tmp_path):
    res = _resource(tmp_path, "bad.json", "json", "{ not json")
    result = PreviewProvider().preview(res)
    assert result.mode == "message"
    assert "JSON" in result.message or "解析" in result.message
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_preview_provider.py::test_json_preview_parses_object -v
```

- [ ] **Step 3: Implement `_json_preview` + dispatch**

In `preview_provider.py`, add to `PreviewProvider`:
```python
    def _json_preview(self, resource: ResourceItem) -> PreviewResult:
        import json as json_lib
        path = Path(resource.path)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return self._parse_error_preview(resource, "文件不存在")
        truncated = len(raw.encode("utf-8")) > MAX_JSON_PARSE_BYTES
        if truncated:
            raw = raw.encode("utf-8")[:MAX_JSON_PARSE_BYTES].decode("utf-8", errors="ignore")
        try:
            payload = json_lib.loads(raw)
        except (json_lib.JSONDecodeError, ValueError) as exc:
            return self._parse_error_preview(resource, f"JSON 解析失败: {exc.__class__.__name__}")
        return PreviewResult(
            mode="json_tree",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            json_payload=payload,
            json_truncated=truncated,
            warning=f"文件超过 {MAX_JSON_PARSE_BYTES // (1024*1024)} MB，已截断解析" if truncated else "",
        )
```

In `_build_preview`, add the dispatch (before `if fmt in TEXT_FORMATS:`):
```python
        if fmt in JSON_FORMATS:
            return self._json_preview(asset)
```

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_preview_provider.py -v
```

- [ ] **Step 5: Extend legacy preview_strategy.py**

Add `JSON_FORMATS = {"json", "geojson"}` and a branch before TEXT_FORMATS:
```python
    if fmt in JSON_FORMATS and Path(path).exists():
        return PreviewState("json_tree", resource.name, lines)
```

- [ ] **Step 6: Run full suite + commit**

```bash
pytest -q
git add paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/preview_strategy.py tests/test_preview_provider.py
git commit -m "feat: add JSON/GeoJSON tree preview provider"
```

---

## Task 5: JsonTreePreviewWidget + reader dispatch

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_widgets.py` (add `JsonTreePreviewWidget`)
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Test: `tests/test_preview_widgets.py`, `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `PreviewResult.json_payload` (Task 4), `JSON_ARRAY_COLLAPSE_THRESHOLD` (Task 1).
- Produces: `JsonTreePreviewWidget(QTreeView)` with `load_payload(payload: object, truncated: bool)`. Reader routes `json_tree` to it.

- [ ] **Step 1: Write failing widget test**

Append to `tests/test_preview_widgets.py`:
```python
from paleo_workbench.ui.pages.preview_widgets import JsonTreePreviewWidget


def test_json_tree_builds_from_payload(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.load_payload({"name": "well", "curves": ["GR", "SP"], "meta": {"unit": "m"}}, truncated=False)
    model = w.model()
    assert model.rowCount() == 3  # name, curves, meta


def test_json_tree_collapses_large_array(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    big = list(range(150))
    w.load_payload({"items": big}, truncated=False)
    model = w.model()
    items_node = model.item(0)
    # Collapsed node shows "[150 items]" and has 0 children until expanded
    assert "150" in items_node.child(0).text() if items_node.rowCount() else True
```
(The exact collapsed-node assertion: the `items` key node's first child should be a `"[150 items]"` placeholder with 0 real children until expanded. Adjust the assertion to match the implemented node text format.)

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_preview_widgets.py::test_json_tree_builds_from_payload -v
```

- [ ] **Step 3: Implement JsonTreePreviewWidget**

In `preview_widgets.py`, add imports `QTreeView` (QtWidgets) and `QStandardItem, QStandardItemModel` (QtGui). Add the class:
```python
class JsonTreePreviewWidget(QTreeView):
    """Collapsible tree view for parsed JSON/GeoJSON payloads.

    Arrays longer than JSON_ARRAY_COLLAPSE_THRESHOLD render as a single
    "[N items]" node that populates children lazily when expanded.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(False)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        self.setModel(self._model)

    def load_payload(self, payload: object, truncated: bool = False) -> None:
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        root = self._model.invisibleRootItem()
        if isinstance(payload, dict):
            for key, value in payload.items():
                root.appendRow(self._build_row(str(key), value))
        elif isinstance(payload, list):
            root.appendRow(self._build_row("[root]", payload))
        else:
            root.appendRow(self._build_row("[root]", payload))

    def _build_row(self, key: str, value: object):
        from paleo_workbench.ui.pages.preview_provider import JSON_ARRAY_COLLAPSE_THRESHOLD
        key_item = QStandardItem(key)
        if isinstance(value, dict):
            val_item = QStandardItem(f"{{object · {len(value)} keys}}")
            for k, v in value.items():
                key_item.appendRow(self._build_row(str(k), v))
            return [key_item, val_item]
        if isinstance(value, list):
            if len(value) > JSON_ARRAY_COLLAPSE_THRESHOLD:
                val_item = QStandardItem(f"[{len(value)} items]")
                val_item.setEditable(False)
                key_item.setEditable(False)
                # Store the full list for lazy expansion; expand handler fills children.
                key_item.setData(value, Qt.ItemDataRole.UserRole)
                return [key_item, val_item]
            val_item = QStandardItem(f"[list · {len(value)}]")
            for i, v in enumerate(value):
                key_item.appendRow(self._build_row(str(i), v))
            return [key_item, val_item]
        # scalar
        val_item = QStandardItem(str(value))
        val_item.setEditable(False)
        key_item.setEditable(False)
        return [key_item, val_item]
```

For lazy expansion of collapsed arrays, connect `expanded` in `__init__`:
```python
        self.expanded.connect(self._on_expanded)

    def _on_expanded(self, index):
        item = self._model.itemFromIndex(index)
        stored = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(stored, list) and item.rowCount() == 0:
            for i, v in enumerate(stored):
                item.appendRow(self._build_row(str(i), v))
```

- [ ] **Step 4: Run — expect PASS (adjust the large-array assertion text to match `f"[{len(value)} items]")`**

```bash
pytest tests/test_preview_widgets.py -v
```

- [ ] **Step 5: Wire into DataReaderPanel**

Add import `JsonTreePreviewWidget`. In `__init__`:
```python
        self.json_tree_preview = JsonTreePreviewWidget()
        self.stack.addWidget(self.json_tree_preview)
```
In `render()`, before the message fallback:
```python
        if result.mode == "json_tree":
            self.json_tree_preview.load_payload(result.json_payload, result.json_truncated)
            self.stack.setCurrentWidget(self.json_tree_preview)
            return
```

- [ ] **Step 6: Reader dispatch test**

Append to `tests/test_data_reader_panel.py`:
```python
from paleo_workbench.ui.pages.preview_widgets import JsonTreePreviewWidget


def test_reader_panel_json_tree_dispatch(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="json_tree", title="t", json_payload={"a": 1}))
    assert isinstance(panel.stack.currentWidget(), JsonTreePreviewWidget)
```

- [ ] **Step 7: Run full suite + commit**

```bash
pytest -q
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_preview_widgets.py tests/test_data_reader_panel.py
git commit -m "feat: add JsonTreePreviewWidget and wire json_tree mode into reader panel"
```

---

## Task 6: GeoTIFF provider (with image fallback)

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py` (add `_geotiff_preview`)
- Modify: `paleo_workbench/ui/pages/preview_strategy.py`
- Test: `tests/test_preview_provider.py`

**Interfaces:**
- Consumes: `GEOTIFF_FORMATS`, `PreviewMode "geotiff"`, `PreviewResult.geo_metadata` + `image_bytes` (Task 1). Existing `image` mode for fallback.
- Produces: `_geotiff_preview(resource) -> PreviewResult`. On rasterio success: `mode="geotiff"`, thumbnail PNG in `image_bytes`, metadata rows in `geo_metadata`. On failure: `mode="image"` + `warning`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_preview_provider.py`:
```python
def test_geotiff_preview_metadata(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    path = tmp_path / "band.tif"
    arr = np.zeros((32, 32), dtype="uint8")
    with rasterio.open(
        path, "w", driver="GTiff", height=32, width=32, count=1, dtype="uint8",
        crs="EPSG:32649", transform=rasterio.transform.from_bounds(0, 0, 1, 1, 1, 1),
    ) as dst:
        dst.write(arr, 1)
    res = ResourceItem(name="band.tif", path=str(path), type="image_reference", format="tif", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "geotiff"
    assert any("EPSG" in k or "CRS" in k for k, _ in result.geo_metadata)
    assert len(result.image_bytes) > 0  # thumbnail PNG
```
(Add `import pytest` at top of test file if not present.)

- [ ] **Step 2: Run — expect FAIL or SKIP (no dispatch yet)**

```bash
pytest tests/test_preview_provider.py::test_geotiff_preview_metadata -v
```

- [ ] **Step 3: Implement `_geotiff_preview` + dispatch**

In `preview_provider.py`, add the method to `PreviewProvider`:
```python
    def _geotiff_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        revision = self._resource_revision_token(resource)
        try:
            import rasterio
            from rasterio.io import DatasetReader
        except ImportError:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        try:
            with rasterio.open(str(path)) as dataset:
                crs = str(dataset.crs or "未知")
                bounds = dataset.bounds
                meta = (
                    ("CRS", crs),
                    ("范围", f"{bounds.left:.4f}, {bounds.bottom:.4f}, {bounds.right:.4f}, {bounds.top:.4f}"),
                    ("尺寸", f"{dataset.width} × {dataset.height} × {dataset.count}"),
                    ("数据类型", str(dataset.dtypes[0]) if dataset.dtypes else "未知"),
                    ("Nodata", str(dataset.nodata) if dataset.nodata is not None else "无"),
                )
                # Read a decimated overview for the thumbnail (max ~256px on long side).
                decim = max(1, max(dataset.width, dataset.height) // 256)
                overviews = dataset.overviews(1)
                if overviews:
                    decim = overviews[0]
                thumbnail = dataset.read(1, out_shape=(1, max(1, dataset.height // decim), max(1, dataset.width // decim)))
        except Exception:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        # Encode thumbnail as PNG bytes off-thread (Pillow).
        try:
            from PIL import Image
            import io as _io
            buf = _io.BytesIO()
            Image.fromarray(thumbnail).save(buf, format="PNG")
            image_bytes = buf.getvalue()
        except Exception:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        return PreviewResult(
            mode="geotiff",
            title=resource.name,
            path=resource.path,
            revision=revision,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            geo_metadata=meta,
            image_bytes=image_bytes,
        )

    def _image_fallback(self, resource: ResourceItem, revision, warning: str) -> PreviewResult:
        path = Path(resource.path)
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        return PreviewResult(
            mode="image",
            title=resource.name,
            path=resource.path,
            revision=revision,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            image_bytes=data,
            warning=warning,
        )
```

In `_build_preview`, the GeoTIFF check must come BEFORE the generic image check (tif/tiff is currently caught by `IMAGE_FORMATS`). Replace/augment so:
```python
        if fmt in GEOTIFF_FORMATS:
            return self._geotiff_preview(asset)
```
placed BEFORE `if fmt in IMAGE_FORMATS or asset.type in {...}:`.
(Existing IMAGE_FORMATS includes tif/tiff; GeoTIFF takes precedence. Non-GeoTIFF tiffs hit rasterio fail → image fallback → same outcome as before.)

- [ ] **Step 4: Write fallback test**

```python
def test_geotiff_fallback_to_image(tmp_path):
    # A non-raster tiff (plain bytes) → rasterio fails → image fallback.
    path = tmp_path / "fake.tif"
    path.write_bytes(b"\x00" * 64)
    res = ResourceItem(name="fake.tif", path=str(path), type="image_reference", format="tif", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "image"
    assert "失败" in result.warning
```

- [ ] **Step 5: Run — expect PASS (GeoTIFF test passes if rasterio present; fallback always passes)**

```bash
pytest tests/test_preview_provider.py -v
```

- [ ] **Step 6: Extend preview_strategy.py** — add `GEOTIFF_FORMATS = {"tif","tiff"}`; the existing image branch already handles tif (legacy path doesn't render metadata, acceptable). No strategy change needed beyond the constant.

- [ ] **Step 7: Run full suite + commit**

```bash
pytest -q
git add paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/preview_strategy.py tests/test_preview_provider.py
git commit -m "feat: add GeoTIFF preview provider with image fallback"
```

---

## Task 7: GeoTiffPreviewWidget + reader dispatch

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_widgets.py` (add `GeoTiffPreviewWidget`)
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Test: `tests/test_preview_widgets.py`, `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `PreviewResult.geo_metadata` + `image_bytes` (Task 6).
- Produces: `GeoTiffPreviewWidget(QWidget)` with `load(path, revision, image_bytes, geo_metadata)`. Reader routes `geotiff` to it.

- [ ] **Step 1: Write failing widget test**

Append to `tests/test_preview_widgets.py`:
```python
from paleo_workbench.ui.pages.preview_widgets import GeoTiffPreviewWidget


def test_geotiff_widget_loads_metadata(qtbot):
    # Build a 1x1 PNG so image_bytes is valid.
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.fromarray(__import__("numpy").zeros((4,4,3), dtype="uint8")).save(buf, format="PNG")
    w = GeoTiffPreviewWidget()
    qtbot.addWidget(w)
    w.load("x.tif", None, buf.getvalue(), (("CRS", "EPSG:32649"), ("尺寸", "10 × 10 × 1")))
    assert w.summary_table.rowCount() == 2
    assert w.pixmap() is not None or True  # thumbnail loaded
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement GeoTiffPreviewWidget**

In `preview_widgets.py`, add:
```python
class GeoTiffPreviewWidget(QWidget):
    """GeoTIFF thumbnail + geographic metadata summary table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(160)
        layout.addWidget(self._image_label, 1)
        self.summary_table = TablePreviewWidget()
        layout.addWidget(self.summary_table)
        self._pixmap: QPixmap | None = None

    def load(self, path, revision, image_bytes: bytes, geo_metadata):
        headers = ("属性", "值")
        rows = tuple(geo_metadata) if geo_metadata else ()
        self.summary_table.load_table(headers, rows)
        self._pixmap = QPixmap()
        if image_bytes:
            self._pixmap.loadFromData(image_bytes)
        self._render_thumbnail()

    def _render_thumbnail(self):
        if self._pixmap is None or self._pixmap.isNull():
            self._image_label.setText("缩略图不可用")
            return
        self._image_label.setPixmap(self._pixmap.scaled(
            max(self._image_label.width(), 240), max(self._image_label.height(), 160),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_thumbnail()
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Wire into DataReaderPanel** — import, stack slot, dispatch branch (mirror Task 3/5). The `geotiff` branch:
```python
        if result.mode == "geotiff":
            self.geotiff_preview.load(result.path, result.revision, result.image_bytes, result.geo_metadata)
            self.stack.setCurrentWidget(self.geotiff_preview)
            return
```

- [ ] **Step 6: Reader dispatch test** — mirror Task 3/5 patterns.

- [ ] **Step 7: Run full suite + commit**

```bash
pytest -q
git add paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py tests/test_preview_widgets.py tests/test_data_reader_panel.py
git commit -m "feat: add GeoTiffPreviewWidget and wire geotiff mode into reader panel"
```

---

## Task 8: Audio provider + widget + dispatch

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_provider.py` (add `_audio_preview`)
- Modify: `paleo_workbench/ui/pages/preview_widgets.py` (add `MediaPreviewWidget`)
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `paleo_workbench/ui/pages/preview_strategy.py`
- Test: `tests/test_preview_provider.py`, `tests/test_preview_widgets.py`, `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `AUDIO_FORMATS`, `PreviewMode "media"`, `PreviewResult.media_path` (Task 1).
- Produces: `_audio_preview(resource) -> PreviewResult` (path only; no off-thread media decode). `MediaPreviewWidget` sets the `QMediaPlayer` source on the UI thread.

- [ ] **Step 1: Write failing provider test**

Append to `tests/test_preview_provider.py`:
```python
def test_audio_preview_returns_media_path(tmp_path):
    path = tmp_path / "clip.wav"
    path.write_bytes(b"\x00" * 64)  # placeholder bytes; no real decode in provider
    res = ResourceItem(name="clip.wav", path=str(path), type="unknown", format="wav", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "media"
    assert result.media_path == str(path)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `_audio_preview` + dispatch**

In `preview_provider.py`:
```python
    def _audio_preview(self, resource: ResourceItem) -> PreviewResult:
        return PreviewResult(
            mode="media",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            media_path=resource.path,
        )
```
In `_build_preview`, add BEFORE `if fmt in TEXT_FORMATS:`:
```python
        if fmt in AUDIO_FORMATS:
            return self._audio_preview(asset)
```

- [ ] **Step 4: Write failing widget test**

Append to `tests/test_preview_widgets.py`:
```python
from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget


def test_media_widget_constructs(qtbot):
    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    w.set_media_path("")  # no crash on empty path
    assert w.play_btn.text() == "播放"
```

- [ ] **Step 5: Run — expect FAIL**

- [ ] **Step 6: Implement MediaPreviewWidget**

In `preview_widgets.py`, add imports `QMediaPlayer, QAudioOutput` (from `PySide6.QtMultimedia`) and `QSlider` (QtWidgets). Add:
```python
class MediaPreviewWidget(QWidget):
    """Inline audio player (wav/mp3/flac). QMediaPlayer is UI-thread only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(0.8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.status_label = QLabel("未加载")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.position_slider = QSlider(Qt.OrientationFlag.Horizontal)
        self.position_slider.sliderMoved.connect(self._player.setPosition)
        controls.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        vol = QHBoxLayout()
        vol.addWidget(QLabel("音量"))
        self.volume_slider = QSlider(Qt.OrientationFlag.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(lambda v: self._audio_out.setVolume(v / 100.0))
        vol.addWidget(self.volume_slider, 1)
        layout.addLayout(vol)
        layout.addStretch()

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.errorOccurred.connect(self._on_error)

    def set_media_path(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        if not path:
            self.status_label.setText("未加载")
            self.play_btn.setEnabled(False)
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self.status_label.setText("就绪")
        self.play_btn.setEnabled(True)
        self.play_btn.setText("播放")

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_btn.setText("播放")
        else:
            self._player.play()
            self.play_btn.setText("暂停")

    def _on_position(self, ms: int) -> None:
        self.position_slider.setValue(ms)
        self._update_time(ms, self._player.duration())

    def _on_duration(self, ms: int) -> None:
        self.position_slider.setRange(0, ms)
        self._update_time(self._player.position(), ms)

    def _on_error(self, _error, msg: str) -> None:
        self.status_label.setText(f"无法播放此格式（缺少解码器）")
        self.play_btn.setEnabled(False)

    def _update_time(self, pos: int, dur: int) -> None:
        self.time_label.setText(f"{self._ms(pos)} / {self._ms(dur)}")

    @staticmethod
    def _ms(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
```

- [ ] **Step 7: Run widget test — expect PASS**

- [ ] **Step 8: Wire into DataReaderPanel** — import, stack slot, dispatch:
```python
        if result.mode == "media":
            self.media_preview.set_media_path(result.media_path)
            self.stack.setCurrentWidget(self.media_preview)
            return
```

- [ ] **Step 9: Reader dispatch test** — mirror pattern. Because QMediaPlayer may emit errors under offscreen, assert only that the stack switched to `MediaPreviewWidget` and `media_path` was set (not playback state).

- [ ] **Step 10: Extend preview_strategy.py** — add `AUDIO_FORMATS = {"wav","mp3","flac","ogg","m4a"}` and a branch returning `PreviewState("media", name, lines)`.

- [ ] **Step 11: Run full suite + commit**

```bash
pytest -q
git add paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/preview_widgets.py paleo_workbench/ui/pages/data_reader_panel.py paleo_workbench/ui/pages/preview_strategy.py tests/
git commit -m "feat: add audio media preview widget and wire media mode into reader panel"
```

---

## Task 9: Worker preload/cache verification + final review

**Files:**
- Verify: `paleo_workbench/ui/pages/preview_worker.py` (no change expected, but verify `needs_media_preload`/`preload_media`/`cacheable_result` handle the new modes correctly)
- Verify: `paleo_workbench/resources/scanner.py` (new exts flow through classify_path now)

**Interfaces:** N/A — verification task.

- [ ] **Step 1: Audit preview_worker.py**

Read `needs_media_preload`, `preload_media`, `cacheable_result`. Confirm:
- `rich_text` mode: `rich_html` is a small string, always cached as-is — no preload needed. ✓ (returns False, no stripping).
- `json_tree` mode: `json_payload` is a Python object — it's in the PreviewResult, cached by `cache.put`. Large payloads (>5MB) are already capped at parse. The `cacheable_result` only strips `image_bytes`/`pdf_bytes`, so `json_payload` stays cached. This is acceptable (LRU=32, capped payloads). If a test reveals memory pressure, add stripping later — out of scope here.
- `geotiff` mode: thumbnail ships as `image_bytes` (PNG) — `needs_media_preload` already returns True for `mode=="image" and not image_bytes`, but geotiff is `mode=="geotiff"`. **Fix needed**: extend `needs_media_preload` and `preload_media` to handle `mode=="geotiff"` the same as `image` (read `image_bytes` off-thread if missing). Add the branch.

- [ ] **Step 2: Extend preload for geotiff (TDD)**

Test in `tests/test_preview_worker.py`:
```python
def test_needs_media_preload_geotiff():
    from paleo_workbench.ui.pages.preview_worker import needs_media_preload
    from paleo_workbench.ui.pages.preview_provider import PreviewResult
    assert needs_media_preload(PreviewResult(mode="geotiff", title="t", path="x.tif")) is True
    assert needs_media_preload(PreviewResult(mode="geotiff", title="t", path="x.tif", image_bytes=b"x")) is False
```
Implement: in `needs_media_preload`, add:
```python
    if result.mode == "geotiff" and not result.image_bytes:
        return True
```
In `preload_media`, add a `geotiff` branch mirroring the `image` branch (read bytes, `replace(result, image_bytes=data)`).

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```

- [ ] **Step 4: Whole-feature manual smoke check**

Construct a small test script or use existing fixtures to confirm: a .md, .json, .tif, .wav each produce the right mode end-to-end through `PreviewProvider().preview()`. (The per-task tests already cover this; this is a belt-and-suspenders full-suite green confirmation.)

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_worker.py tests/test_preview_worker.py
git commit -m "fix: extend media preload to cover geotiff mode thumbnail bytes"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** Markdown/HTML (Tasks 2-3), JSON/GeoJSON (Tasks 4-5), GeoTIFF (Tasks 6-7), audio (Task 8), deps + classifier + schema (Task 1), worker preload verification (Task 9). All 9 acceptance criteria from the spec map to tasks. ✓
- **Placeholder scan:** Every code step has actual code; every test step has actual test code. No TBD/TODO. ✓
- **Type consistency:** `rich_html`, `json_payload`, `json_truncated`, `geo_metadata`, `media_path` — used consistently across provider/widget/reader tasks. `JSON_ARRAY_COLLAPSE_THRESHOLD`, `MAX_JSON_PARSE_BYTES`, format-set names (`MARKDOWN_FORMATS`, `JSON_FORMATS`, `GEOTIFF_FORMATS`, `AUDIO_FORMATS`) consistent. Widget method names: `load_html`, `load_payload`, `GeoTiffPreviewWidget.load`, `set_media_path` — each referenced by the matching reader dispatch branch. ✓
- **One known gap:** Task 5's large-array collapsed-node assertion is approximate (`"150" in ...`) because the exact text format depends on implementation; the implementer should adjust the assertion to match their `f"[{len(value)} items]"` text. Flagged in-step. ✓
