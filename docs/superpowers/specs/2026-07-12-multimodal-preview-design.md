# Multimodal Preview Formats Design (Phase B)

> **Date:** 2026-07-12
> **Status:** Approved (pending spec review)
> **Scope:** Add 4 new preview formats to the DataPage reader panel: Markdown/HTML, JSON/GeoJSON, GeoTIFF, audio.
> **Predecessor:** Data Page V2 (Phase 13) — current preview pipeline.
> **Decomposition:** This is sub-project B of the data page overhaul (B multimodal → A DEVONthink 3-pane → C performance). A and C are separate specs.

## Goal

Extend the existing preview pipeline with 4 new format families so the reader panel can render richer document/data/media types inline, without launching external tools. The four formats:

1. **Markdown / HTML** — rendered rich text (currently falls through to plain text).
2. **JSON / GeoJSON** — collapsible tree view (currently plain text).
3. **GeoTIFF** — thumbnail + geographic metadata (currently plain image, no CRS/bounds).
4. **Audio** — inline player for wav/mp3/flac (currently unsupported).

## Non-Goals

- Video playback (codec/dependency complexity; audio only for this phase).
- Editing any format.
- Network fetching of remote resources referenced in HTML.
- Synchronized scrolling between tree and source for JSON.
- A/V transcoding or waveform rendering.
- The DEVONthink 3-pane layout restructure (sub-project A) and performance work (sub-project C).

## Current Pipeline (confirmed)

```
PreviewProvider._build_preview(asset)
    → dispatches by asset.format → returns PreviewResult(mode=..., <fields>)
    → runs on a worker thread (PreviewRequestController)
    → result delivered to UI thread
DataReaderPanel.render(result)
    → switches QStackedWidget to the widget for result.mode
preview_widgets.py
    → concrete widget (Text/Table/Image/PDF/...)
```

To add a format: (1) add a format set + `PreviewMode` literal + `_xxx_preview()` method to `preview_provider.py`; (2) add a widget to `preview_widgets.py`; (3) add a stack slot + dispatch branch to `data_reader_panel.py`; (4) optionally extend `preview_strategy.py` (the legacy/sync strategy used by tests and `DataPage` fallback).

The existing `PreviewCache` (LRU, 32 entries, keyed by stat+type+format) and generation-based invalidation (`PreviewRequestController`) apply automatically to new modes — no cache changes needed.

## Design Decision

**Route 1: reuse the existing PreviewResult pipeline.** Each new format adds one `PreviewMode` and optional fields on `PreviewResult`. Heavy work (JSON parse, rasterio read) runs on the worker thread; rendering runs on the UI thread. This reuses the proven cache/thread/invalidation infrastructure and matches the existing test pattern (construct ResourceItem → `preview()` → assert mode/fields).

The alternative (a second lazy-load pipeline for heavy formats) was rejected — it doubles the cache/test/threading surface for no gain.

## New Format Specs

### 1. Markdown / HTML — `rich_text` mode

**Trigger:** `fmt in {"md", "markdown", "htm", "html"}`.

**Widget:** `RichTextPreviewWidget(QTextBrowser)` — read-only.
- Markdown: parse to HTML using Python's `markdown` library (new dep, pure-Python, lightweight), then `setHtml()`.
- HTML: `setHtml()` directly.
- **Security:** disable external resource loading — override `QTextBrowser.loadResource` to return empty for non-`file://` URLs (blocks network); local `file://` image references are resolved relative to the document's directory and allowed (for embedded figures in reports). No JavaScript (QTextBrowser doesn't execute it by design).
- Worker-thread work: read file bytes + markdown→HTML conversion (pure CPU, safe off-thread). UI thread: `setHtml()` only.

**PreviewResult fields used:** `title`, `path`, `revision`, `format`, `status`, `type_label` + new field `rich_html: str = ""` (the rendered HTML string).

### 2. JSON / GeoJSON — `json_tree` mode

**Trigger:** `fmt in {"json", "geojson"}`.

**Widget:** `JsonTreePreviewWidget(QTreeView + QStandardItemModel)`.
- Parse JSON on the worker thread → build a serializable node tree → ship to UI → populate `QStandardItemModel`.
- **Large array collapsing:** arrays longer than a threshold (default 100 items) render as a single collapsed node `"[N items]"` that expands on click to reveal children (the QStandardItemModel populates expanded children lazily, so the visible tree isn't fully built upfront). The full parsed payload (`json_payload`) is always shipped from the worker thread (subject to the 5 MB parse cap); only the tree-model rendering is lazy.
- Objects: nested key nodes; scalars: leaf nodes with value + type hint.
- GeoJSON: recognized by `fmt == "geojson"` or top-level `"type"` in `{"FeatureCollection","Feature",...}` → root node labeled with geometry type summary (e.g. `"FeatureCollection · 42 features"`).
- Size guard: if file > 5 MB, parse only the first 5 MB and show a truncation warning (avoid OOM on huge NDJSON-ish files).

**PreviewResult fields used:** `title`, `path`, `revision`, `format`, `status`, `type_label`, `warning` + new field `json_payload: object | None = None` (parsed Python object: dict/list/scalar) + `json_truncated: bool = False`.

### 3. GeoTIFF — `geotiff` mode

**Trigger:** `fmt in {"tif", "tiff"} AND rasterio import succeeds AND file opens as rasterio dataset`. If rasterio is unavailable or the file fails to open as a dataset, **fall back to the existing `image` mode** (QPixmap thumbnail) with a warning `"地理元数据读取失败，仅显示图像"`.

**Widget:** `GeoTiffPreviewWidget(QWidget)` — a vertical layout:
- Thumbnail: downsampled overview band (rasterio `overview` or decimated read) as QPixmap, scaled to fit.
- Metadata summary table: CRS (e.g. `"EPSG:32649"`), bounds (west/south/east/north), dimensions (width × height × band count), dtype, nodata value.
- Worker-thread work: `rasterio.open()` + read overview + extract `crs/bounds/transform/dtypes/nodata` → encode thumbnail as PNG bytes. UI thread: decode QPixmap + populate table.

**Fallback path:** `_geotiff_preview()` catches `ImportError`/`RasterioIOError`/`Exception` → returns a `PreviewResult(mode="image", ...)` with `image_bytes` (from a Pillow/Qt fallback read) + `warning`. The existing `ImagePreviewWidget` renders it; no new widget involved in fallback.

**PreviewResult fields used:** `title`, `path`, `revision`, `format`, `status`, `type_label`, `warning` + new fields `image_bytes: bytes` (reused from image mode) + `geo_metadata: tuple[tuple[str,str],...] = ()` (key/value rows for the summary table).

### 4. Audio — `media` mode

**Trigger:** `fmt in {"wav", "mp3", "flac", "ogg", "m4a"}`.

**Widget:** `MediaPreviewWidget(QWidget)`:
- `QMediaPlayer` + `QAudioOutput` (audio-only; no video surface).
- Controls: play/pause button, seek slider (`QSlider` bound to position/duration), time label (`mm:ss / mm:ss`), volume slider.
- Worker-thread work: read file size + probe duration via `QMediaPlayer.duration` (set source on UI thread, duration arrives async). Minimal off-thread work — media decoding is Qt's responsibility.

**PreviewResult fields used:** `title`, `path`, `revision`, `format`, `status`, `type_label` + new field `media_path: str = ""` (the file path; widget sets it as `QMediaSource` on the UI thread — media objects are not worker-thread-safe).

**Codec availability:** if `QMediaPlayer` can't decode (no backend codec), the player shows `"无法播放此格式（缺少解码器）"` message. No hard failure — gracefully degrades.

## PreviewResult Changes

Add these optional fields (all default-empty, backward-compatible):

```python
@dataclass(frozen=True)
class PreviewResult:
    # ... existing fields ...
    rich_html: str = ""          # rendered HTML for rich_text mode
    json_payload: object | None = None  # parsed JSON for json_tree mode
    json_truncated: bool = False
    geo_metadata: tuple[tuple[str, str], ...] = ()  # GeoTIFF summary rows
    media_path: str = ""         # audio file path for media mode
```

`PreviewMode` literal extended: add `"rich_text"`, `"json_tree"`, `"geotiff"`, `"media"`.

## New Dependencies

| Package | Purpose | Weight |
|---------|---------|--------|
| `markdown` | Markdown→HTML (pure Python) | Light (~100KB) |
| `rasterio` | GeoTIFF metadata + overview read | Heavy (pulls GDAL) |

**Installation strategy** (lesson from the geoviz baseline break): add both to `pyproject.toml` `dependencies` so `pip install -e .` pulls them. `rasterio` wheels include GDAL on Linux/macOS/Windows for Python 3.12 — no system GDAL needed. Add to `requirements-geoviz.txt`? No — these are main-project deps, not engine subpackages; they belong in `pyproject.toml` directly.

`QMediaPlayer`/`QAudioOutput` ship with PySide6 (already installed) — no new dep for audio.

## File Changes Summary

| File | Change |
|------|--------|
| `paleo_workbench/ui/pages/preview_provider.py` | +4 format sets, +4 `PreviewMode` literals, +4 `_xxx_preview()` methods, +5 `PreviewResult` fields |
| `paleo_workbench/ui/pages/preview_widgets.py` | +4 widgets (`RichTextPreviewWidget`, `JsonTreePreviewWidget`, `GeoTiffPreviewWidget`, `MediaPreviewWidget`) |
| `paleo_workbench/ui/pages/data_reader_panel.py` | +4 stack slots + 4 dispatch branches in `render()` |
| `paleo_workbench/ui/pages/preview_strategy.py` | Extend `preview_for_resource` to recognize the 4 new format families (return appropriate `PreviewState` mode) so the legacy sync path stays consistent |
| `paleo_workbench/resources/scanner.py` | Ensure new extensions (md/markdown/htm/html/json/geojson/wav/mp3/flac/ogg/m4a) are recognized in format/type detection (verify; may already be via extension table) |
| `pyproject.toml` | Add `markdown`, `rasterio` to dependencies |

## Testing

Each format gets focused provider tests + widget smoke tests:

- `tests/test_preview_provider.py` (extend):
  - `test_markdown_preview`: `.md` file → mode `rich_text`, `rich_html` contains `<h1>`/`<p>`.
  - `test_html_preview`: `.html` → mode `rich_text`, `rich_html` set.
  - `test_json_preview`: `.json` → mode `json_tree`, `json_payload` is the parsed dict.
  - `test_json_large_array`: large array → `json_truncated` flag behavior (or collapsed node — assert the payload carries enough to build the collapsed tree).
  - `test_geojson_preview`: `.geojson` with `type: FeatureCollection` → mode `json_tree`, payload recognized.
  - `test_geotiff_preview`: `.tif` (synthetic rasterio-writable file in tmp) → mode `geotiff`, `geo_metadata` has CRS/bounds rows.
  - `test_geotiff_fallback_to_image`: rasterio unavailable or bad file → mode `image` + warning.
  - `test_audio_preview`: `.wav` → mode `media`, `media_path` set.
  - **rasterio guard:** tests that import rasterio must skip gracefully if unavailable (`pytest.importorskip("rasterio")`).

- `tests/test_preview_widgets.py` (new or extend):
  - Smoke: each widget constructs, loads a sample result, doesn't crash.
  - `RichTextPreviewWidget`: loads HTML, displays.
  - `JsonTreePreviewWidget`: builds tree from a sample payload; collapsed-array node present.
  - `GeoTiffPreviewWidget`: loads thumbnail + metadata table.
  - `MediaPreviewWidget`: constructs player, sets source path.

- `tests/test_data_reader_panel.py` (extend):
  - Each new mode routes to the correct widget in the stack (assert `stack.currentWidget()` is the right type).

All existing tests must continue to pass.

## Acceptance Criteria

1. A `.md` file renders as rich text (headings/lists/code) in the reader panel.
2. A `.json`/`.geojson` file renders as a collapsible tree, with large arrays collapsed.
3. A `.tif` GeoTIFF renders as a thumbnail + CRS/bounds/dimensions metadata table.
4. A corrupt/non-raster `.tif` falls back to image preview with a warning.
5. A `.wav`/`.mp3` file shows an inline player (play/pause/seek/volume).
6. rasterio-unavailable environments degrade gracefully (GeoTIFF→image fallback).
7. Existing preview modes (text/table/Excel/LAS/SEG-Y/PDF/image) unchanged.
8. `markdown` and `rasterio` declared in `pyproject.toml`.
9. All existing + new tests pass.

## Risks

- **rasterio/GDAL install:** heavy dependency. Mitigated by wheel availability for Python 3.12 (no system GDAL) and graceful fallback to image mode if import fails.
- **QMediaPlayer codec availability:** varies by OS/backend. Acceptable — degrades to a message, doesn't crash.
- **Large JSON memory:** capped at 5 MB parse + collapsed-array lazy population.
- **QTextBrowser security:** external resource loading disabled by overriding `loadResource`; local file images allowed.
- **Worker-thread safety:** `QMediaPlayer` and `QPdfDocument` are NOT worker-safe — like PDF, audio source-setting stays on the UI thread; only file-size read happens off-thread.
