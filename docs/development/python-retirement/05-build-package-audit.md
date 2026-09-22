# Python Retirement — Build & Package Audit

How the native build/install/packaging surfaces were detached from the
retired Python tree, with the verification record. Environment: Linux
(GCC 16.2.1), Qt6 system prefix, vendored QGIS SDK reused from the sibling
main checkout (`PALEO_QGIS_SDK_DIR`), resource gate at `-j 2`.

## Configure

```text
cmake -S . -B build/final-closure -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DPWB_BUILD_NATIVE_PRODUCT=ON -DPWB_BUILD_INTEGRATION_TESTS=ON \
  -DPWB_BUILD_TOOLS=OFF -DPWB_ENABLE_PACKAGING=ON
→ exit 0, build.ninja generated
```

Notable evidence: configure succeeds with `paleo_workbench/` absent from
the source tree — `pwb_install_resources()` now stages the native-owned
`resources/` tree (facies JSONs + `ui/assets/icons/**`, 150 assets, git-mv
history preserved) and no longer globs the retired package. The
`resource_locator` dev-tree probe is `<source>/resources` only.

## Compile fixups required by the stacked base (#1473)

#1473's build evidence is MSVC-only; two Linux-path defects surfaced and
were fixed on this branch (each a stacked fixup, listed in the PR body):

| File | Defect | Fix |
|---|---|---|
| `libs/providers/src/plugin_loader.cpp` | non-Windows `dl_close()` called `::dl_close` (the anonymous-namespace wrapper itself — infinite recursion intent, rejected by GCC's global qualification) | `::dlclose` |

## Install / package rules (post-retirement shape)

- `cmake/PwbInstall.cmake`: installs `resources/` under
  `share/paleo-workbench/` (`.py`/`__pycache__` excluded); no
  `paleo_workbench/` sources; no `*schema*` glob (no schema dirs existed).
- `legacy/python_reference/**` appears in **no** CMake source, install
  rule, package manifest, launcher, or deploy script (effective-code scan
  in `check-python-retirement.sh`; comment-only mentions are exempt).
- `final-closure-gate.sh run_package` now additionally refuses any
  `legacy/` path in the install tree on top of the existing `.py`/`.pyc`
  prohibition.
- Deploy tree (`deploy-native-product.sh`) collects the binary + QGIS
  prefix + licenses; nothing under it may reference or contain the
  archive.

## Runtime independence

- `audit-python-runtime-deps.sh`: product link set (apps + product libs)
  contains no `Python.h`/`Py_Initialize`/PySide/python-subprocess
  references; pybind11 confined to the two compat seams
  (`libs/mapping_bind`, `libs/cartography/cartography_bind`) which are
  consumed by Python and never linked into `pwb-platform`.
- `check-python-retirement.sh` (new) adds the archive-isolation, tree
  shape, sanctioned-shim, and install-purity checks and is wired into the
  final-closure gate's static stage.
- `ldd` closure over the built `pwb-platform`: verified in the runtime
  stage (record in 06-test-evidence.md).
