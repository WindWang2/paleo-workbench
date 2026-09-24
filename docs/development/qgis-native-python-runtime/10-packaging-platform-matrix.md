# QGIS Native Python Runtime — Packaging & Platform Matrix

Date: 2026-09-23 · Base: `192422c60`

## 1. What the package must carry (both platforms)

| Artefact | Source | Destination |
|---|---|---|
| `qgispython` shared library | built from `third_party/qgis/src/python` | alongside `qgis_core` (QGIS library dir) |
| `qgis` Python package (`core`, `gui`, `analysis`, `_3d`, `processing`, `utils`, `user`) | built from `third_party/qgis/python` | QGIS Python site dir |
| built-in Python plugins (`processing`, `pyplugin_installer`) | `python/plugins`, `python/pyplugin_installer` | `.../python/plugins` |
| console package | `python/console` | `.../python/console` (ships with the bindings install) |
| API files for completion | `python/qsci_apis` | `.../python/qsci_apis` |
| the interpreter the bindings were compiled against | the QGIS distribution's Python | never a paleo-private venv |

The bridge already resolves a vendored prefix (`PALEO_QGIS_SDK_DIR`); the
Python artefacts are installed under the same prefix so `QLibrary` resolution
and `PYTHONPATH` stay inside one tree.

## 2. Platform differences

| Concern | Windows (MSVC) | Linux (GCC) |
|---|---|---|
| `qgispython` file name | `qgispython.dll` (`lib` prefix only on MinGW) | `libqgispython.so` (+ `.so.4.2.0` versioned) |
| library lookup | `QgsApplication::libraryPath()` + DLL dir on `PATH` | `QgsApplication::libraryPath()`, `LD_LIBRARY_PATH` must not be polluted |
| Python | the distribution's `python3xx.dll` must be reachable | `libpython3.14.so` (present on the verification host) |
| PyQt6 / SIP | must match the QGIS distribution build | PyQt6 present on host; **`sip` build tool missing → prerequisite** |
| QScintilla | `qscintilla2_qt6` from the dependency prefix (`C:/deps/...`) | `/usr/include/qt6/Qsci` + `libqscintilla2_qt6.so` (present) |
| plugin/profile paths | `%APPDATA%/QGIS/QGIS3/profiles\default/python/plugins` equivalent | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` equivalent |
| packaging | install scripts under `packaging/` must copy the Python tree into the install image | same, via the existing install scripts |

## 3. Known prerequisite gaps

| Gap | Platform | Action |
|---|---|---|
| `sip` build executable (≥ 6, matching the installed PyQt6) | Linux verification host | install before enabling `PALEO_WITH_QGIS_BINDINGS`; the option defaults to `OFF`, so the current build is unaffected |
| PyQt6 + `PyQt6.sip` + `Qsci/qscimod6.sip` on the Windows prefix | Windows | confirm present in the dependency prefix; otherwise the bindings gate stays off there too |

## 4. PATH / PYTHONPATH policy

- paleo appends **only** the vendored prefix paths; it never prepends, so a
  host-installed QGIS cannot win the resolution race;
- `PYTHONPATH` is not used to inject a second environment;
- if a host QGIS is installed (as on this Linux box: 4.2.2 with full PyQGIS),
  the diagnostics panel reports it as **"present but not used"** so nobody
  mistakes it for the runtime in use.

## 5. Degradation matrix

| State | Product behaviour |
|---|---|
| `qgispython` missing | C++ product fully usable; Python features report unavailable; one structured diagnostic |
| `qgispython` present, bindings missing | runner works for non-PyQGIS statements; `import qgis.core` fails with a clear message; console/processing unavailable |
| both present | full PyQGIS: console, editor, scripts, plugins, processing |

Every row is a supported shipping configuration — the package never ships a
half-state silently.
