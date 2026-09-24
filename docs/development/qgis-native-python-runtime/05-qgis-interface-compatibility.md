# QGIS Native Python Runtime — QgisInterface / `iface` Compatibility (Phase B)

Date: 2026-09-23 · Base: `192422c60` · Interface under study:
`third_party/qgis/src/gui/qgisinterface.h` (65 KB, **279** `virtual`
declarations, essentially all pure).

## 1. Why this file exists

Every serious PyQGIS console session and most Python plugins start from
`iface`. If paleo's `iface` is a stub, the Python ecosystem is not actually
reused. The adapter (`PaleoQgisInterfaceAdapter : QgisInterface`) is therefore
the single most important seam of this work — and the one most likely to be
faked.

Hard constraint from the goal spec: **no second `MainWindow`, no second
`MapCanvas`, no second layer registry, no second menu registry, no second
project.** The adapter only forwards.

## 2. An important C++ fact the tier model must respect

`QgisInterface` is a fixed abstract class: *every* pure virtual must be
implemented, or the adapter stays abstract and cannot be instantiated. So
"Tier D — do not expose" cannot mean "omit the method". It means:

> Tier D methods are implemented as a documented no-op that returns the empty
> value (`nullptr` / `false` / empty list) **and** emits a capability
> diagnostic naming the method, so an incompatible plugin fails loudly instead
> of silently doing nothing.

## 3. Tier definitions

| Tier | Meaning | Implementation shape |
|---|---|---|
| **A** | full mapping to a real paleo/QGIS object | forward to the live object, resolved **at call time** |
| **B** | reasonable mapping (semantically close, minor differences) | forward with an adaptation, documented in the table |
| **C** | unsupported / no-op | return empty value + `QgsMessageLog` diagnostic |
| **D** | unsafe or meaningless for paleo | no-op + diagnostic, explicitly listed so it can never be mistaken for supported |

## 4. Mapping table (core surfaces; verified against the header)

| `iface` member | Tier | Paleo binding |
|---|---|---|
| `mapCanvas()` | A | the session's live `QgsMapCanvas` (`MapSession::createCanvas` product) |
| `mapCanvases()` | A | single-element list containing that canvas |
| `activeLayer()` | A | `QgsLayerTreeView::currentLayer()` of the live layer tree; `nullptr` when none |
| `layerTreeView()` | A | the live `QgsLayerTreeView` created by the session |
| `layerTreeCanvasBridge()` | B | the session's bridge if one exists, else `nullptr` + diagnostic |
| `mainWindow()` | A | the real shell main window (Prompt 1 authority) |
| `messageBar()` | A | the shell's real `QgsMessageBar` surface; falls back to a runtime-owned bar + diagnostic when the shell has none |
| `iconSize()`, `defaultStyleSheetOptions()`, `defaultStyleSheetFont()` | A | queried from the real `QApplication`/shell |
| `editableLayers( bool )` | A | derived from `QgsProject::instance()->mapLayers()` + `isEditable()`/`isModified()` |
| `addCustomActionForLayerType()`, `addCustomActionForLayer()`, `removeCustomActionForLayerType()` | B | forwarded into the shell's layer-context-menu seam; when the seam is absent → C |
| `projectMenu()`, `editMenu()`, `viewMenu()`, `layerMenu()`, `newLayerMenu()`, `addLayerMenu()`, `settingsMenu()`, `pluginMenu()`, `pluginHelpMenu()`, `rasterMenu()`, `databaseMenu()`, `vectorMenu()`, `webMenu()`, `meshMenu()`, `windowMenu()`, `helpMenu()`, `firstRightStandardMenu()`, `projectImportExportMenu()`, `projectModelsMenu()` | B | forwarded to the shell's menu registry by id; a menu paleo does not own → C (nullptr + diagnostic) |
| `fileToolBar()`, `layerToolBar()`, `mapNavToolToolBar()`, `digitizeToolBar()`, `advancedDigitizeToolBar()`, `shapeDigitizeToolBar()`, `attributesToolBar()`, `pluginToolBar()`, `dataSourceManagerToolBar()`, `selectionToolBar()` | B | forwarded to the shell's toolbar host; missing toolbar → C |
| `openLayoutDesigners()` | B | list of live `QgsLayoutDesignerInterface`s from Prompt 5's composer; empty when none open |
| `cadDockWidget()` | C | paleo has no advanced-digitizing dock |
| `activeDecorations()` | C | decorations are not part of paleo's map surface |
| `gpsTools()` | D | no GPS tooling in paleo |
| `mapCanvases3D()`, `createNewMapCanvas3D()`, `closeMapCanvas3D()` | D | paleo does not create 3D canvases through `iface` (3D is `libs/geo3d_viz`'s authority, not a plugin surface) |
| `createNewMapCanvas()`, `closeMapCanvas()` | D | creating/closing canvases is `MapSession`'s authority; a plugin must not spawn canvases |
| `showPluginManager()`, `pluginManagerInterface()` | B | thin projection onto QGIS's own plugin backend (see `07`) |
| `openDataSourceManagerPage()` | B/C | forwarded if the shell exposes a data-source dialog, else C |
| `createProjectModelSubMenu()` | C | paleo has no project-model menu concept |
| `actionShowPythonDialog()` | **A** | **required by QGIS's own console**: `python/console/console.py::show_console()` connects the console's visibility to `iface.actionShowPythonDialog().setChecked`, so the adapter must expose the shell's console toggle action or the console raises on open |

Every remaining accessor (status bar, browser model, dev-tool factories,
options widget factories, locator filters, profile manager, application-exit
blockers, custom map-tool handlers, …) is **Tier C**: null + diagnostic, unless
the owning prompt exposes a seam, in which case it is promoted to B and the
promotion is recorded here.

## 5. Lifetime rules the adapter must obey

1. **No cached pointers to project/canvas/layers.** All accessors re-resolve
   from the host on each call (`MapSession` / shell accessor seam). This is the
   mitigation for risk R-1 (`01-overlap-audit.md`): open PRs #1482/#1483/#1484
   move those objects.
2. `QPointer`-style guards: when the shell or session is gone (shutdown,
   project switch), accessors return `nullptr` instead of dereferencing.
3. The adapter is created **before** `initPython()` and destroyed **after**
   `exitPython()`.
4. `QAction`s added by plugins are registered in a runtime-owned registry so
   they can be removed on plugin unload (Phase O requirement).

## 6. Diagnostics contract

Each Tier C/D hit emits exactly one structured log line:

```text
Python iface: <method> is not supported by paleo (tier C|D) — <reason>
```

This is what makes "incompatible plugin" a diagnosable state rather than a
mystery (DoD #10).
