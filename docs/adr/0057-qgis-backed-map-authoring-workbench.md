# ADR 0057: QGIS-backed map authoring workbench

## Status

Accepted for the optional native rendering path.

## Decision

The 2-D map authoring workspace has one primary `UnifiedMapCanvas`.  It consumes an
immutable `MapRenderSnapshot` through `MapRenderBackend`; `MappingPage` does not own a
second feature painter or a renderer-specific QGIS API surface.

When `PALEO_WITH_QGIS_RENDERER` is built and the runtime bridge is available, the
canvas uses `QgisMapRenderBackend` and `native/qgis_render_bridge`. The bridge builds
the fixed in-tree QGIS source snapshot, owns QGIS process initialization, memory
vector/raster render mirrors, render jobs, cancellation, generation rejection, and
synchronous export frames. The PySide6 host receives only owned RGBA frames and a
narrow status/metrics API. It never imports QGIS Python or PyQt GUI objects.

`FallbackMapRenderBackend` remains an explicit test/minimal-runtime option.  Its status
is visibly `fallback`; it is never reported as QGIS rendering.

## Authority and lifecycle

`ProjectDocument`, managed catalog artifacts, `LayerRegistry`, and
`MapAuthoringDocument` own semantic state.  `VectorLayer` plus `VectorEditSession`
hold committed and buffered geometries, attributes, selection IDs, undo/redo, and
audit history.  QGIS `QgsVectorLayer`/`QgsRasterLayer` objects are revision-keyed render
mirrors only.

Finished `FactorGridResult` instances remain scientific contracts.  A scalar grid is
transferred to the existing native `ScalarGridLayer`; the bridge creates a temporary,
revision-keyed GeoTIFF mirror from that raster cache when QGIS needs one.  Pan, zoom,
style, visibility, order, labels, selection, and export never call interpolation.

Raw imported resources are not opened for in-place edit.  Map authoring layers use
`map-working:` source references and save the managed working document/version state.

## Licensing and provenance

QGIS 4.2.0 vector/edit/render source is an owned, fixed source dependency under
`third_party/qgis`. Its immutable upstream tag, commit, archive checksum, component
closure and the four build-only CMake omissions are recorded in
`third_party/qgis/UPSTREAM.md`; upstream copyright notices and `COPYING` are retained.
The combined work is distributed under GPL-2.0-or-later, recorded by the repository
root `LICENSE`. The bridge never discovers or uses an externally installed QGIS
prefix/library.

## Consequences

The former `MapEditScene`/`MapEditView` and `NativeMapCanvas` remain compatibility
adapters for opening legacy documents and legacy callers.  They are not the normal
authoring surface once a map document is active.  Interactive selection, rubber bands,
vertex markers, snap feedback, and measurements are lightweight Qt overlays, avoiding
full QGIS renders for every mouse move.
