# Stage 13 — Prediction production pipeline audit

**BASE_SHA:** `0a4dc451` (local main at worktree creation)  
**GEOVIZ_SHA:** `9e152856`  
**WELLLOG_SHA:** `915076e2`  
**Worktree:** `paleo-wt-grok-prediction-production`  
**Branch:** `grok/prediction-production-pipeline-20260812`

## Component matrix

| Component | Current implementation | Production-capable? | Input | Output | Spatial? | Versioned? | DataRun? | Demo leakage risk | Gap | Proposed action |
|-----------|------------------------|---------------------|-------|--------|----------|------------|----------|-------------------|-----|-----------------|
| DemoModelProvider | Seeded synthetic regions | No | Ignored | Labels + p | No | DERIVED JSON | inference | Low if demo_only | Can be promoted today | Block promote |
| LocalAssetProvider | GR/window heuristic | No (honest flags) | All wells/seis | Regions, no XY | No | DERIVED JSON | inference | Medium if promoted | final_scientific=False | Block promote of heuristic |
| InferenceService | start/execute/materialize | Yes (pattern) | Caller list | JSON DERIVED | N/A | Yes | Yes | — | No schema resolve | Extend inputs only |
| WellLogPredictionPage | Run/Demo buttons | Gate OK | Global resolve | Task | No | Task + DERIVED | Yes | Low | No model package UX | Keep gate message |
| SeismicPredictionPage | Same as well-log | Gate OK | Global resolve | Task | No | Task + DERIVED | Yes | Low | Send→demo compile | Production compile path |
| PredictionTask | result_summary dict | Partial | refs optional | regions | No | Project field | Via link | High if mock→map | No spatial contract | Spatial result schema |
| Paleomap compiler | Fixed squares @114/22.5 | No | region labels | demo polygons | Fake | Project only | Not wired | High | Invents geometry | Separate production compiler |
| Map QC | Basic polygon presence | Partial | doc | report | — | Partial | Optional | Demo treated complete | — | Readiness honesty |
| Export | PNG/SVG/PDF figures | Partial | map widget | figure | — | — | — | Demo exportable | GIS export out of scope | Leave figures |

## Key decisions

1. **No shipped production model** — infrastructure only; scientific Run stays blocked with 未配置生产模型.
2. **Model package** = manifest + artifact validation → register Model/ModelVersion; no training.
3. **TestSpatialModelProvider** lives under `tests/fakes` only.
4. **Production paleomap** requires real polygon coordinates from prediction spatial payload; never demo squares.
5. **promote_model** refuses demo/heuristic providers and demo_only versions.
6. **Schema-driven inputs** when `input_schema` declares required asset types; empty schema falls back to legacy global resolve for heuristic compatibility.

## Scientific honesty

| State | Allowed |
|-------|---------|
| No production model | Block scientific run; allow explicit Demo |
| Heuristic result | `final_scientific_prediction=False` |
| Demo result | `demo=True`, never auto-promote |
| Empty spatial | Block production map compile |
| WELL_INTERVALS only | Block map (not polygonizable without inventing XY) |
