# ADR 0057: QGIS-backed map authoring workbench

## Status

Accepted for the optional native rendering path.

## Decision

The 2-D map authoring workspace has one primary `UnifiedMapCanvas`.  It consumes an
immutable `MapRenderSnapshot` through `MapRenderBackend`; `MappingPage` does not own a
second feature painter or a renderer-specific QGIS API surface.

When `PALEO_WITH_QGIS_RENDERER` is built and the runtime bridge is available, the
canvas uses `QgisMapRenderBackend` and the independently written
`native/qgis_render_bridge` C++ extension.  The bridge owns QGIS process
initialization, memory vector/raster render mirrors, render jobs, cancellation,
generation rejection, and synchronous export frames.  The PySide6 host receives only
owned RGBA frames and a narrow status/metrics API.  It never imports QGIS Python or
PyQt GUI objects.

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

QGIS is an optional external runtime dependency.  This repository does not vendor or
copy QGIS source files or QGIS artwork.  The bridge is independently implemented
against public QGIS C++ APIs and isolates the dependency in `native/qgis_render_bridge`.
Any future direct QGIS source reuse requires a separate licensing/provenance review,
copyright notices, and an explicit repository licensing decision.

## Consequences

The former `MapEditScene`/`MapEditView` and `NativeMapCanvas` remain compatibility
adapters for opening legacy documents and legacy callers.  They are not the normal
authoring surface once a map document is active.  Interactive selection, rubber bands,
vertex markers, snap feedback, and measurements are lightweight Qt overlays, avoiding
full QGIS renders for every mouse move.
