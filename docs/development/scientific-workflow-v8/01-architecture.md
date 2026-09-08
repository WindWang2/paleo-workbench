# V8 Scientific Workflow — Architecture & Delivery Record

Branch: `feat/scientific-workflow-v8` · Baseline: `origin/main @ d5181cb3`.
Direction C (scientific data / versions / provenance / tasks / QA / action
contracts). Directions A (UI) and B (QGIS rendering) untouched except the
two #1224 workers and additive model fields.

## What changed, by milestone

### M1/M3/M4 — scientific core honesty
| Change | File(s) |
|---|---|
| Duplicate-sample policy authority (`mean`/`first`/`error`/`keep`), applied before every consumer; raw samples stay in task params, merge accounting stamped alongside | `workflow/sample_normalization.py` (new), `workflow/factor_interpolation.py` |
| Fingerprints hash the NORMALIZED set → duplicate-bearing tasks invalidate exactly once, duplicate-free tasks stay CLEAN | `workflow/interpolation_fingerprint.py` |
| Kriging LOO scores the PRODUCTION variogram (model/range/nugget) + geometric-anisotropy frame; residual coordinates aligned to deduped unique locations (fixed pre-existing mislabel) | `workflow/interpolation_evaluation.py`, `factor_interpolation.py` |
| Constrained-IDW CV fold passes the project CRS (degree-buffer parity) | `factor_interpolation.py` |
| Recommendation fail-closed gates: unknown unit / invalid CRS / unknown constraint names disable the recommendation, metrics still reported, every entry says why | `interpolation_evaluation.py` |
| `evaluate_methods_for_task`: real per-method production-mirroring comparison (kriging=loo_exact, others=kfold) with scheme-mix caveats — replaces the IDW-proxy | `factor_interpolation.py` |
| numpy kriging fallback labeled degraded (`numpy-grid-ols` vs `engine-wls`, `r_squared=None`); publish gate warns | `mapping/geological_pipeline/interpolator.py`, `workflow/map_product.py` |
| Mixed m/ft multi-well sections resolve to one unit (target well's) with exact conversions + diagnostics; unknown-unit wells refused on ft/mixed sections (V6 labeled-m compromise kept on meter sections); external meter tops converted on foot sections | `viz/welllog_multi_well_adapter.py` |

### M2 — versioned constraints lifecycle
`workflow/constraint_versions.py` (new): explicit `commit_constraint_group`
creates ONE catalog asset per constraint group (first commit via the
sanctioned atomic `register_result_asset`, later commits append immutable
versions via `register_version`), a `constraint_commit` DataRun carries
actor/notes/line-count provenance; content hash is id-free/order-free
canonical sha (unchanged content commits nothing). Interpolation pins
per-group content hashes on the task (horizon-scoped); version binding
resolves lazily by content hash. `constraint_pins_staleness`:
current/stale_content/stale_version/unknown/unpinned per group.
`compare_constraint_versions`: line-level diff.
`resolve_constraint_ref` + `mapping_workspace/dependencies.py`:
`constraints:current` compares document vs latest commit (CLEAN/STALE/
UNKNOWN-when-never-committed); `constraints:<group>:<version>` pins check
supersession. **ADR-1**: constraints are catalog DERIVED versions (the
digitized vector layer is the RAW source, recorded via `layer_id`); the
project document stays the live editing surface — no second DB.

### M5 — fusion V8
`_fuse_weighted` streams per-factor accumulations (O(h,w) working set;
identical maths — verified by equivalence test); conflict diagnostics
(weighted class-disagreement fraction, decision margin); QC gains
low_confidence_fraction / mean+high conflict / low_margin fractions;
variance grid registers as a sibling catalog version; sensitivity computed
once (cached) instead of twice; `FusionModel.weight_provenance`
(actor/notes/policy) rides fingerprint + run parameters.

### M6 — harness coverage
`harness/actions/scientific_pipeline.py` (new): 10 actions over existing
services — `factor.interpolate` (WRITE+verifier), `factor.polygonize`,
`factor.compare_versions`, `constraint.validate`, `constraint.commit`
(WRITE+verifier), `fusion.run` (COMPUTE+verifier),
`compilation.validate_inputs`, `map_product.qa`, `map_product.freeze`
(WRITE+verifier). Verifier count 1 → 5. `factor.evaluate_methods` upgraded
to the real per-method evaluation. Declared-but-unused `supports_cancel`
on `map.create_factor_map` / `seismic.compute_attribute` now checks the
token at admission + pre-registration.

### M7 — DAG productionization
`WorkflowRunStore` cache index (`cache_identity → [(run_id, node_id)]`,
built once, maintained on save): lookups deserialize only candidates,
newest-first — replacing the full-history JSON rescan per cacheable node.
Index is a lookup aid only; full reuse contract re-validated per candidate.
`WorkflowRun.parent_run_id` + `run_lineage` walk rerun chains (cycle-guarded).

### M8 — cancellation (#1224 remainder)
`VizAdapter.resolve(cancel=)` → `load_well_log_from_path(cancel=)` with
checkpoints before the parse and between parse/unit-inspect; typed
`WellLogLoadCancelled` never converted to a soft-fail message.
`WellLogLoadWorker`: mid-parse cancel emits the new `cancelling` signal
(honest "ending now — parse cannot stop"), late results discarded,
before-parse cancels release the slot without the parse. MapExportWorker
was already fixed (79e89ec0). **ADR-2**: the engine's single-call LAS/XML
parse is non-interruptible by design; the contract is honest phases +
discard, never a fake mid-parse abort.

### M9 — data runtime
`db.get_asset_models` (IN-chunked) + `resolve_asset_models` batch path kill
the lazy-search N+1. `catalog/telemetry.py` (new): durable append-only
JSONL events (`gc.sweep`, `working_copy.recovery` with healed counts) under
`<project>.artifacts/catalog/events.jsonl` — best-effort, never an authority.

### M10/M11 — provenance + QA honesty
`workflow/provenance_graph.py` (new): `build_product_lifecycle_graph` —
pure-data product→task→version→constraint-pin→fusion narrative with
recorded gaps. `QualityReport.rule_status`/`coverage`: per-rule
evaluated/skipped+reason (out_of_bound_feature needs extent,
low_confidence needs fusion data, export_fallback needs an export report);
publish gate warns on skipped rules and fallback-kriging factors.

### M12 — perf matrix
`tests/perf/test_v8_goal_perf.py`: kNN IDW 10k/50k/100k × 500×500; fusion
500×500×5/×50 with a structural no-(n,h,w)-stacks gate; DAG identity
digests 50/100 nodes; constraint hashing 20×25 lines; unchanged-commit
no-op; normalization at 100k samples.

## Definition-of-Done mapping
1. overlap audit → `00-overlap-audit.md` (done pre-implementation)
2. constraints lifecycle → M2 + ADR-1
3. factor algorithm honesty → M1/M3/M4
4. scientific actions + verifiers → M6
5. DAG O(N)/stale/cancellation honesty → M7/M8
6. RAW→MapProduct provenance → M10 (+ M2 chain)
7. 100k metadata / 500×500 budgets → M9/M12 (+ existing v6 scale suites)
8. no 100GB seismic → none added (explicit exclusion)
9. tests + 3 review rounds → `02-verification.md`, `04-review-rounds.md`
10. V8-only increment → `00-overlap-audit.md` dispositions
