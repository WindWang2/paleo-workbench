# Final Acceptance

Current status: **conditionally ready for a Qt/QGIS-equipped acceptance
runner; not yet accepted as a fully verified native package**.

> **cpp-100-percent-final-closure update (Windows host, this branch)**:
> the pending native product configure/build and the CTest leg now have
> evidence — configure pass, build 503/503 steps pass, CTest 223/250
> pass on MSVC (see 06-test-evidence.md for the record and the remaining
> Windows-port ledger). Linux CI and the deployed-tree legs stay on the
> acceptance runner.

Satisfied:

- complete one-row-per-Python-module truth matrix;
- declarative feature graph before subdirectory evaluation;
- formal product implications for supported native capabilities;
- native provider service ownership and runtime probe;
- Python-source exclusion from native install trees;
- reproducible static and full final-closure gates;
- static audit and data-only native build evidence.

Pending:

- native product configure/build with Qt 6.8 and QGIS;
- focused and integration CTest, twice;
- `pwb-platform --self-check`, `--capabilities`, and `--diagnostics`;
- package/install/deploy audit;
- deployed-tree self-check;
- `ldd` Python/PySide/shiboken audit;
- Qt/QGIS-backed confirmation of the review findings.

Acceptance is complete only when:

```bash
scripts/cpp-migration/final-closure-gate.sh all
```

exits zero on a provisioned runner and its exact counts are recorded here and
in the pull request.
