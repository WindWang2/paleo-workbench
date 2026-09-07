# Progress — Workstation UI/UX V7

## Session 2026-09-08 (setup + audit)
- Worktree .worktrees/workstation-ux-v7 (branch feat/workstation-ux-v7 off main db21f6cf)
- Submodules geo-viz-engine (40ebd168) + well-log-engine (f845e7ab) via manual local
  clone from main checkout (network clone avoided, per V6 session note)
- uv venv cp312 + `uv pip install -e ".[dev]" -r requirements-geoviz.txt` OK
- Native pyds copied from main (grid_render_core, layer_model_core, seismic_3d_core,
  well_log_core) — cp312 ABI-compatible
- Smoke: tests/test_audit_ui.py 6 passed 1 skipped (offscreen)
- Full baseline suite running (fast selection) → .baseline-test-results.txt
- 5 parallel explore audits completed: command surface, pages/docks, design debt,
  context/state services, visual QA + prior-goal docs. Synthesized into findings.md.
- KEY: CommandRegistry predicates dormant (0 production uses); 2 MapActionController
  instances; 3 stage vocabularies; 44-file light-snapshot theme debt; ratchet RED
  (agent_panel 3>2, curve_operation_dialog 1>0); layer tree has zero state decorations;
  group_summary computed but unconsumed; hub force-float seam; 11 non-active page files.
- Planning files rewritten for V7 (repo convention: tracked per-goal).

## Next
- PHASE 2: write docs/development/workstation-ux-v7/00-baseline.md (from findings),
  01-target-state.md, 02-architecture.md, 03-decisions.md; then M1 implementation.
