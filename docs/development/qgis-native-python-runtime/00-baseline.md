# QGIS Native Python Runtime — Baseline

Date: 2026-09-23 · Executor: WorkBuddy automated run · Mode: fully automated,
no human confirmation, online CI not awaited.

## Repository state at start

| Item | Value |
|---|---|
| Repository | `WindWang2/paleo-workbench` |
| `origin/main` | `192422c60c4eb99ee78a6a410676293ca09053cc` (merge of PR #1480, `devin/1790092371-qgis-native-ui`) |
| Branch | `feat/qgis-native-python-runtime` |
| Worktree | `/home/kevin/projects/paleo-qgis-python` (independent; main workspace untouched) |
| Working tree at branch point | clean, 23 864 tracked files |

## Vendored QGIS baseline

| Item | Value |
|---|---|
| Path | `third_party/qgis` (in-tree, **not** a submodule) |
| Upstream tag | `final-4_2_0` |
| Upstream commit | `ca5812c8b8e39b59695a3b0206fc5f3206eda0a9` |
| Upstream archive | `https://github.com/qgis/QGIS/archive/refs/tags/final-4_2_0.tar.gz` |
| Archive SHA-256 | `98f6913e9e836976f2c0d72d992a172a616621b96c78d9d3a820fdeefd737174` (**re-verified on download, 2026-09-23**) |
| Upstream license | GPL-2.0-or-later (`third_party/qgis/COPYING`) |
| Import policy | `third_party/qgis/README.paleo-workbench.md` — build it, never substitute an installed `qgis_core`/`qgis_gui` |

## PR / issue state checked at execution time

| PR | Branch | State | Relevance |
|---|---|---|---|
| #1484 | `feat/qgis-native-layout-composer-framework` | **OPEN** | Prompt 5 owns `QgsLayout`; Python must reuse the same layout objects |
| #1483 | `feat/qgis-native-layer-control` | **OPEN** | Prompt 2 owns `QgsProject` / `QgsLayerTree`; `iface.activeLayer()` must bind to it |
| #1482 | `feat/qgis-native-data-management` | **OPEN** | Prompt 3 owns project/provider/data |
| #1481 | `fix/cpp-numerics-hardening-20260922` | MERGED 2026-09-22 | orthogonal |
| #1480 | `devin/1790092371-qgis-native-ui` | MERGED 2026-09-22 | Prompt 1 shell convergence — `iface.mainWindow()` / toolbar / menu authority |
| #1479 | `fix/cpp-ui-lifecycle-hardening-20260922` | MERGED 2026-09-22 | Qt object lifetime; relevant to Phase O |
| #1477 | `chore/archive-legacy-python-product` | **CLOSED** (not merged) | legacy Python product stack archived; see `docs/development/python-retirement/` |

## Blocking finding: the vendored closure has no Python at all

`third_party/qgis/UPSTREAM.md` states that QGIS *Python-binding targets* are
deliberately **not** part of the import closure. Verified on disk:

| Component | Upstream path | In `third_party/qgis` |
|---|---|---|
| `qgispython` support library | `src/python/` | **absent** |
| `QgsPythonUtils` / `QgsPythonUtilsImpl` | `src/python/qgspythonutils.h`, `qgspythonutilsimpl.cpp` | **absent** |
| PyQGIS bindings (`qgis.core`, `qgis.gui`, …) | `python/` | **absent** (`.sip` file count in whole tree: **0**) |
| Built-in Python plugins (Processing, console support, …) | `python/plugins/` | **absent** |
| `QgsPythonRunner` (abstract core entry point) | `src/core/qgspythonrunner.{h,cpp}` | **present** |

The build wiring confirms the intent: `native/qgis_render_bridge/CMakeLists.txt`
configures the vendored snapshot as a nested project with
`-DWITH_PYTHON=OFF -DWITH_BINDINGS=OFF`, and `PALEO_WITH_QGIS_RENDERER`
defaults to `OFF`.

Consequence: Phase A cannot be satisfied by configuration alone. The vendored
closure must be **extended** with upstream `src/python/` and `python/` from the
same immutable tag. This is the decision recorded in `01-overlap-audit.md` and
executed per `03-qgispython-bootstrap.md`.

## Upstream source acquisition (external to the repository)

| Item | Value |
|---|---|
| Download | `https://github.com/qgis/QGIS/archive/refs/tags/final-4_2_0.tar.gz` |
| Size | 242 133 574 bytes |
| SHA-256 | matches `UPSTREAM.md` value exactly (see above) |
| Extracted to | `/home/kevin/.build-tmp/qgis-src/QGIS-final-4_2_0` (**outside** any worktree; never committed) |

An older QGIS reference tree also exists on this machine at
`/home/kevin/projects/rs-studio/main/refs/qgis`, but it is **4.0.2
("Norrköping")**, not 4.2.0. It is used for *structural reading only*
(`QgsPythonUtils` contract, `qgsprocess` bootstrap chain); nothing is imported
from it into `third_party/qgis`.

## Host environment (evidence for the capability report)

| Item | Value | Use |
|---|---|---|
| OS | Linux | primary verification platform |
| Python | 3.14.7 (`python3-config` available) | interpreter the bindings must be compiled against |
| PyQt6 | present | QGIS 4.x bindings are PyQt6/SIP-based |
| PySide6 | **absent** | not applicable |
| System QGIS | **4.2.2** with a complete PyQGIS install (`/usr/lib/python3.14/site-packages/qgis`: `core`, `gui`, `analysis`, `_3d`, `server`, `processing`) | **must not be imported** — hard rule forbids substituting system QGIS, and 4.2.2 ≠ vendored 4.2.0 |

## Case selection

Per the goal spec, execution starts from the latest `origin/main`. No stacked
dependency on an open PR is required for the research phase: this branch owns
new files under `libs/qgis_python/**`, `apps/paleo_workbench_platform/python_*`,
`resources/python/**`, `tests/qgis_python/**`, and the vendored-closure
extension under `third_party/qgis/{src/python,python}`. The three open PRs
(#1482/#1483/#1484) touch project/layer/layout authority that Python only
*reads through* — see `01-overlap-audit.md` for the lease ledger.
