# V8 Known Limitations & ADRs

## ADR-1 — Constraints are catalog DERIVED versions; the document is the editing surface
Decision: one catalog asset per `ConstraintLayers` group; each explicit
commit appends an immutable DERIVED DataVersion (JSON payload of the
canonical group content) + a `constraint_commit` DataRun. The project
document keeps the live authoritative geometry; content hashes bridge the
two (id-free, order-free).
Alternatives rejected: (a) full catalog-as-authority for edits (would move
QGIS edit-session handling into the catalog — Direction B territory and a
second write path); (b) fingerprints-only (pre-V8: no version identity, no
comparability, `constraints:current` permanently UNKNOWN).

## ADR-2 — Honest non-interruptible parse phases (#1224)
The engine's LAS/XML parse is a single native/lasio call that cannot stop
mid-file. V8 makes the contract honest instead of faking: cooperative
checkpoints before the parse and between phases; mid-parse cancellation
surfaces as `cancelling` ("ending now") + guaranteed late-result discard.
A true mid-parse abort needs engine-side chunked reading (geo-viz-engine
submodule — deferred; would require a submodule bump affecting parallel
directions).

## ADR-3 — Duplicate policy default is `mean`
Kriging (engine) and CV scoring already collapse duplicates to the mean;
`mean` makes plain IDW and constrained-IDW consistent with that single
scientific convention. `first`/`error`/`keep` remain selectable per task;
`keep` is the exact pre-V8 behaviour escape hatch.

## ADR-4 — DAG cache index is a lookup aid, not an authority
The in-memory index answers "which runs COULD satisfy this identity"; every
candidate is re-loaded from disk and re-validated (terminal state,
succeeded, not from_cache, outputs resolvable + integrity-verified). The
catalog/document remain the only truths; a stale index can only cost a
miss, never a wrong hit.

## Known limitations
1. **Kriging barriers remain unsupported** (deliberate): no scientifically
   defensible barrier-aware ordinary kriging is implemented; the capability
   matrix reports `unsupported` and the publish gate warns. Fake penalty
   methods were explicitly rejected (goal M3).
2. **Engine-internal LOO r² (`result["r_squared"]`) still uses default-fit
   LOO** inside `interpolate_factor_grid`; the CV path (`attach_cross_validation`
   / `cross_validate_factor_task`) is fully production-mirrored. Fixing the
   in-result value needs a geo-viz-engine change (submodule bump — deferred).
3. **numpy kriging fallback fits a grid-OLS variogram** (not the engine's
   weighted WLS): now labeled `degraded` + `variogram_fit: numpy-grid-ols`,
   `r_squared=None`, publish warning. Full parity would duplicate the engine
   authority in numpy — rejected.
4. **`cancelling` UI hint is a signal without a listener yet** — Direction A
   wires the panel text; the worker-side contract is tested.
5. **Version-id pins for constraints are hash-addressed lazily** (pins carry
   content hashes; binding resolves at evaluation) — deliberate, since
   interpolation time has no catalog handle. If two commits ever shared a
   content hash they are byte-identical states by construction.
6. **100GB seismic exclusion** honored: no seismic-payload benchmarks, caches
   or reads were added anywhere in V8.
7. **`constraint.commit` for integrated-boundary constraints** follows the
   same group lifecycle; whether integrated boundaries should version
   independently of factor constraints is a Direction A/B UX decision —
   the data model supports both.
