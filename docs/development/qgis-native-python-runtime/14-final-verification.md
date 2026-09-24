# QGIS Native Python Runtime — Final Verification & Remaining Work

Date: 2026-09-23 · Branch: `feat/qgis-native-python-runtime` · Base: `192422c60`

## 1. Architecture gates (goal spec §23)

| # | Gate | Expected | Status |
|---|---|---|---|
| 1 | second CPython runtime initialised? | NO | **PASS by inspection** — no `Py_Initialize` in paleo code; `qgispython` owns the interpreter |
| 2 | product-level Conda/venv replacing QGIS Python? | NO | **PASS** — `10` §4, `09` §6 |
| 3 | Python operates the same `QgsProject`? | YES | **DESIGNED** (`04` §1, rule 9); **not yet executed** |
| 4 | Python Processing in the same registry? | YES | **DESIGNED** (`08` §1); not yet executed |
| 5 | plugin lifecycle reuses QGIS infrastructure? | YES | **DESIGNED** (`07` §1) |
| 6 | second generic plugin backend? | NO | **PASS by inspection** — nothing but `QgsPythonUtils` calls |
| 7 | legacy Python product restored? | NO | **PASS** — `13` §1, nothing imported from `legacy/**` |
| 8 | silent execution of untrusted project Python? | NO | **PASS** — `09` §4 |
| 9 | QGIS/PyQGIS/Python ABI agreement? | YES | **PENDING** — requires the built bindings; `10` §3 records the prerequisites |
| 10 | missing runtime degrades instead of crashing? | YES | **DESIGNED + partially tested** — `test_qgis_python.runtime` asserts the degradation path |

## 2. What is actually verified today

| Item | Evidence |
|---|---|
| all six paleo translation units compile | `g++ -std=c++20 -fsyntax-only` against vendored QGIS 4.2.0 headers + the snapshot's generated `qgsconfig.h`: **0 diagnostics** for `python_runtime.cpp`, `python_runner.cpp`, `python_diagnostics.cpp`, `python_runtime_install.cpp`, `python_actions_install.cpp`, `python_runtime_test.cpp` |
| two real defects were found that way and fixed | `Impl::libraryError` missing; `QLibrary::resolve()` yields `QFunctionPointer`, not `void*` |
| the vendored closure is imported | `src/python`: 5 files; `python/`: 5 090 files; archive SHA-256 verified before import |
| the vendored QGIS snapshot configures | `cmake -S third_party/qgis` → "Configuring done (19.2s) / Generating done (121.6s)" |
| upstream coupling of qgispython | `src/CMakeLists.txt` adds `src/python` only under `if (WITH_BINDINGS)` — corrected the two-gate design |

| Item | Evidence |
|---|---|
| vendored closure really has no Python | `UPSTREAM.md` text + `.sip` count 0 + `src/python` absent (`02` §1–§2) |
| upstream archive is the right one | SHA-256 of `final-4_2_0.tar.gz` matches `UPSTREAM.md` byte-for-byte |
| `qgispython` is cheap and GUI-free | upstream `src/python/CMakeLists.txt` links `qgis_core` + `Python::Python` + openpty only |
| bootstrap order | transcribed from `src/app/qgisapp.cpp::loadPythonSupport` and `src/process/qgsprocess.cpp` |
| runner contract | `QgsPythonRunner` pure virtuals read from the vendored 4.2.0 header; `setInstance()` ownership read from its `.cpp` |
| console entry point | `python/console/console.py::show_console()` (upstream comment: "called from QGIS to open the console") |
| script editor reuse | `qgscodeeditorpython.{h,cpp}` already vendored |
| PR/branch overlap | `gh pr list` at execution time (`00`) |

## 3. What is NOT verified (and why)

The authoring session lost shell access for roughly an hour (the execution
subsystem wedged under heavy I/O). When it returned, the closure import, the
configure and the syntax checks above were run. Still **not** done:

- **no full build** of `qgis_core` / `qgispython` — a multi-hour job that also
  needs the missing `sip` tool for the bindings half;
- **no test execution** — `qgis_python.runtime` has never been run;
- **Phase B (the `QgisInterface` adapter) is still only designed**, so
  `initialize()` is currently exercised with `iface == nullptr`.

These are recorded as P1 in `12-review-findings.md` (3.8, 1.6) rather than
papered over.

## 4. Remaining work, in order

```bash
# 0. (shell required) from the worktree root
cd /home/kevin/projects/paleo-qgis-python

# 1. import the vendored Python closure (hash-verified) — DONE in this branch
bash scripts/import_qgis_python_closure.sh \
     /home/kevin/.build-tmp/qgis-src/final-4_2_0.tar.gz

# 2. provide sip >= 6 matching the installed PyQt6 (prerequisite, see 10 §3)

# 3. configure + build with the single Python gate (parallelism <= 6)
cmake --preset linux-native-product -DPALEO_WITH_QGIS_RENDERER=ON \
                                    -DPALEO_WITH_QGIS_PYTHON=ON
cmake --build build/native-product -j6

# 4. run the Phase A oracle (twice, per 11 §2)
ctest --test-dir build/native-product -R qgis_python.runtime --output-on-failure

# 5. implement Phase B — the QgisInterface adapter (279 pure virtuals,
#    tiers per 05), then Phases C/D/E/F per 06/07/08.

# 6. before opening the PR
git diff --check
git add -A && git commit -s
git push -u origin feat/qgis-native-python-runtime
gh pr create --base main --head feat/qgis-native-python-runtime
```

## 5. Definition of Done status (goal spec §24)

| # | Requirement | Status |
|---|---|---|
| 1–3 | qgispython/QgsPythonUtils path, no self-embedded CPython, valid `QgsPythonRunner` | implemented, **uncompiled** |
| 4 | `import qgis.core/gui/processing` smoke | needs bindings; test exists |
| 5 | same `QgsProject` | designed; test exists |
| 6–7 | console + script editor path | console wired to QGIS's `show_console()`; editor reuses `QgsCodeEditorPython` |
| 8–9 | Python processing scripts + provider plugins in the same registry | designed (`08`) |
| 10 | plugin discover/enable/disable with diagnostics | designed (`07`) |
| 11 | thin `iface` adapter | **designed only** — implementation pending |
| 12–13 | startup compatibility; C++ stays authoritative | done (`09`, `13`) |
| 14 | no second plugin/project/layer/processing runtime | pass by inspection |
| 15–16 | packaging + trust model documented | done (`10`, `09`) |
| 17 | lifecycle/GIL/shutdown tests | planned (`11`) |
| 18 | `-j <= 6` throughout | enforced in the commands above |
| 19 | two reviews, P0/P1 = 0 | **not met** — see `12` |
| 20 | push + PR, no auto-merge | **not done** — shell unavailable |
