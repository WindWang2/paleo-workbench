# Migration Matrix Method

`tools/migration/pwb_final_closure_matrix.py` joins the generated native-unit
inventory to every tracked `paleo_workbench/**/*.py` module. The generated
artifacts are:

- `migration-matrix.json`: machine-readable evidence and remaining action;
- `migration-matrix.md`: one row per Python module.

Every row contains the required closure fields:

```text
python_source, native_target, native_target_exists, native_target_built,
product_wired, runtime_reachable, oracle_covered, product_tested, packaged,
python_runtime_required, final_classification, evidence, remaining_action
```

The generator is conservative:

- a wired native unit is required for `NATIVE_PRODUCT`;
- a native target without product wiring is
  `NATIVE_LIBRARY_NOT_WIRED`;
- missing native behavior is `PARTIAL_NATIVE`;
- an unattributed Python module remains `LEGACY_REFERENCE`, not a speculative
  dead-code classification;
- no Python module is marked packaged or runtime-required by the formal native
  product.

Current roll-up: 678 unique modules, 115 `NATIVE_PRODUCT`, 79
`NATIVE_LIBRARY_NOT_WIRED`, 70 `PARTIAL_NATIVE`, and 414
`LEGACY_REFERENCE`. No module is silently omitted.
