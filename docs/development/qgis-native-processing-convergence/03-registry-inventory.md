# 03 — registry inventory (before)

Seven coexisting "registries"; four independent execution tracks to science kernels.

## Registries

1. `pwb::science::AlgorithmRegistry` (libs/algorithms) — runtime container, `<domain>.<name>` ids validated; populated by seismic_attributes (10), coherence_c3, science_service adapters (10). Consumer: `pwb::workflow::TaskRuntime` + two TU-static instances.
2. `AlgorithmRunner::kernels_` (libs/application) — its own map, id format NOT validated; product entry for 11 seismic kernels (app_context.cpp:47-91).
3. `workflow_interpretation` static AlgorithmSpec table — 9 interpolation specs, **zero consumers outside its own tests**; UI keeps two divergent hardcoded method lists (page_tokens.hpp:36 ×5, factor_state.cpp:251 ×2).
4. `ui_shell::OperationRegistry` — presentation-layer op records (NOT algorithm discovery); TaskCenter projection merges it with JobSnapshot.
5. `workflow_contracts::WorkflowContractRegistry` — 14 workflow contracts (frozen JSON; domain vocabulary, not algorithms) — out of scope here.
6. `closure_agent::ActionRegistry` — harness actions; unassembled in product.
7. `providers::ProviderRegistry` — 2 builtin providers (factor_stats, map_thumbnail) + ONNX closure_science providers.

Plus `workflow_engine` NodeRegistry op ids (`map.*` — inconsistent with `mapping.*`).

## Execution tracks (before)

- **A** GUI seismic attributes: menu → AlgorithmRunner → TaskRuntime → IAlgorithm (catalog publish, cancel, provenance).
- **B** TU-static direct `algorithm->run()`: section panel (closure_seismic_install.cpp:62-94) + crossplot (seismic_viewer/crossplot_core.cpp) — no publish/cancel/provenance.
- **C** raw kernel calls: factor map pipeline (`run_map_pipeline`), factor prepare (WorkerHost + ui_workers), workflow ops — bypass IAlgorithm entirely.
- **D** Agent: HarnessExecutor → providers (unassembled).

## id chaos (representative)

Same interpolation capability appears as `mapping.factor_interpolate` (A), `idw`/`kriging` (B-reg), `map.interpolate_idw` (engine op), `"idw"` (FactorGrid.algorithm_id stamp). Prefixes: `seismic.*`, `mapping.*`, `well.*`, `geomodel.*`, `factor.fuse`, `map.*`, bare names, UI short names.

## After (this convergence)

`QgsProcessingRegistry` (provider id `paleo`) becomes the single authority for algorithm existence/metadata/parameter schema; algorithm ids are `paleo:<snake_name>`. Legacy registries: 2 (AlgorithmRegistry container remains as kernel-level SDK inside algorithm impls — not a discovery authority), 3 retired into provider metadata, AlgorithmRunner delegates by id.

## After (as built)

- Single discovery authority: `QgsProcessingRegistry` provider `paleo` — 31 algorithms (interpolation ×5, mapping ×6 incl. CONV-04-gated clip/repair, factor ×3, seismic ×11, well ×3, cartography ×1, project ×2; constrained IDW additionally CONV-05-gated).
- `AlgorithmRunner` delegates by id (`seismic.X` → `paleo:seismic_X` via `to_paleo_algorithm_id`); `kernels_` map deleted; TU-static registries deleted (section panel + crossplot resolve via `algorithm_exec.cpp` factory table, the execution mirror of the registry's seismic family); `workflow_interpretation` spec table still exists (zero consumers, unchanged — retirement tracked separately).
- Workflow node op ids bridge to paleo ids: `map.extract_factors` → `paleo:extract_factors`, `map.interpolate_idw` → `paleo:interpolation_idw` (same kernels; see 02 for the staging decision).
- Agent: `closure_agent::processing_algorithm_specs(AlgorithmToolInfo...)` + apps `processing_install.{hpp,cpp}` (`paleo_processing_tool_infos()` / `register_paleo_agent_actions()`) — the GIS tool inventory source is the registry.
- Capabilities/diagnostics/bootstraps enumerate `paleo_algorithm_ids()`.
