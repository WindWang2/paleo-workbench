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

## Windows/MSVC verification record (cpp-100-percent-final-closure branch)

Host: Windows 11 x64, MSVC 14.38 (VS2022), Qt 6.8.0 msvc2022_64, vendored
QGIS 4.2.0 SDK reused read-only from the main checkout, Ninja, gate
`Invoke-ResourceGate.ps1` (admission lowered to the machine's free memory
floor with `-MinFreeGiB 3.5`, jobs=2 — the 8 GiB default protects seven
parallel migration worktrees; this run held the single slot).

- native-product configure: **pass** (Ninja, all features on).
- native-product build: **pass — 503/503 steps, zero failures** (first
  full MSVC build of the tree; includes the branch's new targets:
  `pwb_visualization_well_tie` log_tie kernel, `section_profile_widget`,
  `horizon_interpretation_io`, joint-analysis install wiring).
- CTest (full suite, offscreen): **223/250 pass** (the QGIS-linked
  platform tests additionally need the vendored QGIS `output/bin` on
  PATH). All branch-touched families green: `viz_b.well_tie.oracle` (1082 checks, includes the
  log_tie closure block), `viz_c.joint_analysis` (7/7, including the
  real-log auto-tie and 2D fence-profile E2Es), layout_export oracle
  (geographic graticule spec), `viz_c.joint3d_closure`.
- Windows-port fixes landed for: POSIX `gmtime_r`/`unistd.h`/`dlopen`
  call sites (factor_prepare, closure_agent checkpoint, providers
  plugin_loader, seven test mains), MSVC libm trig-tail divergence in
  the frozen well_tie fixtures (declared 1e-12 absolute tolerance on
  _WIN32), and oracle path-separator normalization (catalog domain).
- Remaining 27 failures are pre-existing Windows-port debt in families
  this branch does not touch (data-suite temp-path 8.3 short-name forms,
  interchange/workflow_engine oracle path spellings, science.viewer
  runtime deps, viz_a viewer flow). They were never executed on Windows
  before this run (#1454 verified Linux only) and are recorded as the
  Windows-port follow-up ledger; Linux CI remains the merge gate.


## Rebase addendum (ribbon five-workspaces merge)

The branch rebased onto main 18c674ef (ribbon five-workspaces shell,
fa9ba744). That merge shipped unbuildable code for this configure shape
— its CI on main is failing — and this branch fixed it:

* `closure_mapping_install.cpp`: static-local lambda capture ill-formed
  under `/permissive-`; MSVC 19.38 ICE on the geographic-preview lambda
  (hoisted to a file-scope helper).
* `workflow_install.cpp` (new in fa9ba744): missing
  `factor_fusion/factor_grid.hpp` include; `workflow_interpretation`
  and `workflow_runtime/constraint_versions.hpp` includes locked behind
  the wrong feature guards — hoisted (the CMake side links
  `Pwb::WorkflowInterpretation`/`Pwb::FactorFusion` when present).
* `workflow_interpretation/fault_lifecycle.cpp`: `wstring::rfind("..")`
  has no narrow overload on Windows (`generic_string()` now).
* `mapping_document/document_io.cpp` `write_atomic`: a Windows absolute
  path has no '/', so the old `find_last_of('/')` turned the whole
  drive-qualified path into the temp-file name (colons → invalid name).

Post-rebase MSVC build: **green** (all steps). The rebased suite runs
~225/257 — every branch-touched family stays green
(`viz_b.well_tie.oracle`, `viz_c.joint_analysis`, layout_export
graticule oracles). The new failures versus the pre-rebase run are the
ribbon shell's own platform tests (`platform.ribbon_visual*`) and
offscreen crashes in the new shell code (`0xc0000409` in
`viz_c.joint3d_closure`/`platform.closure_mapping` under the ribbon
AppShell) — pre-existing main-side Windows debt, untouched by this
branch; Linux CI remains the merge gate.
