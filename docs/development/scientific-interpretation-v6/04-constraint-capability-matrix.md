# 04 — Method × Constraint Capability Matrix

## Status: implemented (§10, P0-6/P0-7)

Authority: `paleo_workbench/workflow/constraint_capabilities.py`
(`capability_matrix()`, `evaluate_request()`, strict mode raises
`ConstraintViolationError`). ✓ supported · ◑ partial · ✗ unsupported.

| method | boundary_mask | barrier | direction | anisotropy | trend |
|---|---|---|---|---|---|
| IDW 反距离加权 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 约束IDW | ✓ | ✓ | ✓ | ◑ | ✓ |
| 普通克里金 | ✗ | ✗ | ✗ | ✓ | ✗ |
| 样条 (CloughTocher) | ◑ | ✗ | ✗ | ✗ | ✗ |
| 线性插值 | ◑ | ✗ | ✗ | ✗ | ✗ |
| 最近邻 | ◑ | ✗ | ✗ | ✗ | ✗ |
| RBF 多二次 | ◑ | ✗ | ✗ | ✗ | ✗ |
| 方向趋势 | ✗ | ✗ | ◑ | ◑ | ✓ |

Partial notes: 样条/线性/最近邻/RBF clip to the sample convex hull, not a
user boundary ring; 方向趋势 averages multi-line anisotropy into one global
azimuth; 约束IDW anisotropy ratio is floored at 16 by the host adapter
(documented in 06).

## Enforcement (never silent)
- `apply_interpolation_to_task` (single + batch plan paths) derives the
  REQUESTED kinds (breaks/directions/boundary rings/anisotropy params/q-b_i
  weights) and records `constraint_diagnostics`
  (requested/applied/partial/ignored/unsupported + diagnostics) on BOTH the
  task parameters (provenance) and the grid algorithm_parameters.
- the engine (`interpolate_factor_grid`) reports
  `ignored_constraints`/`constraint_warnings` when a backend drops
  constraint inputs; the workflow merges them into the same record.
- `geological_mapping_service.create_factor_map` (dialog/agent path)
  evaluates the project's constraint layers against its method and records
  the same diagnostics + a `constraints_ignored` quality metric.

## Verified by
tests/test_constraint_capabilities.py (11), test_constraint_routing_honesty.py (5).
