# P2-C — Geological AI / Agent Harness

## Architecture (as built)

```
LLM / Agent runtime (external; vendor-agnostic)
      │ binds via ToolSource / ChatModel protocols (harness/llm.py — no vendor clients)
      ▼
HarnessToolSource ──► HarnessExecutor.execute(action_id, params, context)
      │ 1. spec lookup            (ActionRegistry — single authority)
      │ 2. parameter validation   (JSON-schema from ActionSpec — same object as tool schema)
      │ 3. permission gate        (risk vs context permissions; DESTRUCTIVE uninstallable)
      │ 4. required-context gate  (explicit, explainable LookupError)
      │ 5. resource admission     (governor lease from spec profile — P2-A)
      │ 6. execute                (handler over domain services OR capability provider — P2-B)
      │ 7. verify                 (ScientificValidator + MapValidationHook)
      │ 8. ActionResult           (ok/warning/fail + outputs + verification + metrics)
      ▼
Domain services: DataCatalogService(CatalogPort) / well loader+track layout /
open_volume / GeologicalMappingService / composition+export / workflow dashboard
```

## Action inventory (25 actions, coarse-grained)

| domain | actions | risk |
|---|---|---|
| workspace | list_assets, search, get_lineage, get_versions, describe_context | READ |
| well | list, open, list_curves, create_display, apply_template | READ/COMPUTE |
| seismic | open_volume, get_slice, compute_attribute | READ/COMPUTE |
| map | create_factor_map, create_well_location_map, add_layer, set_style, apply_template, add_component, validate, export (8) | READ/COMPUTE/WRITE |
| geology | list_horizons, list_faults, create_interpretation | READ/WRITE |
| workflow | status | READ |

`ActionSpec.tool_schema()` derives OpenAI/Gemini function schemas 1:1 — single source
(no hand-written prompt schema anywhere).

Review-round hardening: default permissions are READ+COMPUTE (from_app grants WRITE
for app sessions); export/volume paths confined to the workspace with no-overwrite;
invalid maps FAIL export instead of success-shaped refusal; factor-map grids are
scientifically validated BEFORE any catalog commit, which now registers a DataRun +
INTERMEDIATE grid artifact and returns the version identity; attribute providers
probe output validity before registering derived stores.

## Security boundaries (04-security-boundaries.md for detail)

- No shell/eval/exec/arbitrary-SQL/arbitrary-path actions exist in the registry;
  DESTRUCTIVE risk class is refused at registration.
- File reads only via typed refs resolved from context; writes only inside
  WRITE-risk handlers through domain services; every data output enters the
  catalog (register_derived / register_output) — no /tmp-only results.
- Context is read-only for agents (SelectionSnapshot copy); mutation happens
  exclusively inside actions.
- Provider execution reuses P2-B's guarded pipeline (admission + provenance).

## Verification hooks

- Scientific: all-NaN FAIL, thin-coverage/constant-field WARNING, non-ascending
  axes FAIL, grid-vs-extent mismatch FAIL, CRS mismatch FAIL, unit mismatch WARNING.
- Map: no/all-hidden/empty-visible layers FAIL, invalid/inverted extent FAIL,
  missing CRS WARNING, grid-without-ramp WARNING, composition must contain
  main_map frame (seeded automatically), missing legend/scale/north/title
  FAIL when require_components (default for export gate).

## Measured (this host)

- READ action dispatch overhead (executor + validation + admission, excluding
  business IO): median < 1 ms — budget < 10 ms PASS (test_harness_core).
- Registry lookup: 10k lookups < 200 ms total (~O(1) dict) PASS.
- E2E A–E: all green on production paths (tests/e2e/test_harness_scenarios.py).

## Known limitations

- `well.create_display` produces a display document (pure data), not a live
  widget — the UI renders it; agents never drive widgets by design.
- Interpretation creation (well/geology WRITE beyond maps) stays UI-adjacent
  until a guarded writer with draft/version semantics is justified; the
  harness exposes reads for now (honest scope).
- In-process map documents live in the ActionContext (session-scoped); project
  persistence of agent-created maps follows the existing MapDocument → project
  save path, unchanged.
