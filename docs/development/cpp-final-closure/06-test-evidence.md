# Test Evidence

Executed in this worktree:

| Check | Result |
| --- | --- |
| final matrix unit tests | 4/4 pass |
| per-module matrix coverage | 678/678 unique modules |
| root feature declaration coverage | pass |
| native install Python exclusion policy | pass |
| source Python runtime audit | pass; binary audit skipped |
| data-only configure | pass |
| `pwb_data` + `pwb_job_runtime` build | pass, 76 steps |
| data/job tools-free test build | pass, 100 steps |
| `data.*` + `job_runtime.*` CTest | 28/28 pass |
| native-product feature fixpoint | pass |
| native-product configure | blocked at missing Qt 6.8 |

The static acceptance entry point is:

```bash
scripts/cpp-migration/final-closure-gate.sh static
```

The complete gate is:

```bash
scripts/cpp-migration/final-closure-gate.sh all
```

The complete gate has not been represented as passing on this machine. It
requires Qt 6.8, the QGIS SDK/runtime, and the product's provider/runtime data.
