# Module map (deep) — per-library inventory

**Baseline**: `470d7500`. Companion to [`module-map.md`](module-map.md).
**Method**: `libs/*/CMakeLists.txt` first `#` comment + Qt link presence.
Total libraries: **63**.

| Library | Qt | CMake one-liner |
| --- | --- | --- |
| `algorithms` | Qt-free | pwb::science algorithm SDK (interface handshake v1 owner). |
| `application` | Qt-free | B/C integration adapters: only when the real modules are in the build |
| `cartography` | Qt-free | CPP cartography — CONV-27: Qt-free style/template/symbol/ramp registry |
| `catalog` | Qt-free | pwb_catalog — canonical catalog.sqlite repository. |
| `closure_agent` | Qt-free | PUBLIC: headers expose pwb::providers types (CancelToken, TypedInp…) |
| `closure_review` | Qt-free | closure_review (line 09) — the review/publish governance closure |
| `closure_science` | Qt | Line-03 closure_science — science/prediction product loop adapter |
| `closure_workflow` | Qt-free | cpp-close-02 — workflow orchestration / versioning / recompute closure |
| `data_suite` | Qt-free | data_suite — standalone build entry for the CPP-B data kernel |
| `domain` | Qt-free | pwb_domain — strong ids, stage vocabulary, errors, JSON conventions |
| `factor_fusion` | Qt-free | CONV-24 — factor_fusion + factor_units pure kernel |
| `factor_host` | Qt-free | CONV-08 factor_host — interpolation fingerprint / evaluation / plan |
| `geo3d_viz` | Qt | pwb::geo3d_viz — CONV-GEO3D native 3D geomodel viewer |
| `geomodel` | Qt-free | CONV-12 geomodel — volume / thickness / section geometric kernels |
| `ingest` | Qt-free | CONV-19 libs/ingest — resource scan / well tops / well location XML |
| `interchange` | Qt-free | CONV-14: interchange path-safety + package manifest + preflight |
| `job_runtime` | Qt | CONV-30 — job runtime: bounded scheduler core + Qt queued |
| `layout_export` | Qt-free | CONV-29 — Qt-free layout-export behavior kernel |
| `mapping_bind` | Qt-free | CONV-20: optional pybind11 facade over Qt-free mapping kernel |
| `mapping_document` | Qt-free | CONV-02 — Qt-free MapDocument / MapCompositionDocument JSON kernel |
| `mapping_kernel` | Qt-free | CPP mapping_kernel — contouring + interpolator + polygonization |
| `platform_services` | Qt | Platform services — settings / theme tokens / diagnostics / resources |
| `prediction` | Qt-free | CPP prediction — tiled ONNX inference geometry |
| `project` | Qt-free | pwb_project — .paleo.json compatibility (schema parity, atomic IO) |
| `providers` | Qt-free | CONV-PROVIDERS — provider/plugin/tool runtime |
| `qgis` | Qt-free | BEGIN V14-QGIS-CONTROL |
| `science_service` | Qt-free | CONV-28 science_service — native science service layer |
| `science_suite` | Qt | Paleo Workbench science suite — C-line standalone entry |
| `seismic_attributes` | Qt-free | pwb::seismic_attributes — ten production seismic attribute kernels |
| `seismic_io` | Qt-free | CPP seismic_io — native seismic volume IO |
| `seismic_service` | Qt-free | pwb::seismic_service — native seismic volume service |
| `seismic_viewer` | Qt | pwb::seismic_viewer — D-line embeddable 2-D seismic slice viewer |
| `tool_policy` | Qt-free | Deliberately dependency-free Qt-free policy core |
| `ui` | Qt | BEGIN CONV-27 |
| `ui_canvas` | Qt | UI-15 — root-canvas slice |
| `ui_composite` | Qt | UI-13 — workstation-composite |
| `ui_controllers` | Qt | UI-14 — root-controller slice |
| `ui_data_core` | Qt | UI-03 — core-data-preview |
| `ui_map` | Qt | UI-05 — qgs-map slice |
| `ui_pages_data` | Qt | UI-06 — data/home page library |
| `ui_pages_mapedit` | Qt | UI-08 — qt-mapedit slice |
| `ui_pages_preview` | Qt | UI-07 — preview pages cluster |
| `ui_review` | Qt | UI-11 — qt-review-gov slice |
| `ui_ribbon` | Qt | UI-18 — Ribbon five-workspaces chrome |
| `ui_seqviz` | Qt | UI-10 — sequence/factor/visualization pages |
| `ui_shell` | Qt | UI-01 — UI shell substrate |
| `ui_stageflow` | Qt | V14-THREE-STAGE-UX — stage presentation projection |
| `ui_visualqa` | Qt | UI-16 — visual-QA slice |
| `ui_wellseis` | Qt | UI-09 — qt-well-seismic slice |
| `ui_widgets` | Qt | UI-02 — design-system components + model/view |
| `ui_workers` | Qt-free | UI-04 — core page-worker ports |
| `ui_workstation` | Qt | UI-12 — workstation shell |
| `visualization` | Qt-free | pwb::visualization core |
| `viz_charts` | Qt | VIZ-E — geoviz plots C++ port |
| `well_science` | Qt-free | CPP well_science — DTW well-log matcher kernel |
| `workflow` | Qt-free | pwb::workflow minimal task runtime |
| `workflow_contracts` | Qt-free | CONV-23 — workflow/contracts pure contract layer |
| `workflow_engine` | Qt-free | CPP workflow_engine — in-memory DAG executor |
| `workflow_graph` | Qt-free | CONV-25 — workflow dependency graph + evidence selectors |
| `workflow_interpretation` | Qt-free | CONV-32 — workflow interpretation domain spine |
| `workflow_runtime` | Qt-free | CONV-26 — workflow runtime closure |
| `workflow_spec` | Qt-free | CONV-06 — WorkflowSpec DAG pure model + validator |
| `workspace` | Qt-free | pwb_workspace — stage/membership/binding state codec |

## Re-verify

```bash
ls libs | wc -l   # 63
rg -l 'Qt6|Qt::' libs/*/CMakeLists.txt | wc -l
```
