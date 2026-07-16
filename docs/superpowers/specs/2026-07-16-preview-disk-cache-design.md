# Project Preview Disk Cache Design

**Date:** 2026-07-16
**Status:** Approved
**Scope:** Data-page GeoViz previews — selective prepare-result disk cache under the project root

## Context

The data page already prepares many previews on a background worker (`PreviewRequestController`) and keeps a process-local, byte-weighted LRU (`PreviewCache`). GeoViz widget creation and `render()` remain UI-thread-only.

For large DAT-family assets (horizon surfaces, well stratification tops, well-head XY sets), re-selecting the same resource still re-runs bounded parse/resample work. That work is not interactive-critical the way seismic slice switching or well-log track interaction is, but it is expensive enough to feel sluggish when users flip between resources.

This design adds a **project-scoped disk cache of prepare results** for a small set of semantic types, without converting interactive previews (LAS, SGY) into static images.

## Goals

1. Keep **LAS** and **SGY** previews **interactive and behaviorally unchanged** (background `prepare`, UI-thread professional widgets).
2. For **horizon**, **well_stratification**, and **well_head** DAT previews: avoid repeating full bounded prepare when source file and options are unchanged.
3. Persist cache under the project as **`.preview_cache/`** intermediate artifacts (a dedicated cache category, not business geology resources).
4. Keep all heavy parse/resample/serialize/deserialize work **off the UI thread**.
5. Provide a clear way to **invalidate** (source change) and **clear** (user/action) the cache.

## Non-Goals

- Rasterizing seismic or well-log canvases to static thumbnails as the primary preview path.
- Caching plain text, small tables, SpreadsheetML, PPTX, ZIP, DFB, or WLP in this phase.
- Caching **time-depth** DAT in this phase (may follow the same mechanism later).
- Making `geo-viz-engine` depend on workbench project layout.
- Network/shared multi-user cache coherence.
- Guaranteeing cache as a long-term archival format (schema versioned; rebuild is always allowed).

## Product Decisions (confirmed)

| Decision | Choice |
|----------|--------|
| Cache location | `<project_root>/.preview_cache/` |
| Artifact kind | Project-local **preview cache artifacts** (not primary Resource tree kinds) |
| Cache payload | **Bounded prepare results** (serializable data), not full-screen screenshots |
| Cacheable types | `horizon`, `well_stratification`, `well_head` |
| Interactive types (unchanged) | `las` / well-log, `sgy` / seismic slices |
| time-depth DAT | Out of scope for v1 |

## Architecture

### Strategy split

```text
resource selected
    -> PreviewRequestController (generation / latest-only)
    -> classify semantic_type
         interactive (las, sgy, …)
             -> existing path: worker prepare -> UI GeoVizPreviewHost.render
         cacheable_prepare (horizon, well_stratification, well_head)
             -> worker:
                  lookup disk cache by CacheKey
                  hit  -> deserialize PreparedPreview-compatible payload
                  miss -> GeoVizEngine.prepare -> serialize to .preview_cache
             -> UI: GeoVizPreviewHost.render with prepared payload
                    (zoom/pan/hover as today’s widgets allow)
         other
             -> existing non-GeoViz / fallback readers
```

Interactive types never require a disk hit to show a correct preview. Cacheable types may still fall back to live `prepare` on any cache miss, corruption, or version mismatch.

### Ownership

| Component | Owner |
|-----------|--------|
| Cache key, index, file layout, eviction | `paleo_workbench` |
| Serialize/deserialize of prepare payloads | `paleo_workbench` (adapter around public `PreparedPreview` / payload dicts) |
| Parse, sample, build `PreparedPreview` | `geo-viz-engine` via public facade only |
| Qt widgets and `render` | UI thread + `geoviz` facade |
| Project path for `.preview_cache/` | Project manager / open project root |

Workbench production code continues to import only the public `geoviz` facade.

### Cache key

A cache entry is identified by a stable key derived from:

| Field | Purpose |
|-------|---------|
| `source_path` (resolved absolute or project-relative norm) | Identity of source file |
| `mtime_ns` + `size` | Invalidate on rewrite |
| `semantic_type` | horizon / well_stratification / well_head |
| `format` | e.g. `dat` |
| `options_fingerprint` | Hash of local preview options that affect prepare (max points, max grid axes, option schema version) |
| `payload_schema_version` | Integer bumped when on-disk format changes |

Key material is hashed to a short id (e.g. SHA-256 prefix) used as the directory name under `.preview_cache/entries/`.

### On-disk layout

```text
<project_root>/
  .preview_cache/
    index.json                 # optional fast index of entries
    entries/
      <key_hash>/
        meta.json              # CacheKey fields + created_at + byte sizes
        payload.npz            # or .json + .npy; see serialization
        # optional thumb.png   # future list thumbnail only; not primary preview
```

- `.preview_cache/` is project-local intermediate storage; add to default ignore rules for exports/VCS if not already covered by project packaging.
- Entries are **not** registered as first-class geology `ResourceItem`s in the main asset table.
- A lightweight **PreviewCacheArtifact** model (in-memory / index only) may expose: source id/path, semantic type, size, created_at, for a “Clear preview cache” UI.

### Serialization

Requirements:

- Round-trip enough data for `GeoVizEngine.render` (or equivalent host path) without re-reading the source DAT.
- Stay within the same **local preview bounds** already enforced by prepare (e.g. ≤50k points, ≤256×256 grids).
- Versioned; unknown `payload_schema_version` → treat as miss and rebuild.

Suggested v1:

- `meta.json`: key fields, schema version, `preview_kind`, capabilities summary, `estimated_bytes`.
- `payload.npz` (NumPy) or a small JSON header + binary arrays for XY / grid / tops columns.

Do **not** pickle Qt objects or full engine internals.

### Threading

| Work | Thread |
|------|--------|
| Stat source, read/write cache files, deserialize, `prepare` | Worker |
| Create/reuse widget, `engine.render`, stack switch | UI |
| Update in-memory LRU after disk hit | UI coordinator (same as today’s cache write path) |

Disk cache **complements** the existing in-memory LRU:

1. Memory hit → no worker needed (current behavior).
2. Memory miss → worker: disk hit → deserialize → emit result.
3. Disk miss → worker: prepare → write disk → emit result.

### Invalidation and cleanup

**Automatic**

- Source `mtime`/`size` mismatch → miss.
- Options fingerprint or schema version mismatch → miss (orphan entry may be deleted opportunistically).

**Manual**

- Action: **Clear preview cache** (project menu or data-page utility): delete `.preview_cache/` contents and clear matching in-memory entries.
- Optional later: cap total disk bytes (LRU by `created_at` / last access); not required for v1 if a clear action exists.

### Integration points

| Module | Change |
|--------|--------|
| `preview_worker.py` | For cacheable types, attempt disk load before `provider.preview`; after successful prepare, write disk entry |
| New `preview_disk_cache.py` | Keying, paths, read/write, clear, corruption handling |
| `geoviz_preview_provider.py` | Unchanged prepare API; may expose helpers to classify cacheable semantic types |
| Project open/close | Resolve `project_root`; on close, clear is optional (files remain on disk) |
| Data page / menu | “清除预览缓存” action |

LAS/SGY code paths must not call disk cache write/read in v1.

## Error handling

| Condition | Behavior |
|-----------|----------|
| Corrupt `meta.json` / payload | Treat as miss; delete entry if safe; live prepare |
| Disk full / write failure | Log/warning; still emit live prepare result (preview must work offline-cache-failed) |
| Project root unknown (no open project) | Skip disk cache; memory-only (current behavior) |
| Partial write | Write to temp file then atomic replace; never leave half-written as valid hit |

## Testing

1. **Hit:** prepare horizon once, second select with same mtime/size → provider/`GeoVizEngine.prepare` not called (mock), result still renders.
2. **Invalidate:** touch/rewrite source → next select prepares again and overwrites entry.
3. **Isolation:** LAS/SGY selects never create `.preview_cache` entries for those types.
4. **Clear:** clear action removes entries; next select is a miss.
5. **Concurrency:** rapid A/B/C selection still latest-only; stale generation must not write over a newer key’s UI (disk write for stale gen may be skipped or key-scoped only).
6. **Corruption:** truncated payload → miss + successful live prepare.
7. **No project root:** cacheable type still previews via live prepare.

## Success criteria

- Re-selecting an unchanged horizon / well-stratification / well-head resource is faster and does not re-parse the full DAT when a valid cache entry exists.
- Seismic and well-log previews remain interactive and match current behavior.
- UI thread does not perform DAT parse or cache file I/O for these paths.
- Users can clear project preview cache without breaking the project document.

## Implementation sketch (for planning)

1. Add `preview_disk_cache.py` + unit tests (key, atomic write, corrupt miss).
2. Wire cacheable types into `PreviewRequestController` worker path.
3. Wire project root resolution + clear action.
4. Integration tests with real small DAT fixtures and mocked `prepare` call counts.
5. Document `.preview_cache/` in progress notes / user-facing cleanup label.

## Open follow-ups (explicitly deferred)

- Add `time_depth` to the cacheable set.
- Disk budget LRU and access-time tracking.
- Optional list thumbnails (`thumb.png`).
- Sharing cache across machines (not planned).
