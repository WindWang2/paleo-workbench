# Paleogeography Mapping Workbench Design

Date: 2026-07-05

## Goal

Build a desktop prototype system for paleogeographic map compilation. The first MVP focuses on a runnable, high-fidelity workflow from project data to factor maps, sedimentary facies prediction, paleogeographic map editing, quality control, and export.

The UI must strictly follow the existing prototype reference:

`/home/kevin/projects/paleo_project/古地理图编制系统 (standalone).html`

Before implementation, extract a screen inventory from the prototype into the implementation plan. The inventory should identify the main navigation pages, key dashboard cards, task panels, data tables, dialogs, design tokens, and reusable component patterns. Implementation should not repeatedly parse or depend on the standalone bundle at runtime.

The existing `geo-viz-engine` subproject remains an independent visualization engine. The new system can modify `geo-viz-engine` when needed, but business workflow state belongs to the main paleogeography application.

## Confirmed Scope

The first MVP uses a hybrid fidelity strategy:

- The main UI and workflow should closely match the standalone prototype.
- Key nodes should connect to real sample data from `/home/kevin/projects/paleo_project/data`.
- Sedimentary facies prediction is a replaceable mock or service adapter in the first MVP.
- The default project coordinate reference is `EPSG:4326 / WGS84`.
- The stratigraphic framework manages target horizons plus sequence scheme metadata. It does not implement full stratigraphic calibration or correction tools in the first MVP.

## Architecture

Use a two-part architecture:

1. Main paleogeography workbench application.
2. `geo-viz-engine` as an independent visualization engine subproject.

The main application owns:

- Project file format and project lifecycle.
- Data resource catalog and provenance.
- Target horizon and sequence stratigraphic framework.
- Compilation workflow state.
- Factor map task orchestration.
- Prediction task orchestration.
- Quality control state.
- Export artifact tracking.
- UI shell matching the standalone prototype.

`geo-viz-engine` owns:

- Well log visualization.
- Seismic visualization.
- Cross-well and well-tie visualization.
- Factor map and contour visualization.
- Paleogeographic map canvas rendering and editing widgets.
- High-fidelity map/chart export rendering.
- Reusable interpolation, projection, rendering, and style utilities.

The main application may import Python modules from the `geo-viz-engine` workspace packages directly, such as `geoviz_paleo_map`, `geoviz_plots`, and `geoviz_seismic`. If an existing engine page is too tightly coupled to the old desktop shell, add lightweight adapters inside `geo-viz-engine` instead of moving business workflow logic into the engine.

## MVP Work Areas

### 1. Project Workbench

The workbench provides new, open, save, and save-as project operations. It displays project metadata, target horizon, sequence scheme, default CRS, recent tasks, and result overview.

The first screen must be a workflow dashboard, not a generic data browser. When a user opens a project, the dashboard should answer:

- Which target horizon and sequence scheme are active.
- Whether required resources are present.
- Which factor maps are complete, missing, mock-derived, or stale.
- Which prediction task is current and whether it needs review.
- Which paleogeographic map document is current.
- Which QC issues block export.
- Which artifacts have already been exported.

The dashboard is the control surface for the compilation run. Data and visualization pages are supporting views.

### 2. Data Management

The system scans and imports the sample data directory. Resource types include:

- Well locations.
- LAS well logs.
- SEGY seismic volumes.
- Horizon DAT files.
- time-depth DAT files.
- well stratification DAT files.
- outsourced reports and charts.
- image references.
- PDF, PPT, Excel, XML, WLP, and DFB files.

Each resource records type, path, format, CRS, parse status, tags, source, parsed summary, and provenance.

Unsupported or proprietary formats should still be indexed as reference resources. The scanner should classify them, preserve their path and metadata, and mark them `status=indexed_reference` rather than failing the scan.

### 3. Data Visualization

The main application embeds `geo-viz-engine` visualization widgets for inspection and source traceback. Visualization is read-oriented in the MVP and does not own compilation workflow state.

Required views:

- Well log preview.
- Seismic slice or volume preview.
- Cross-well or well-tie preview.
- Reference image/document preview where practical.
- Factor map preview.
- Paleogeographic map preview.

### 4. Compilation Data Preparation

The workbench creates or registers factor map tasks for the selected target horizon. First-phase factor map types include:

- Stratigraphic thickness map.
- Sand body thickness map.
- Sand-ground ratio map.
- Porosity contour map.
- Mudstone thickness map.
- Seismic attribute plan map.

When real fields are available, tasks use real sample data and existing interpolation/rendering utilities. When fields are missing, tasks may use mock data, but the task must record `source_kind=mock`.

Mock-derived factor maps must be deterministic. Store `seed`, `generator_version`, and `input_snapshot_hash` in the task parameters so demonstrations, tests, and future comparisons are reproducible.

### 5. Sedimentary Facies Prediction

Prediction is modeled as a replaceable adapter:

- `mock`: deterministic prototype result.
- `http`: future model service endpoint.
- `local`: future local model implementation.

Inputs include well logs, horizons, sequence scheme, factor maps, and seismic attributes. Outputs include predicted facies, probabilities, evidence contribution, low-confidence areas, and regions requiring review.

The MVP should present prediction results and provenance clearly without pretending mock results are real model output.

Mock prediction outputs must be deterministic. Store `seed`, `generator_version`, `input_snapshot_hash`, and adapter schema version with each prediction task result.

### 6. Paleogeographic Map Compilation, QC, and Export

The paleogeographic map document uses `geo-viz-engine` paleomap widgets for display and editing. The workflow supports:

- Generating an initial facies boundary draft from prediction results.
- Manual editing of facies polygons.
- Facies legend and style management.
- Well point overlay.
- North arrow, scale bar, title block, and coordinate/grid display.
- QC checks.
- Export to PDF, SVG, PNG, GeoJSON, and project artifact records.

## Workflow

The MVP data flow is:

`project file -> resource catalog -> target horizon/sequence scheme -> factor map tasks -> prediction task -> paleogeographic draft -> manual edit -> QC report -> exported artifacts`

Every stage writes structured state to the project file. Each output records its input IDs, method, parameters, status, and provenance.

The workflow should be represented as an explicit compilation run, not only as disconnected task objects. A run links the target horizon, selected resources, methods, intermediate results, QC reports, and export artifacts into one auditable evidence chain.

## Project File Model

The main application should use an independent project file format such as `.paleo.json` or `.paleo`. The MVP should use JSON for easier debugging.

The project file should store stable metadata and relative paths, not large generated arrays or binary outputs. Generated grids, thumbnails, exported maps, and reports should live under a project artifact directory next to the project file.

Default project layout:

```text
project-name.paleo.json
project-name.artifacts/
  cache/
  factor_maps/
  predictions/
  paleomaps/
  qc/
  exports/
  thumbnails/
```

All paths in the project file should be relative to the project file directory when possible. Resources outside the project directory may remain absolute but must be marked `external=true`.

### ProjectMeta

Fields:

- project name.
- region.
- created time.
- updated time.
- software version.
- project root directory.

### CoordinateReference

Fields:

- `project_crs`, default `EPSG:4326`.
- `target_crs`.
- `display_crs`.
- `transform_history`.

The first MVP stores CRS metadata and supports future reprojection, but does not require full coordinate conversion workflow.

### StratigraphicFramework

Fields:

- target horizon.
- sequence boundaries.
- systems tract scheme.
- interpretation version.
- applicable wells and seismic ranges.

### CompilationRun

Fields:

- run ID and name.
- target horizon.
- sequence scheme reference.
- status: draft, running, blocked, review_required, export_ready, exported, or failed.
- ordered workflow steps.
- active factor map task IDs.
- active prediction task ID.
- active paleomap document ID.
- active quality report ID.
- export artifact IDs.
- created time and updated time.

### WorkflowStep

Fields:

- step ID.
- step type: data_check, factor_map, prediction, map_compile, qc, or export.
- status: pending, ready, running, complete, warning, failed, skipped, or mock.
- required input resource IDs.
- produced task or artifact IDs.
- blocking issue summary.
- provenance summary.

### ResourceCatalog

Each resource has:

- `id`.
- `name`.
- `path`.
- `type`.
- `format`.
- `crs`.
- `status`.
- `tags`.
- `source`.
- `parsed_summary`.
- `checksum`.
- `external`.
- `artifact_role`, when the resource is generated by the workflow.

### FactorMapTask

Fields:

- task ID and name.
- target horizon.
- factor type.
- input resource IDs.
- method, such as IDW, SciPy, manual import, or mock.
- parameters.
- output resource IDs or paths.
- quality metrics.
- status.
- `source_kind`: real, imported, mock, or mixed.
- `input_snapshot_hash`.
- `generator_version`, when generated.
- `seed`, when mock-derived.

### PredictionTask

Fields:

- task ID and name.
- adapter kind: mock, http, or local.
- input factor map IDs.
- input well, seismic, horizon, and sequence references.
- model metadata.
- result paths or embedded summary.
- probability summary.
- evidence contribution.
- review areas.
- status.
- adapter schema version.
- `input_snapshot_hash`.
- `generator_version`, when generated.
- `seed`, when mock-derived.

### PaleoMapDocument

Fields:

- document ID and name.
- linked target horizon.
- linked prediction task.
- facies polygons.
- facies style and legend.
- well overlays.
- map chrome configuration.
- view state.
- edit history.

### QualityReport

Fields:

- report ID.
- linked map document.
- rules.
- issue list.
- issue geometry or location.
- severity.
- status.
- generated time.

### ExportArtifact

Fields:

- artifact ID.
- linked map document or report.
- format.
- output path.
- DPI or vector setting.
- scale or layout template.
- included map elements.
- generated time.
- source task IDs.

## Main Application Package Layout

The main application should be a real Python package at the project root, not a loose script collection. The root currently contains the data directory, the standalone UI reference, and the `geo-viz-engine` git subproject, so the MVP must add packaging before implementation.

Recommended layout:

```text
pyproject.toml
paleo_workbench/
  __init__.py
  main.py
  app.py
  project/
  resources/
  workflow/
  prediction/
  ui/
  adapters/
tests/
docs/
data/
geo-viz-engine/
```

The root `pyproject.toml` should declare a path dependency on `geo-viz-engine` or install the engine workspace in editable mode for development. The main app should run through a stable entry point such as:

```bash
python -m paleo_workbench.main
```

The implementation plan should decide whether root-level git initialization is required before code work begins. Without a root repository, design docs and main app code cannot be committed together.

## `geo-viz-engine` API Boundary

The main application should call these engine-level capabilities:

- `WellLogViewer`: display LAS or parsed well log data.
- `SeismicViewer`: display SEGY slices, seismic attributes, and horizon overlays.
- `CrossWellViewer`: display cross-well sections and stratigraphic/facies correlation.
- `FactorMapViewer`: display scattered points, grids, contours, colorbars, and factor map export previews.
- `PaleoMapViewer`: display and edit facies polygons, well points, legends, and map chrome.
- `ExportService`: render high-fidelity PDF, SVG, PNG, and GeoJSON exports.

If these APIs do not exist cleanly today, add adapters in `geo-viz-engine` that wrap current pages/widgets. These adapters must not depend on the main application's project schema.

### Minimum Adapter Contract

Engine adapters should expose a small, stable interface so the main workbench does not depend on old `geo-viz-engine` page state or navigation.

Required methods:

- `set_data(payload: dict) -> None`: replace the displayed dataset.
- `set_view_state(state: dict) -> None`: restore viewport, selections, visible layers, and style choices.
- `get_view_state() -> dict`: return serializable visual state for the project file.
- `export(path: str, options: dict) -> dict`: write an artifact and return export metadata.
- `clear() -> None`: reset the viewer to an empty state.

Required signals or callbacks:

- `selection_changed(payload: dict)`: emitted when a user selects a well, layer, polygon, point, or interval.
- `edit_committed(payload: dict)`: emitted when an editable viewer changes geometry or styling.
- `error_occurred(payload: dict)`: emitted when rendering, loading, or export fails.

Adapters may use Qt signals internally, but the payloads must remain plain serializable dictionaries at the main-application boundary.

The main workbench should not directly depend on `geo-viz-engine/src/app.py`, `PAGE_CONFIGS`, old shell navigation, or page-local project state.

### Typed Adapter Schemas

The adapter boundary should use typed schemas internally and serialize to dictionaries at the boundary. Define these schemas in either the main app or a small shared adapter module:

- `ViewerPayload`: viewer type, data resources, layer list, style hints, CRS, and payload schema version.
- `ViewState`: viewport, selected IDs, visible layers, style overrides, and schema version.
- `ExportRequest`: output path, format, DPI/vector mode, selected layers, and layout options.
- `ExportResult`: output path, format, byte size if available, warnings, and produced artifact metadata.
- `AdapterError`: adapter name, operation, severity, message, recoverable flag, and optional traceback summary.

The adapter contract may expose dictionaries publicly, but each adapter should validate those dictionaries against typed schemas before rendering or exporting.

## Error Handling

The MVP should surface file and task problems at workflow level:

- Missing file: mark resource as missing and keep the project loadable.
- Unsupported format: record as indexed reference only.
- Parse failure: preserve the resource with `status=parse_failed` and error summary.
- Missing real data fields for a factor map: allow mock task creation only with explicit `source_kind=mock`.
- Prediction service unavailable: fall back to mock only if the user selects or confirms mock mode.
- Export failure: preserve the map document and record a failed artifact with error details.

## Testing Strategy

Minimum tests for the MVP:

- Project file round-trip for all core schema objects.
- Resource scanner classification for the current `data/` directory formats.
- Factor map task creation with real or mock input and provenance.
- Prediction adapter contract for mock mode.
- Paleomap document serialization with polygons, styles, and linked prediction task.
- QC rule execution with pass, warning, and error outputs.
- Export artifact record creation.
- Integration smoke test: create project, scan data, create factor map task, run mock prediction, create map document, run QC, create export record.
- Relative path and artifact directory round-trip tests.
- Deterministic mock output tests using seed and input snapshot hash.
- Adapter schema validation tests for valid payloads, invalid payloads, export results, and adapter errors.

`geo-viz-engine` changes need their own tests in the subproject when APIs or adapters are modified.

## MVP Success Criteria

The MVP is successful only if it can demonstrate the full compilation loop on the current sample workspace:

- Create and save a `.paleo.json` project.
- Scan `/home/kevin/projects/paleo_project/data` and classify the resource catalog.
- Select a target horizon and sequence scheme.
- Generate or register at least one factor map with explicit real-or-mock provenance.
- Run the mock prediction adapter and produce structured facies, probability, evidence, and review-area outputs.
- Create an initial paleogeographic map document linked to that prediction task.
- Display the map through a `geo-viz-engine` adapter.
- Run QC and produce pass, warning, or error records.
- Export at least one artifact record, even if the first export implementation writes metadata before full high-fidelity rendering is connected.
- Reopen the project and recover the workflow dashboard state.

The MVP should not be considered complete if it only reproduces the UI without project-file provenance and run recovery.

## Non-Goals For MVP

- Full production-grade coordinate reprojection workflow.
- Full stratigraphic calibration or correction tool.
- Real AI facies model training or inference implementation.
- Complete parsing of every outsourced proprietary format.
- Replacing `geo-viz-engine` as a visualization product.

## MVP Implementation Defaults

- Use `.paleo.json` as the MVP project file extension. A `.paleo` wrapper can be added later without changing the schema.
- Create the main application outside `geo-viz-engine`, under a dedicated top-level application package in the main project.
- Start by adding explicit viewer adapters for the compilation workflow. Existing reusable widgets may be embedded inside adapters, but the main application should depend on adapter contracts rather than old pages.
- Use the current sample `data/` directory as the first resource catalog source. For factor maps, use real parsed values where available and generate explicit mock values where required fields are missing.
- Keep all mock-derived outputs visibly labeled in the project state and UI.
- Use deterministic mock generation only; no unseeded random demo data in persisted workflow outputs.
- Treat packaging and local run commands as part of the first implementation slice, not follow-up work.
