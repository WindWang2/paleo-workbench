# Stage 11 — Professional Workflow Audit Matrix

**BASE_SHA:** `66c785ea650e73f74496cc634193b1cd5a036500`
**GEOVIZ_SHA:** `9e152856f0c2ffede37e718f62897e98a45735be`
**WELLLOG_SHA:** `915076e22165b4652ab2c51b32bfdb0f0c050992`

Evidence-based matrix (actual code). Certainty: KNOWN_FROM_CODE unless noted.

| Module | Entry point | Input representation | Operation | Output | DataRun op | DataStage | QC | Downstream | Demo path | Contract gap | Expert questions |
|--------|-------------|----------------------|-----------|--------|------------|-----------|-----|------------|-----------|--------------|------------------|
| data_import / data_check | `ui.pages.data_page`, `catalog.lifecycle.register_resource_input` | `ResourceItem` list; types well_log/seismic/horizon | Import / classify / register RAW | Managed/external RAW version | (none on import; bridge via register_input) | RAW | file present / checksum optional | all workflow modules | sample project resources | readiness rules scattered | depth domain of mixed wells? |
| well_log_ingest | LAS parser providers, data import | LAS path → `ResourceItem(type=well_log)` | Parse header + curves | RAW well_log resource | — | RAW | format accept | visualization, correlation, factor samples | mock curves in demo projects | native engine vs legacy path dual | MD/TVDSS requirement before multi-well? |
| well_log_visualization | `ui.pages.well_log_*`, well-log-engine multi-track | well_log resource ids | Track/curve display | Display state (not versioned) | — | — | — | correlation | demo wells | track style vs scientific | which curves are mandatory for facies? |
| well_correlation | `workflow.stratigraphy_correlation` | `input_refs` wells | DTW / tops correlation | tops / correlation result in project | partial | DERIVED if registered | well_qc | stratigraphy binding | mock tops | incomplete lineage | unified depth datum? |
| seismic_volume | `viz.seismic_volume_source`, SEG-Y import | seismic ResourceItem | Lazy volume open + LOD | Runtime volume access (not every slice versioned) | — | RAW source | geometry/sample interval | interpretation, 3D, prediction | synthetic volume paths | slice display ≠ artifact | time vs depth domain velocity model? |
| horizon_interpretation | `viz.interpretation_lifecycle` | seismic/source versions + draft | draft → save version | `.horizon_interp.npz` + DERIVED | `horizon_interpretation` | DERIVED | fingerprint | factor_map, 3D | seed array drafts | fault versioning weaker | multi-interpreter merge rules? |
| fault_interpretation | constraint lines role=break; limited fault modules | polylines in ConstraintLayers | edit constraints | constraint geometry in project | often none | intermediate project state | topology partial | factor constraints | mock faults | not full versioned lifecycle | fault throw required for maps? |
| factor_interpolation | `workflow.factor_interpolation`, prepare scheduler | sample_points, target_horizon, constraints, method | IDW/kriging/constrained IDW | FactorGrid NPZ INTERMEDIATE | `factor_map` | INTERMEDIATE | quality_metrics, fingerprints | prediction, paleomap | source_kind=mock common | horizon version now in inputs if project passed | geological factor definition catalog? |
| facies_prediction | `prediction.adapters` Mock/Local | `input_factor_map_ids`, `input_refs` wells/seismic | mock or local adapter | result_summary in task; optional DERIVED file | `prediction` | DERIVED | evidence panels | map_compile, export | **Mock default** | model registry optional | production model acceptance criteria? |
| paleomap_compile | `pipeline.compile_map`, mapping page | paleomap document, factors/prediction | compile draft / map authoring | PaleoMapDocument | `map_compile` (helper; not always called) | DERIVED if registered | `workflow.qc` | QC, export | demo paleomap seed | lineage often missing | facies polygon ontology? |
| quality_control | `workflow.qc.run_basic_qc` | map document | rule checklist | QualityReport | `qc` helper | OUTPUT if path | BASIC_QC_RULES | export gate | warns empty polygons | geological completeness rules soft | which QC are HARD_GATE? |
| export | `project.artifacts.record_export`, lifecycle export | linked_id + source_task_ids | write file + register OUTPUT | ExportArtifact | `export` | OUTPUT | file checksum | delivery | any format string | source completeness | archival package standard? |
| well_seismic_joint | joint_host, fence | seismic + wells | joint 3D progressive | runtime scene | modeling optional | — | — | interpretation | demo/synthetic scenes | production honesty | registration residual tolerance? |
| geomodel_3d | geological_modeling_* | mixed | workers | demo or DERIVED | `modeling` | DERIVED optional | demo flag in params | viz | **synthetic/demo** common | must not claim production | when is model “validated”? |

## Key findings

1. Stage-9 `DataRun.operation` values: `factor_map`, `prediction`, `export`, `horizon_interpretation`, `map_compile`, `qc`, `modeling`.
2. Prediction defaults to `adapter_kind="mock"` — implementation_status must be DEMO/PARTIAL, not PRODUCTION.
3. Slices/tracks/viewports are display — not DataVersions.
4. Readiness must use project metadata only (resource counts, task fields, paths present) — no SEG-Y/LAS bulk load.
5. Do not invent geological thresholds; mark EXPERT_CONFIRMATION_REQUIRED with specific questions.
