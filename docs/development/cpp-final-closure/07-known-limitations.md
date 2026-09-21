# Known Limitations

1. Qt 6.8 and the QGIS SDK/runtime are unavailable in the current environment.
   Native-product build, CTest, self-check, diagnostics, package deployment,
   and `ldd` evidence remain pending.
2. `Pwb::ClosureWorkflow` is a reusable native library but lacks a formal
   product host binding.
3. The agent panel has an honest no-resolver path; there is no production
   native agent executor binding.
4. 414 Python modules have no native origin attribution. They remain
   `LEGACY_REFERENCE` until a separate import/reference audit proves a narrower
   category.
5. Python oracle and compatibility seams remain in the repository. They are
   excluded from the native install tree and must not be interpreted as native
   runtime dependencies.
6. Historical successful Qt/QGIS verification in older closure documents is
   not substituted for current-branch evidence.
7. The configure-time closure proves target existence, required links, and
   product host definitions. Live service probes exist for the attribute and
   provider registries; the remaining UI-oriented capabilities still require
   the provisioned self-check and entrypoint tests before runtime acceptance.

## Independent review passes

- Migration/Python retirement: no unclassified Python module or invented
  build/test evidence found; the 414 unattributed modules remain conservative
  legacy references.
- C++ architecture/lifetime: provider ownership is scoped to `AppContext`,
  teardown remains idempotent, and no new raw callback or thread-affinity
  seam was introduced.
- Product entrypoints: review found and fixed missing target-link validation
  and tools-free data-test guards. No unresolved P0/P1 finding remains in the
  statically verifiable closure.
