# Segfault bisect report — full-suite exit 139 under `QT_QPA_PLATFORM=offscreen`

Date: 2026-07-23. Investigation only; no tracked files modified.

## Verdict

- **Culprit test**: `tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`
- **Lethal object**: the `pyqtgraph.opengl.GLViewWidget` (a `QOpenGLWidget`) created at
  `paleo_workbench/ui/pages/geological_modeling_3d_page.py:117` (`self.gl_widget = gl.GLViewWidget()`),
  which this test — uniquely among the early suite — `show()`s offscreen
  (`tests/test_geological_modeling_3d_page.py:128`).
- **Mapping work (7360861, d7adebc, e586c03): EXONERATED** (evidence below).
- **Deterministic: YES** — 5/5 segfaults across the minimal repros.

## Minimal reproduction (deterministic)

Smallest pytest invocation (segfaults 2/2; the test itself reports `F`, then the process dies in GC
during pytest unconfigure):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m pytest -q \
  tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout
```

Even smaller, pytest-free (segfaults 2/2):

```python
import sys, gc
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import pyqtgraph.opengl as gl
w = gl.GLViewWidget()
w.show()
app.processEvents()   # may raise RuntimeError from initializeGL; irrelevant
del w
gc.collect()          # SIGSEGV here
```

The two-file repro used during bisection (3/3 segfaults):
`pytest -q tests/test_geological_modeling_3d_page.py tests/test_geoviz_package_independence.py`
— `test_geoviz_package_independence.py` contains no Qt code; its `ast.parse` work merely gives the
GC something to traverse, which is why the full-suite crash signature lands there.

## Mechanism

1. Offscreen, Qt prints `QOpenGLWidget is not supported on this platform.` / `QOpenGLWidget: No fbo, cannot render`.
2. `show()` forces `GLViewWidget.initializeGL()`
   (`.venv/.../pyqtgraph/opengl/GLViewWidget.py:101`). pyqtgraph checks
   `ctx.format().version() < (2, 1)` against the **requested** surface format (Qt default = 2.0), not
   the actual context, so it raises `RuntimeError: pyqtgraph.opengl: Requires >= OpenGL 2.1; Found
   b'4.6.0 NVIDIA 610.43.03'` mid-initialization. The widget is left half-initialized. (This is also
   why the test itself FAILs offscreen — a pre-existing failure, independent of the crash.)
3. On teardown, Qt parent/child deletion frees the C++ side while a Shiboken wrapper remains
   reachable from a Python reference cycle. The next CPython GC pass walks the dead object →
   use-after-free **inside the collector**.

Because the fatal dereference happens inside GC, the crash *location* in the full suite is
non-deterministic (whichever test allocates enough to trigger collection — run 1/3: `ast.parse` in
`test_geoviz_package_independence.py`; run 2: the next `QOpenGLWidget` construction in
`GLViewWidget.__init__` line 29 `super().__init__()`), but the lethal state is deterministic and
always comes from the shown-then-torn-down `GLViewWidget`.

## Stack evidence

Python (faulthandler, full suite and minimal pair):

```
Garbage-collecting
  File ".../ast.py", line 52 in parse
  File "tests/test_geoviz_package_independence.py", line 95 in _workbench_geoviz_import_violations
```

Solo run dies in pytest's own `gc_collect_harder` (`_pytest/unraisableexception.py:33`) at
`pytest_unconfigure`.

C-level (gdb `-batch -ex run -ex bt`, minimal pair):

```
#0  visit_decref
#1  dict_traverse
#2  deduce_unreachable
#3  gc_collect_main
#4  _PyEval_EvalFrameDefault ... pymain_run_module
```

i.e. the crash is in CPython's cyclic GC decrementing a dangling pointer — a use-after-free of a
Qt/Shiboken object, not a bug in the collector and not in any project C++ extension.

## Mapping-domain implication: NO (exonerated)

- The crashing prefix (test files 1–43 alphabetically, where every full-suite crash occurred)
  contains **zero** mapping test files — the first `tests/test_map_*` file is #57 of 207.
- The pytest-free repro above loads only 18 extension modules: PySide6, numpy, gdal/osgeo, shapely.
  **No `map_edit_core`, no `seismic_3d_core`, no `well_log_core`.** The
  `disabled_acceleration` seam in `paleo_workbench/native_backend.py` is therefore irrelevant to
  this crash; nothing in the repro path touches the native backend.
- Neither `tests/test_geological_modeling_3d_page.py` nor
  `paleo_workbench/ui/pages/geological_modeling_3d_page.py` imports any mapping module (imports are
  pyqtgraph, `paleo_workbench.viz.geomodel.*`, workers, dialogs).
- Timing: the culprit page/test predate the mapping session — last touched by `603cc6c` (2026-07-22)
  and earlier 3D-modeling commits; the mapping commits `7360861`/`e586c03` are dated 2026-07-23.

## Does it predate the mapping session? Plausibly yes / independent of it

- The repro involves only `geological_modeling_3d_page.py` + pyqtgraph + Qt offscreen; every piece
  predates the mapping commits.
- `git log -- paleo_workbench/ui/pages/seismic_view_panel.py paleo_workbench/ui/app_shell.py
  paleo_workbench/app.py` shows the seismic page was last reworked 2026-07-19..20 (`297391b`,
  `90d77c2`); the eager `SeismicPredictionPage()` construction in `AppShell`
  (`paleo_workbench/ui/app_shell.py:88`) explains run 2's crash *site* (a second QOpenGLWidget
  construction hitting already-corrupted GL/Qt state), not the root cause.
- Note: `534e3e3` (2026-07-23, parallel session) bumped geo-viz-engine for a "GLViewWidget teardown
  guard", but `geological_modeling_3d_page.py:117` instantiates pyqtgraph's `GLViewWidget` directly,
  bypassing any engine-side guard — so that fix does not cover this path.

## Fix directions (not applied — diagnosis only)

- In `tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout`,
  avoid `page.show()` offscreen (or skip when `QGuiApplication.platformName() == "offscreen"`).
- And/or set an appropriate default `QSurfaceFormat` (>= 2.1) before `QApplication` creation in
  test bootstrap so pyqtgraph's version check does not raise mid-`initializeGL`.
- Longer term: route the page's 3D viewport through the same teardown-guarded wrapper the engine
  uses, instead of raw `pyqtgraph.opengl.GLViewWidget`.

## Bisect trail (all `QT_QPA_PLATFORM=offscreen`)

| Invocation | Result |
|---|---|
| files 1–43 (prefix to `test_geoviz_package_independence.py`) | SEGV (139), GC during ast.parse |
| files 1–21 + geoviz | PASS (243) |
| files 22–42 + geoviz | SEGV |
| files 22–31 + geoviz | PASS |
| files 32–42 + geoviz | SEGV |
| files 32–36 + geoviz | PASS |
| files 37–42 + geoviz | SEGV |
| files 37–39 + geoviz | PASS |
| `test_formation_volume` + `test_geological_modeling_3d_page` + geoviz | SEGV |
| `test_formation_volume` + geoviz | PASS |
| `test_geological_modeling_3d_page` + geoviz | SEGV (3/3) |
| `...::test_geological_modeling_3d_page_ui_elements` + geoviz | PASS |
| `...::test_geological_modeling_3d_page_splitter_layout` + geoviz | SEGV |
| `...::test_geological_modeling_3d_page_splitter_layout` alone | SEGV (2/2) at GC in pytest unconfigure |
| 12-line pytest-free GLViewWidget script | SEGV (2/2) |

Artifacts: `/tmp/run_prefix43.log`, `/tmp/runD2.log`, `/tmp/m2.log`, `/tmp/solo.log`, `/tmp/gdb.log`,
`/tmp/mini_repro2.py`, `/tmp/mini_repro3.py`.
