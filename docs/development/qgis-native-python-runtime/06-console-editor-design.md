# QGIS Native Python Runtime — Python Console & Script Editor (Phases C & D)

Date: 2026-09-23 · Base: `192422c60`

## 1. Priority order (fixed by the goal spec)

1. **Load QGIS's own console** — no paleo REPL, no paleo editor widget.
2. Reuse QGIS's console package / widget as-is.
3. Only if the public API is insufficient, port upstream code **with
   provenance recorded** (upstream path, tag, license, copyright, change note).

## 2. What upstream actually ships (verified in `final-4_2_0`)

| Path | Content | Reuse decision |
|---|---|---|
| `python/console/` (12 files, 184 KB) | `console.py`, `console_editor.py`, `console_output.py`, `console_sci.py`, `console_settings.py`, `console_compile_apis.py`, `process_wrapper.py`, `CMakeLists.txt` | **reuse verbatim** — this *is* the QGIS Python Console |
| `src/gui/codeeditors/qgscodeeditorpython.{h,cpp}` | QScintilla-based Python editor with highlighting | **already vendored** in `third_party/qgis` → reuse, do not rewrite |
| `src/gui/codeeditors/qgscodeeditorwidget.{h,cpp}`, `qgscodeeditordockwidget.{h,cpp}` | editor + dock chrome (open/save/run selection/history) | **already vendored** → reuse |
| `python/qsci_apis/` (2.1 MB) | API files used for completion | **reuse** (ships with the bindings install) |

The console is a *Python* package, not a C++ widget: it is loaded through the
Python runtime after `initPython()`, and it reaches the host through `iface`
(`console.py` uses `iface.mainWindow()` to parent its dock). That is exactly
why Phase B must come first.

## 3. Console design

| Aspect | Decision |
|---|---|
| Loading | `QgsPythonUtils::runString("from qgis import utils; utils.load_console()")`-equivalent path — i.e. QGIS's own console bootstrap, not a paleo launcher |
| Placement | the console dock is parented into the shell's real main window (Prompt 1 authority) — no floating second window |
| Pre-imported surface | `qgis.core`, `qgis.gui`, `qgis.processing`, `iface`, `QgsProject.instance()`, `QgsApplication.processingRegistry()` — identical to QGIS |
| Multiline / run selection / traceback | inherited from upstream; paleo adds nothing |
| Repeated open / close | must be idempotent; the console instance is owned once and re-shown |
| Shutdown | console closed before `exitPython()` |

Acceptance smoke (DoD #6) — executed inside the product process:

```python
from qgis.core import *
from qgis.gui import *
from qgis import processing
QgsProject.instance()
QgsApplication.processingRegistry()
iface.mapCanvas()
iface.activeLayer()
```

## 4. Script editor design

`QgsCodeEditorPython` + `QgsCodeEditorWidget` are already vendored, so the
editor is *not* new UI:

| Feature | Source |
|---|---|
| Python syntax highlighting, brace matching, indentation | `QgsCodeEditorPython` |
| open / save / run file / run selection | `QgsCodeEditorWidget` chrome |
| traceback display | the console's output pane (`console_output.py`) |
| API completion | `python/qsci_apis` via `QgsCodeEditorPython`'s API loading |
| QGIS/PyQGIS help hooks | upstream console (`console_sci.py` help handling) |

Paleo contributes only the **action seam** (Phase D's menu):

```text
Tools → Python
  ├─ Python Console
  ├─ Script Editor
  ├─ Run Script...
  ├─ Processing Scripts
  ├─ Python Plugins
  └─ Environment Diagnostics
```

Menu/toolbar authority stays with Prompt 1; this branch only registers the
actions through the shell's action seam and owns the widgets they open.

## 5. Requirements the tests must hold

- open/close/reopen without leaking the console instance;
- multiline input and traceback rendering;
- run-file path resolves and reports errors;
- console survives a project switch (it must not hold a dead project wrapper);
- console is closed and Python still shuts down cleanly at app exit.

## 6. Explicitly not built

No generic REPL, no custom editor widget, no paleo-specific script runner, no
JSON-based "execute this source" contract. Anything the console cannot do is a
gap in the `iface` adapter, not a reason to write a new console.
