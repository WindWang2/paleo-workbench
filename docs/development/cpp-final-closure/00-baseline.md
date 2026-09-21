# C++ Final Closure Baseline

Baseline: `412d8baf22a6a928c860e2e3d6c1108a9c035c78` (`origin/main` at
worktree creation).

The baseline already contained a substantial native implementation and a
`pwb-platform` composition root, but its migration evidence was unit-based
rather than one row per Python module. The baseline inventory recorded 60
native units and 264 attributed Python paths while the tracked
`paleo_workbench/**/*.py` tree contained 678 modules.

Baseline closure gaps established by source and configure audit:

- 18 root `PWB_BUILD_*` options were absent from `PwbFeatures.cmake`;
- `PWB_BUILD_NATIVE_PRODUCT` was declared after dependency resolution;
- the native install rule could copy Python files from resource trees;
- the provider target was linked but no provider service was owned by
  `AppContext`;
- workflow and agent closure libraries existed without a product host binding;
- the local environment did not provide Qt 6.8 or the QGIS SDK, so current
  product build/runtime claims could not be reproduced locally.

The closure policy is fail-closed: target existence and unit tests are not
evidence of product support without composition-root wiring and runtime reach.
