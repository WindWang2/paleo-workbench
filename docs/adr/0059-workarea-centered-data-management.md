# ADR 0059: WorkArea-Centered Geological Data Management

- Status: Accepted
- Date: 2026-08-21
- Deciders: WindWang2 (product decisions 1B/2A/3B/4A confirmed), OpenCode Build (implementation)

## Context

Data management was ResourceItem/DataAsset-centric: files were the primary
object, wells existed only as rows in factor-prep tables, per-file previews,
and ad-hoc string identities (five parallel well-id namespaces; two well_head
parsers; no persisted seismic survey). The product decision is to organize the
workbench around geological business objects:

```
Project / WorkArea → Geological Domain Entity → DataAsset → Immutable DataVersion → DataRun
```

Confirmed constraints: `*.paleo.json + *.artifacts/` persistence (1B); import
defaults to managed RAW with Link External as advanced option (2A); entity-first
Data Manager IA (3B); project-level well GIS instead of single-file XY scatter (4A).

## Decision

### 1. One Project = One WorkArea

`ProjectDocument.workarea: WorkArea | None` (additive field). The WorkArea holds
name/description/boundary/vertical datum/units. **`ProjectDocument.coordinate`
remains the canonical CRS authority**; `WorkArea.project_crs/display_crs` are
projections kept in sync by `sync_workarea_with_coordinate()` before every save.
No competing second authority exists.

### 2. Domain registries on ProjectDocument

Additive lists (old files load unchanged via Pydantic defaults):

- `wells: list[WellEntity]` — stable canonical `Well.id`; uwi/aliases;
  source coords preserved verbatim (`surface_x/y/z`, `source_crs`) plus
  projected `project_x/y` and `coordinate_status`
  (`ok | untransformed | invalid | missing`). A Well is NOT a LAS file, a
  WellTableRow, or a filename.
- `seismic_surveys: list[SeismicSurveyEntity]` — survey geometry frozen at
  discovery (corners, inline/crossline ranges, dt/t0) reusing
  `survey_corners_from_segy`.
- `geological_entities / auxiliary_entities: list[DomainEntity]` — lightweight
  named containers for horizons/faults and non-geological material.
- `entity_asset_links: list[EntityAssetLink]` — explicit
  `(entity_type, entity_id, asset_id, role, is_primary, unresolved)` relations.
  Relationships are NEVER inferred from tags.

### 3. Catalog remains the lifecycle authority

DataAsset/DataVersion/DataRun/checksum/lineage/trash/tags are untouched. Domain
entities reference catalog assets by id; nothing bypasses
`DataCatalogService`. Import pipeline: file → classify → parse metadata →
resolve/create entity → managed copy (`import_raw`, SHA-256, immutable RAW) →
`EntityAssetLink`. RAW edits continue through working copy → commit as new version.

### 4. Identity resolution (§13)

Priority: persisted id → UWI → normalized canonical name → alias → explicit
mapping. Normalization is conservative (NFKC + casefold + separator collapse);
ambiguous name hits never merge silently — every candidate receives an
`unresolved=True` link so governance UI can surface it without blocking other
imports. File-side UWI extraction awaits an upstream geo-viz payload extension
(known follow-up).

### 5. Central migration (schema v1 → v2)

`paleo_workbench/project/domain_migration.py` is the only migration path — no
scattered `hasattr` compat hacks. Triggered on open inside the existing
deferred catalog-maintenance thread. Properties:

- deterministic (resources sorted by id; resolution order fixed);
- idempotent (existing entities matched by identity keys; late-binding pass
  attaches links only for resources whose asset is not yet linked);
- non-destructive (legacy `resources` untouched; migration mutates memory and
  persists only on the next successful save; failures become report issues).

Strong evidence only: SMI well_head files parsed through the canonical
geo-viz backend, SEG-Y headers, LAS headers. Filenames are never identity.

### 6. Data Manager IA 3.0

NavigationTree gains entity-first groups (工区概览 / 井 / 地震 / 地质解释 /
辅助资料 / 工作数据 / 成果) while legacy lifecycle/type/tag/integrity/governance
views remain as secondary smart filters. Well leaves expand to role sub-leaves
(测井/井轨迹/分层/时深/解释/其他) backed by link roles. 工区概览 swaps a cheap
overview panel over the asset table (cached counts only, no scans).

### 7. Project Well Location GIS

New 井位地图 page fed exclusively by the Well Registry. Rendering reuses the
geo-viz PlotWidget with batched series (ok / flagged / selected) — no per-well
widgets; the searchable list is model/view with uniform item sizes. Tree↔map
selection syncs through canonical `Well.id` in both directions. Wells lacking
CRS declarations plot from source coordinates in a flagged amber series with
⚠ markers — never silently mixed into the projected set.

## Consequences

- Old projects open without re-import; first save upgrades them to schema v2.
- Five well-id namespaces still exist in legacy modules; the new API provides
  the canonical adapter surface (`Well.id` + registries) for incremental
  migration of Well Log / Correlation / Joint modules (follow-ups).
- File-side UWI matching requires upstream XYPreviewPayload extras (follow-up).
- GDAL reference layers on the GIS map reuse the mapping module later
  (boundary + survey extents ship now).

## Compliance notes

- No second catalog authority; no duplicate well parser (both existing parsers
  reused for their original purposes).
- No destructive migration; legacy resources preserved verbatim.
- Performance: 50k-well rebuild ≈ O(N) numpy once per domain change; selection
  O(1); verified by `tests/test_project_well_map.py::TestWellMapPerformance`.
