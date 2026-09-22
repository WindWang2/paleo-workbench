# App install seams — `paleo_workbench_platform`

**Baseline**: `470d7500`.
**Host**: `apps/paleo_workbench_platform` (`pwb_platform` binary).

Install seams are the **composition root** for a feature slice: they bind already-built library services into the shell/window. They must not invent a second catalog, stage, or command authority.

## Index

| Stem | Role | Primary header/source | Summary (from file banner) |
| --- | --- | --- | --- |
| `closure_catalog_install` | Closure vertical | `closure_catalog_install.hpp` | Production INSTALLER: binds the concrete adapter into CatalogRuntimeApi for ProjectControllerCore; exposes 04/09 handles. |
| `closure_joint3d_install` | Closure vertical | `closure_joint3d_install.hpp` | Product data-plane binder for the joint 3D host (volume + well-head / TD catalog → VizCJointHost). |
| `closure_mapping_install` | Closure vertical | `closure_mapping_install.hpp` | Product install for 数据制备 + 编图编辑 + 组合文档 (honest skip when UI targets absent). |
| `closure_preview_install` | Closure vertical | `closure_preview_install.hpp` | Unified data page, parse-registry base seam, and preview-dispatch closure. |
| `closure_review_install` | Closure vertical | `closure_review_install.hpp` | 审核治理 / 可验证发布 closure: binds real IReviewActions onto the review page. |
| `closure_seismic_install` | Closure vertical | `closure_seismic_install.hpp` | Product binding between SeismicPredictionPage and the real seismic display stack. |
| `joint_analysis_install` | Well / joint host | `joint_analysis_install.hpp` | Joint page analysis hooks → real kernels (stratal / welltie / facies / export). |
| `m5_compose_install` | Workspace / viz page | `m5_compose_install.hpp` | ws3 layout compose panel + contextual ribbon groups. |
| `m5_data_install` | Workspace / viz page | `m5_data_install.hpp` | Data workspace lineage/history inspector install. |
| `m5_validation_install` | Workspace / viz page | `m5_validation_install.hpp` | Validation workspace comparison + review disposition install. |
| `ribbon_command_install` | Ribbon / commands | `ribbon_command_install.hpp` | 58 ribbon placeholder ids → real CommandRegistry commands (see ribbon-command-catalog.md). |
| `stage_flow_install` | Stage flow | `stage_flow_install.cpp` | Three-stage workbench install; one composition point, no second authorities. |
| `viz_a_install` | Workspace / viz page | `viz_a_install.hpp` | WLE LAS preview provider + well-log menu wiring. |
| `viz_d_seismic_install` | Workspace / viz page | `viz_d_seismic_install.hpp` | Advanced seismic display affordances for the 地震 dock. |
| `viz_e_install` | Workspace / viz page | `viz_e_install.hpp` | Data/preview page assembly (asset select → load → preview/export). |
| `well_presenter_install` | Well / joint host | `well_presenter_install.hpp` | Registers well-log / time-depth ExternalPresenters into viz-e registry. |
| `workflow_install` | Workflow host | `workflow_install.hpp` | UI-14 composition-root wiring for WorkflowController + real services. |

## Reading order for new agents

1. `ribbon_command_install` — 58 ribbon ids → CommandRegistry (see [`ribbon-command-catalog.md`](ribbon-command-catalog.md)).
2. `stage_flow_install` — stage ↔ workspace projection; must not dual-write stage.
3. `workflow_install` — cross-page orchestration bag.
4. `closure_*_install` — vertical product binders (catalog / mapping / seismic / review / …).
5. `m5_*_install` + `viz_*_install` — workspace page chrome and viewers.

## Invariants

- Installers are **idempotent per window** where documented; unregister on window teardown when using process-global registries.
- Missing optional deps → **honest skip / disabled**, never a stub that pretends success.
- No Python fallback inside these seams for the native product track.
