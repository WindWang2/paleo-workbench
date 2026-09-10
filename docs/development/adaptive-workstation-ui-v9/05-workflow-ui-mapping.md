# 05 — Workflow → UI Mapping (V9)

## Surface consistency model (V7/V8 base, unchanged and re-verified)

All command surfaces consume the SAME availability source:

```
domain authority (mapping_workspace stages/readiness, edit sessions, layer state)
        ↓
tool_surface.evaluate_tool(tool_id, ToolContext)  — single evaluator
        ↓
┌─────────────┬──────────────┬───────────────┬────────────────┐
│ canvas toolbar │ command palette │ context menus │ stage panel │
└─────────────┴──────────────┴───────────────┴────────────────┘
   (map:* / stage:* commands registered with applicability =
    evaluate_tool(...).disabled_reason — one string source everywhere)
```

V9 additions to this map:

| Context | V9 behavior |
|---|---|
| Dock visibility per workflow | `DockDescriptor.workflow_tags` + stage `dock_recommendation` (first-entry-only suggestions; user layout free afterwards) |
| Viewport class | non-preference layout constraints only (see 04) — never tool availability |
| GL-bearing content (well/seismic/3D hub) | docks not floatable (crash-class prevention), everything else (move/tab/close/reopen) unchanged |

## Verified invariants (tests)

- `tests/test_visual_qa_v8.py` — palette disabled reasons = evaluator output; frozen product disables editing but keeps view/export tools; blocking task disables map tools with reason.
- `tests/test_dock_framework_v9.py` — GL docks not floatable; presets visibility-only; grow-only affordances; per-dock save wiring.
- `tests/test_workstation_context.py`, `tests/test_action_help_v8.py` — availability/context seam tests (64 tests in the batch run, all green).

## Inspector typing (V7 §8, carried forward)

Layer-tree selection routes to typed inspector payloads (layer / factor via `factor_task_id` membership); domain rows come through the context seam (`composite.layer_domain_status`) — the inspector never re-derives mapping authority.
