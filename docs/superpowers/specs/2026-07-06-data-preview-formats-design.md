# Data Preview Formats Enhancement Design

> **Status:** Approved for planning
> **Date:** 2026-07-06
> **Scope:** Extend the Data page preview area from metadata-only summaries to safe, lightweight previews for multiple common file formats.

## Goal

The Data page should let users inspect common project files without leaving the application. Preview must stay lightweight, predictable, and safe: small text-like files and images can render inline; heavy professional formats remain metadata-first until a dedicated parser/viewer exists.

This enhancement builds on the current Data Management Center:

- `DataPage` already has catalog, asset table, detail panel, and import flows.
- `preview_strategy.py` already returns `PreviewState` with `mode`, `title`, `lines`, `image_path`, and `warning`.
- `DataDetailPanel` already consumes `PreviewState` and renders metadata lines.

## Preview Tiers

### Tier 1: Inline Visual Preview

Supported formats:

- `png`
- `jpg`
- `jpeg`
- `tif`
- `tiff`

Behavior:

- `PreviewState.mode == "image"`.
- `DataDetailPanel` attempts to show a scaled thumbnail with `QPixmap`.
- If image loading fails, the panel falls back to metadata lines and a warning.
- The strategy layer does not decode image bytes; decoding remains in the UI panel.

### Tier 2: Text Snippet Preview

Supported formats:

- `txt`
- `csv`
- `dat`
- `xml`

Behavior:

- `PreviewState.mode == "text"` for `txt` and `xml`.
- `PreviewState.mode == "table"` for `csv`, `dat`, and classified table-like resources.
- Preview reads only a bounded prefix of the file.
- Default limits:
  - maximum bytes: 8192
  - maximum lines: 20
- Binary-looking content falls back to metadata-only with a warning.
- Encoding handling is conservative: try UTF-8 first, then replace undecodable bytes.

### Tier 3: Metadata-Only Professional Formats

Supported formats:

- `las`
- `sgy`
- `segy`
- `xlsx`
- `xls`
- `pdf`
- `ppt`
- `pptx`
- `wlp`
- `dfb`

Behavior:

- These formats are not deep-loaded by default.
- The preview shows type, format, path, size, checksum when present, and a clear reason such as "此格式暂使用安全摘要预览".
- LAS and SEGY keep their specialized modes (`well_log`, `seismic`) but remain summary-only.
- Excel remains metadata-only for this phase to avoid adding a spreadsheet dependency.

### Tier 4: Unsupported Or Missing Files

Behavior:

- Unsupported files return `mode == "metadata"` and warning `"暂不支持预览"`.
- Missing files return metadata plus warning `"文件不存在"`.
- Preview failures must not remove the item from the project or crash the Data page.

## Component Changes

### Preview Strategy

Extend `PreviewState` rather than adding a new model:

- Keep existing fields for compatibility.
- Add optional `preview_lines: list[str]` if needed, or reuse `lines` for bounded snippets.
- Resolve relative paths with the existing `base_path` behavior.
- Add helper functions for safe text reads:
  - bounded bytes
  - bounded line count
  - binary-content detection
  - missing-file detection

The strategy remains pure and UI-independent.

### Data Detail Panel

Enhance rendering:

- For `image` mode, render a thumbnail label using `QPixmap`.
- For `text` and `table` modes, show snippet lines in a compact monospace-ish label style.
- For metadata-only modes, retain current metadata line rendering.
- Always show warnings in the preview area when present.

No nested cards should be introduced. The panel stays a fixed-width operational inspector.

## Error Handling

- Missing file: show `"文件不存在"` warning.
- Read permission error: show a warning with the filename and exception class.
- Decode error: use replacement decoding and include a warning only if content appears damaged.
- Oversized file: read only the bounded prefix; show `"仅显示前 20 行"` when truncated.
- Invalid image: show image path plus `"图片预览加载失败"` warning.

## Testing Plan

Unit tests:

- Image resources keep `mode == "image"` and expose `image_path`.
- TXT preview reads bounded lines.
- CSV preview uses table mode and includes header/row text.
- DAT preview uses table mode and does not read more than the configured limits.
- Missing file produces metadata mode with `"文件不存在"`.
- LAS/SEGY/PDF/XLSX remain metadata or specialized summary modes without deep reads.

Widget tests:

- `DataDetailPanel` renders a thumbnail widget for a valid image.
- Invalid image preview falls back to warning text.
- Text preview lines appear after selecting a text resource.
- Missing file warning appears in the detail panel.

Integration tests:

- Imported text/image files can be selected in `DataAssetTable` and rendered in `DataDetailPanel`.
- Existing Data Management Center tests remain green.

## Acceptance Criteria

- The Data page previews images inline when possible.
- The Data page previews text-like files with bounded content.
- CSV/DAT files show a lightweight table/text preview.
- Heavy professional formats remain safe summary-only previews.
- Missing, unreadable, invalid, unsupported, and oversized files produce readable non-crashing states.
- Full root test suite remains green.
