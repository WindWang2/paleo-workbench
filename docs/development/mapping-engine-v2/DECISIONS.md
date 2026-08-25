# Mapping Engine 2.0 & Geological Mapping Pipeline — Architectural Decisions

## ADR-01: Layer & Renderer Separation (Protocol + Registry)
- **Context**: The existing mapping engine hardcoded rendering inside `FallbackMapRenderBackend` and `MapComposerRenderer` with `if/elif layer_type` branching.
- **Decision**: Introduce explicit `MapLayer` and `LayerRenderer` protocols with a thread-safe `RendererRegistry`. This allows adding new layer types (e.g. `GridLayer`, `ContourLayer`, `GeologicalFactorLayer`) without modifying backend core loops.
- **Consequences**: Backwards compatibility is preserved by wrapping legacy `MapLayerSnapshot` into the registry.

## ADR-02: Map Document Model Unification
- **Context**: Three fragmented documents existed (`PaleoMapDocument`, `MapAuthoringDocument`, `MapCompositionDocument`).
- **Decision**: Define a unified `MapDocument` in the mapping engine that represents layers, order, extent, CRS, layout, and cartographic elements, bridging to both live interactive canvas and composer layout/export.

## ADR-03: GIS Layer Output for Geological Factors
- **Context**: Factor interpolation previously produced plot figures or isolated arrays.
- **Decision**: The geological mapping pipeline produces first-class GIS layers (`GridLayer`, `ContourLayer`, `WellPointLayer`, `PolygonLayer`) attached to a `MapDocument`.
