# Stage 12 — Stratigraphic Interpretation Audit Matrix

**BASE_SHA:** `e92f81d14f92eb379cbf215613ba6c26d4ada156`
**GEOVIZ_SHA:** `9e152856f0c2ffede37e718f62897e98a45735be`
**WELLLOG_SHA:** `915076e22165b4652ab2c51b32bfdb0f0c050992`

| Object | Authority today | Representation | Scientific? | Mutable? | Persisted? | Versioned? | DataRun? | Domain | Consumers | Gap |
|--------|-----------------|----------------|-------------|----------|------------|------------|----------|--------|-----------|-----|
| FormationTop | well_tops_parser.WellTop / load_well_tops dict | well_name, top_name, md[, tvd] | yes | file edit | well_stratification files | no | no | MD (+optional TVD) | correlation UI | no project-side versioned tops product |
| CorrelationLink | geoviz/UI session | often screen/engine objects | yes when linked tops | session | partial/export only | no | no | inherits tops | canvas | no stable top IDs / version |
| CorrelationResult | page session | runtime | mixed | yes | no scientific DERIVED | no | no | MD assumed | UI | need versioned interpretation |
| HorizonInterpretation | Stage-8 HorizonInterpretationRef | npz + catalog | yes | draft only | yes | yes | horizon_interpretation | time/depth string | 3D, factor optional | reuse pattern |
| FaultInterpretation | ConstraintLine role=break | polyline XY | partial | project constraints | yes as constraints | no | no | map plane | factor IDW | need versioned fault interp |
| CorrelationSession | UI | viewport/exaggeration | display | yes | no | no | no | — | UI | keep display-only |
| WellSection | joint/fence | runtime | display | yes | joint state partial | no | no | Time/Depth | joint page | not correlation product |
| 3D Horizon | scene | runtime / horizon artifact | if from version | scene | via horizon version | yes if Stage-8 | yes | vertical_domain | geomodel | consume current_version |
| 3D Fault | demo/synthetic often | mesh/polylines | often demo | yes | weak | no | modeling demo | — | 3D page | mark DEMO; version real polylines |

## Decision for Stage 12

1. Add **CorrelationInterpretation** lifecycle (JSON artifact, DERIVED, DataRun `stratigraphic_correlation`).
2. Add **FaultInterpretation** lifecycle for scientific XY polylines (not constraint display alone).
3. Reuse HorizonInterpretationRef pattern for identity/current_version/fingerprint.
4. Wire Stage-9 current context + Stage-11 contracts honesty.
5. No new DTW/AI; method provenance MANUAL / DTW_ASSISTED when helpers used.
