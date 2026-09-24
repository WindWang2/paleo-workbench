# QGIS Native Python Runtime — Review Findings

Date: 2026-09-23 · Branch: `feat/qgis-native-python-runtime`

Two independent review passes were run over the branch. Findings are listed
with severity, evidence and disposition. **P0/P1 must be zero before the PR is
mergeable**; the current state is recorded honestly at the bottom.

## Pass 1 — architecture-gate review (against the goal spec's 10 gates)

| # | Finding | Severity | Evidence | Disposition |
|---|---|---|---|---|
| 1.1 | Phase A bootstrap transcribes the upstream chain, including the two mandatory `QLibrary` load hints | OK | `03` §2, `src/python_runtime.cpp` | accepted |
| 1.2 | `QgsPythonRunner::setInstance()` is called **after** `initPython()` and only when enabled | OK | `src/python_runtime.cpp` | accepted |
| 1.3 | No `Py_Initialize`/`Py_Finalize` anywhere in paleo code | OK (gate #1) | grep performed over the branch sources | accepted |
| 1.4 | The vendored Python closure is **not yet imported** into `third_party/qgis` — the runtime therefore cannot load `qgispython` in this branch as committed | **P1** | `third_party/qgis/src/python` absent | **open**: `scripts/import_qgis_python_closure.sh` performs the import with hash verification; must be run and committed before merge |
| 1.5 | `sip` build tool is absent on the verification host, so `WITH_BINDINGS` cannot be built there | **P2** | `02` §4 | accepted as a documented packaging prerequisite; bindings option defaults OFF |
| 1.6 | Phase B (`QgisInterface` adapter, 279 pure virtuals) is designed but **not implemented** in this branch | **P1** | `05` exists; no adapter TU | **open**: the runtime accepts `nullptr` iface, so Phase A is complete and testable; the adapter is the next increment |
| 1.7 | Diagnostics never emit secrets; env keys are allow-listed and long values truncated | OK (Phase L) | `src/python_diagnostics.cpp` | accepted |
| 1.8 | No project-directory Python is executed; startup policy is opt-in only | OK (gates #8) | `09` §2–§4 | accepted |

## Pass 2 — code and integration review

| # | Finding | Severity | Evidence | Disposition |
|---|---|---|---|---|
| 2.1 | `PythonRuntime::initialize()` marks itself initialised **before** loading the library, so a failure is never retried — matches "init once only" but also means a transient failure is sticky for the process | **P2** | `src/python_runtime.cpp` | accepted by design (N1); `shutdown()` clears the flag so a deliberate retry is possible |
| 2.2 | The upstream safety transplant that neutralises `QgsApplication.initQgis/exitQgis` only runs when bindings are importable | OK | `src/python_runtime.cpp` (`kNeuterAppInit`) | accepted — without bindings there is no `QgsApplication` in Python to misuse |
| 2.3 | `PythonRunner` deletes nothing: `QgsPythonRunner::setInstance()` takes ownership and deletes the previous instance | OK | `third_party/qgis/src/core/qgspythonrunner.cpp` | accepted |
| 2.4 | `shutdown()` deletes `QgsPythonUtils` while the library is still loaded, then unloads — correct order | OK | `src/python_runtime.cpp` | accepted |
| 2.5 | The console action depends on `iface.actionShowPythonDialog()` (QGIS's `show_console()` connects to it) — an adapter without that member will break console opening | **P1** | `python/console/console.py::show_console()` | **fixed in `05`**: the member is promoted to Tier A with the reason recorded |
| 2.6 | `python_actions_install.cpp` keeps "Processing Scripts" and "Python Plugins" disabled with an explicit tooltip rather than faking them | OK | source | accepted (Phases E/F follow) |
| 2.7 | Root `CMakeLists.txt` gained a conditional `add_subdirectory(libs/qgis_python)`; with the option OFF the build graph is unchanged | OK | `CMakeLists.txt` | accepted |
| 2.8 | The bridge now forwards `-DWITH_PYTHON/-DWITH_BINDINGS` from options and **fails configuration** when the closure is missing | OK | `native/qgis_render_bridge/CMakeLists.txt` | accepted — fail fast beats a silently Python-less build |
| 2.9 | Tests were written but **not executed**: the authoring session lost shell/compiler access before any build could run | **P0** | see below | **open** — this is the single blocker for merge |

## Pass 3 — post-implementation verification (after shell access returned)

| # | Finding | Severity | Evidence | Disposition |
|---|---|---|---|---|
| 3.1 | Vendored closure imported: `src/python` 5 files, `python/` 5 090 files, archive SHA-256 verified | OK | `scripts/import_qgis_python_closure.sh` output | **fixed** (1.4 closed) |
| 3.2 | Import script originally deleted the class-D plugins with `rm -rf`, which is both unsafe-to-replay and blocked by a bulk-delete guard; now excluded at extraction time with `tar --exclude` | **P2 → fixed** | script diff | **fixed** |
| 3.3 | Two `g++ -fsyntax-only` failures in `python_runtime.cpp`: `Impl` had no `libraryError` member; `QLibrary::resolve()` returns `QFunctionPointer`, not `void*` | **P1 → fixed** | compiler output | **fixed** — this is exactly why compilation had to be attempted |
| 3.4 | The test TU used `PythonCapability` without a using-declaration | **P2 → fixed** | compiler output | **fixed** |
| 3.5 | **Design error corrected**: `src/python` is added by upstream only inside `if (WITH_BINDINGS)`, so `qgispython` cannot be built without the bindings — the earlier two-gate design was wrong | **P1 → fixed** | `third_party/qgis/src/CMakeLists.txt:36` | **fixed**: single gate `PALEO_WITH_QGIS_PYTHON`; `03` §7 records the correction |
| 3.6 | All six paleo TUs pass `g++ -fsyntax-only` against the real vendored QGIS 4.2.0 headers (generated `qgsconfig.h` from a configure-only build of the snapshot) | OK | compiler output, 0 diagnostics | accepted |
| 3.7 | Vendored QGIS 4.2.0 **configures** cleanly on this host (`Configuring done … Generating done`), including Python detection | OK | cmake output | accepted |
| 3.8 | No full build of `qgis_core` / `qgispython`, therefore **no test execution** | **P1** | — | **open**: building the QGIS closure is a multi-hour job; `14` §4 lists the exact commands |

## Honest status of this review

| Severity | Count | State |
|---|---|---|
| P0 | **0** | — |
| P1 | **2** | 1.6 (iface adapter not implemented — Phases B), 3.8 (no full build / no test execution) |
| P2 | 2 | 1.5 (`sip` prerequisite), 2.1 (sticky init flag, by design) |

**This branch is not a finished Prompt 7.** It is a verified Phase A
(compiles, vendored closure imported, bootstrap chain correct) plus the
complete design ledger for Phases B–O. The two P1 items are the remaining
work, in the order given in `14-final-verification.md` §4.
