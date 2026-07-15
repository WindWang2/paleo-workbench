# GeoViz-Powered Local Data Preview Design

**Date:** 2026-07-15
**Status:** Approved
**Scope:** Data-page local visualization and the public GeoViz engine package boundary

## Context

The workbench currently discovers the repository `data/` directory as its default sample data source. The data page already has asynchronous, cached previews for documents, tables, images, PDFs, LAS metadata, and SEG-Y metadata. Real geological rendering is split across the visualization page and direct imports from internal packages such as `geoviz_well_log`, `geoviz_seismic`, and `geoviz_plots`.

The default dataset includes LAS, SGY, DAT, DFB, WLP, SpreadsheetML XML, Excel, images, PDF, PPTX, ZIP, and other files. The data page should provide an immediate, bounded visualization when a selected resource has meaningful visual semantics. Professional parsing and rendering must belong to an independently installable GeoViz engine, not to `paleo_workbench`.

## Goals

1. Add an interactive local visualization to the existing right-side smart preview area on the data page.
2. Support as many default `data/` formats as can be handled reliably, while retaining the existing document and metadata fallbacks.
3. Keep the data page responsive for large files, including the approximately 1 GB sample SGY file.
4. Establish `geo-viz-engine` as an independently installable visualization engine with one stable public `geoviz` namespace.
5. Keep complete analysis workflows on the full visualization page; local preview provides fast inspection and basic interaction.

## Non-Goals

- Rewriting the complete visualization page in this phase.
- Reverse-engineering proprietary DFB or WLP formats without a reliable specification or parser.
- Loading a complete seismic volume for a data-page preview.
- Moving every existing internal GeoViz module into one physical Python package in a single migration.
- Guessing geological semantics for arbitrary tabular columns.

## Chosen Product Design

The data page retains its existing three-column structure. Selecting a resource automatically switches the right-side reader to the best available view:

- a GeoViz professional canvas for recognized geological data;
- the existing table, document, image, PDF, or media reader for ordinary content;
- a clear metadata or unsupported state when no reliable preview exists.

The inspector remains below the reader. Local professional canvases preserve basic interaction such as zoom, pan, curve visibility, and two-dimensional slice selection. A persistent **Open in Visualization** action opens the same resource reference in the full visualization page for complete analysis.

## Architecture

### Ownership Boundaries

`paleo_workbench` owns:

- resource selection and project references;
- background-task orchestration;
- generation tokens for stale-result rejection;
- preview-payload caching;
- the right-side preview host and fallback reader;
- navigation to the full visualization page.

`geo-viz-engine` owns:

- professional format parsing used for visualization;
- bounded geological preview preparation;
- preview capabilities and format registration;
- professional Qt canvases and their rendering behavior;
- structured engine errors and cleanup hooks.

`geo-viz-engine` must not import or depend on `paleo_workbench`. After migration, workbench production code must use the public `geoviz` API instead of importing internal `geoviz_*` packages directly.

### Data Flow

```text
resource selected
    -> data page builds PreviewRequest
    -> LocalVisualizationRegistry checks GeoViz support
    -> worker thread calls GeoVizEngine.prepare(...)
    -> workbench stores bounded PreparedPreview in a byte-weighted cache
    -> UI thread lazily creates or reuses the matching GeoViz widget
    -> GeoVizEngine.render(widget, payload)
    -> unsupported/error result falls back to the existing reader
```

The existing generation-token rule remains authoritative: after rapid selection of A, B, and C, only C may update the visible reader. Rendering a failure must clear stale graphics from the previous resource.

## GeoViz Engine Package

### Distribution and Namespace

`geo-viz-engine` becomes the installable umbrella distribution and exposes one stable namespace:

```python
from geoviz import GeoVizEngine, PreviewOptions, PreviewRequest
```

Recommended structure:

```text
geo-viz-engine/
├── geoviz/
│   ├── __init__.py
│   ├── contracts.py
│   ├── engine.py
│   ├── registry.py
│   └── previews/
└── packages/
    ├── geoviz_common/
    ├── geoviz_well_log/
    ├── geoviz_seismic/
    ├── geoviz_cross_well/
    ├── geoviz_plots/
    ├── geoviz_map/
    └── geoviz_paleo_map/
```

The existing subpackages remain internally modular and independently testable during the migration. Their current public imports remain temporarily compatible, but workbench code migrates to `geoviz`. This avoids a high-risk physical merge while still creating one supported external engine boundary.

Local development installation may continue installing workspace members before the umbrella distribution until the internal distributions are available through the configured package source. The supported consumer contract is nevertheless a single `geo-viz-engine` installation and the `geoviz` namespace.

### Public Contracts

The initial public surface is:

```python
engine.supports(request) -> bool
engine.capabilities(request) -> PreviewCapabilities
engine.prepare(request, options) -> PreparedPreview
engine.create_widget(kind, parent=None) -> QWidget
engine.render(widget, payload) -> None
engine.release(widget) -> None
```

`PreviewRequest` contains a stable resource identifier, absolute or resolved path, declared semantic type, file format, and optional display label. It does not contain a `paleo_workbench` model.

`PreviewOptions(profile="local")` applies bounded local-preview defaults. `PreparedPreview` contains only plain Python data, Pydantic models, and/or NumPy arrays safe to create in a worker thread; it must not contain Qt objects. It also reports an estimated memory cost for cache accounting.

`PreviewCapabilities` describes the selected preview kind, supported interactions, fallback availability, and whether preparation requires an optional dependency.

### Preparation and Rendering Thread Rules

- `supports`, `capabilities`, and `prepare` must be callable without constructing a Qt widget.
- `prepare` must be safe to run in the workbench preview worker.
- `create_widget`, `render`, and `release` run only on the UI thread.
- Parsers close file handles before returning a prepared payload unless an explicit engine-managed streaming handle is required. Local preview will prefer detached bounded payloads.

## Format Coverage

| Resource | Local visualization | GeoViz implementation | Fallback |
|---|---|---|---|
| LAS well log | Multi-track curves, depth zoom, curve visibility | Reuse `geoviz_well_log`; expose a public bounded LAS loader | Current LAS metadata summary |
| SGY/SEGY seismic | Middle inline by default; switch among inline, crossline, and time slices | Add a lightweight two-dimensional `SeismicPreviewWidget` using `geoviz_seismic` loaders and profiles | Current seismic metadata summary |
| Well-head DAT | XY well scatter with labels, zoom, and pan | Reuse `geoviz_plots` scatter rendering | Bounded table/text preview |
| Well-stratification DAT | Well-versus-depth formation-top comparison with points and correlations | Add a lightweight formation-tops preview in `geoviz_cross_well`, composed from existing plot/correlation primitives | Bounded table/text preview |
| Horizon DAT | XYZ points or bounded interpolated surface with color scale | Reuse `geoviz_plots.SurfaceWidget` and interpolation | Bounded table/text preview |
| Time-depth DAT | Time-depth line or scatter plot | Reuse `geoviz_plots` two-dimensional chart | Bounded table/text preview |
| Excel and SpreadsheetML XML | Sheet/table preview; chart only when a known geological schema is recognized | Existing table reader plus `geoviz_plots` for recognized schemas | Existing table/text preview |
| PNG/JPG/TIFF | Zoomable image; GeoTIFF includes CRS and bounds | Existing image/GeoTIFF reader | Metadata message |
| PDF/PPTX | PDF pages; best-effort PPTX page thumbnails | Existing PDF reader; add bounded PPTX conversion only when a reliable dependency is available | Metadata message |
| DFB | Embedded thumbnail or same-name companion image when reliably discoverable | No proprietary data parser in this phase | Metadata/unsupported message |
| WLP | No professional parsing in this phase | No reliable parser or specification is present | Metadata/unsupported message |
| ZIP/unknown | Bounded archive listing where safe, otherwise metadata | Non-professional reader | Metadata/unsupported message |

Schema recognition is conservative. A table is charted only when its header and semantic resource type match a registered parser, such as the sample `WellHead`, `WellTops`, or `XYZInlineCrossline` DAT headers.

## Performance and Resource Management

### Bounded Local Profile

`PreviewOptions.local()` defines these initial defaults as named, independently testable constants:

- LAS displays at most 12 non-depth curves and 2,000 uniformly sampled depth rows.
- SGY reads only the selected two-dimensional slice and downsamples each displayed axis to at most 512 samples. It never reads the entire volume for local preview.
- Point plots display at most 50,000 spatially representative points while preserving the full coordinate extent.
- Surface interpolation uses a grid no larger than 256 by 256 and runs off the UI thread.
- Tables and SpreadsheetML read at most 256 KiB of source text per initial pass and display at most 200 rows, 40 columns, and one active sheet. Sheet names may be indexed without loading every sheet body.
- ZIP preview lists at most 500 entries and does not extract archive content.
- Documents and images retain their existing bounded decoding behavior.

These values are engine options rather than hard-coded widget behavior, so a full visualization page may request a different profile. The existing count-based preview cache is extended or replaced for GeoViz payloads by a byte-weighted LRU with a default 128 MiB budget. A single payload larger than the budget is rendered once and not cached. Cache entries use the stable resource revision token already derived from resource identity, checksum, file size, and modification time.

### Widget Lifecycle

- Professional widgets are constructed lazily by preview kind.
- Widgets are reused when another resource uses the same preview kind.
- Switching to a different kind hides the old widget and releases resource-specific state.
- Leaving the data page, closing the project, or closing the application releases engine widgets, file handles, media sources, and preview workers.
- The local seismic preview does not initialize the full three-dimensional OpenGL renderer.

## Error Handling

GeoViz reports structured errors with these stable categories:

- `unsupported`
- `invalid_data`
- `dependency_missing`
- `io_error`
- `resource_limit`
- `render_error`

The workbench maps them to short Chinese reader messages and an available fallback. Preview failures do not open modal dialogs. Diagnostic details remain available for logs and tests without exposing full tracebacks in the reader.

An unsupported or failed professional preview must clear the previous professional canvas before displaying the fallback. Proprietary formats are not heuristically decoded when doing so could produce misleading geology.

## Testing Strategy

### GeoViz Unit and Contract Tests

- Import `geoviz` in isolation and assert it has no `paleo_workbench` dependency.
- Test registry selection and capability reporting for each supported semantic type and format.
- Test minimal LAS, SGY, WellHead DAT, WellTops DAT, horizon DAT, and time-depth fixtures.
- Verify LAS downsampling, SGY slice-only reads, bounded point counts, bounded interpolation grids, and estimated payload sizes.
- Verify structured errors for malformed files, missing dependencies, missing paths, and resource limits.
- Verify the current internal `geoviz_*` imports remain compatible during the migration window.
- Verify widget creation, basic interaction, payload replacement, clearing, and release with pytest-qt.

### Workbench Integration Tests

- Selecting each registered resource routes to the expected local preview kind.
- Rapid A/B/C selection displays only C.
- Engine unsupported/error results use the existing reader fallback.
- Changing kind or encountering failure never leaves stale graphics.
- Re-selecting an unchanged resource uses the prepared-payload cache.
- **Open in Visualization** passes the same resource identity and path to the complete visualization page.
- Data-page shutdown and application shutdown terminate workers and release engine resources.
- Production workbench modules import the `geoviz` facade rather than internal GeoViz subpackages.

### Real-Data Smoke Tests

The repository `data/` directory supplies opt-in `slow` smoke tests for representative LAS, the approximately 1 GB SGY, well-head DAT, well-stratification DAT, horizon DAT, SpreadsheetML XML, images, and PDF. Normal CI uses small fixtures. The SGY smoke test verifies slice-only access and UI responsiveness rather than loading the complete volume.

DFB and WLP pass when the reader provides a clear fallback without crashing or blocking. They are not considered professionally visualized until a reliable documented parser exists.

## Acceptance Criteria

1. Selecting a supported geological resource on the data page automatically displays the matching interactive local visualization in the right reader.
2. Unsupported or failed formats degrade to the existing reader without a modal error or stale canvas.
3. Local previews remain bounded, asynchronous, revision-cached, and latest-selection-wins.
4. The sample SGY local preview performs slice-only I/O and does not initialize the full 3D renderer.
5. The engine is installable and importable through `geoviz` without depending on the workbench.
6. Workbench production code uses the `geoviz` public facade for professional visualization.
7. Existing full visualization workflows continue to load the same project resources.

## Implementation Sequence

1. Create the `geoviz` facade, contracts, registry, packaging, and independence tests.
2. Migrate existing workbench professional visualization imports to the facade without changing behavior.
3. Add bounded GeoViz preparers and preview widgets for LAS and SGY.
4. Add semantic DAT parsers and plot/cross-well previews.
5. Integrate the local visualization registry and host into the data reader, including cache and lifecycle handling.
6. Extend best-effort non-geological fallbacks such as SpreadsheetML, PPTX, archive listing, and DFB companion thumbnails.
7. Run fixture tests, workbench integration tests, and opt-in real-data smoke tests.
