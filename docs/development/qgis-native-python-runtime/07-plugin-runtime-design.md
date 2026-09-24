# QGIS Native Python Runtime — Python Plugin Runtime (Phases F & G)

Date: 2026-09-23 · Base: `192422c60`

## 1. Non-negotiable: reuse QGIS's plugin lifecycle

Everything below is done through `QgsPythonUtils` (interface verified in
`final-4_2_0/src/python/qgspythonutils.h`):

| Concern | Call |
|---|---|
| discovery | `pluginList()` |
| enabled state | `isPluginEnabled()` / `isPluginLoaded()` / `listActivePlugins()` |
| load | `loadPlugin()` (imports the package) |
| start | `startPlugin()` (calls `initGui()`) |
| processing-only start | `startProcessingPlugin()` + `finalizeProcessingStartup()` |
| metadata | `getPluginMetadata( name, "name"/"version"/"description"/"hasProcessingProvider" )` |
| processing detection | `pluginHasProcessingProvider()` |
| unload | `unloadPlugin()`; `canUninstallPlugin()` before removal |
| state | `isEnabled()` |

**No second plugin backend, no paleo plugin database, no parallel plugin
directory format** (gates #6, #14).

## 2. Search paths

Priority is QGIS's own, unchanged:

1. user profile plugins — `QgsApplication::qgisSettingsDirPath() + "/python/plugins"`;
2. system plugins — `QgsApplication::pkgDataPath() + "/python/plugins"`;
3. a paleo-specific extra path **only if** a real need appears, appended last
   and documented — it never replaces 1 or 2.

## 3. Lifecycle rules

| Rule | Statement |
|---|---|
| L1 | a disabled plugin is never started |
| L2 | load failure fails honestly: message + traceback, plugin stays unloaded |
| L3 | tracebacks are never swallowed |
| L4 | `unload()` is called on app shutdown and on disable; the runtime removes the plugin's `QAction`s from the shell |
| L5 | Processing-provider plugins get `startProcessingPlugin()` then `finalizeProcessingStartup()` after **all** providers have started |
| L6 | plugin `initGui()` runs after `iface` is fully ready, i.e. after shell + session exist |
| L7 | reload (if available upstream) goes through `unloadPlugin()` + `loadPlugin()` + `startPlugin()` |

## 4. Plugin manager UI

QGIS's own manager is **app-private** (`src/app/pluginmanager/`, not part of the
vendored closure). Decision:

- the *backend* is QGIS's: `python/pyplugin_installer` (196 KB, imported with
  the bindings closure) handles repositories, install/uninstall, metadata;
- paleo provides only a **thin UI projection** onto that backend (list,
  enable/disable, install/uninstall) through `iface.showPluginManager()` /
  `pluginManagerInterface()`;
- no re-implementation of the plugin ecosystem.

## 5. Built-in plugin classification (Phase G)

Scanned in `final-4_2_0/python/plugins/`:

| Plugin | Size | Class | Decision |
|---|---|---|---|
| `processing` | 44 MB | **A/B** | import — Python Processing provider, script provider, modeler, GUI. Needs `iface` (B) |
| `pyplugin_installer` | 196 KB | **A** | import — plugin manager backend |
| `db_manager` | 1.4 MB | **D** | not imported — paleo owns database tooling; a DB browser plugin is out of product scope |
| `grassprovider` | 4.4 MB | **D** | not imported — requires an external GRASS GIS install |
| `MetaSearch` | 268 KB | **D** | not imported — CSW catalogue client, out of product scope |

Console support (`python/console`, 184 KB) ships with the bindings closure and
is class **A**.

The goal is maximum reuse of the QGIS Python ecosystem, **not** a QGIS Desktop
clone: class D entries are excluded deliberately and listed here so the
exclusion is a decision, not an oversight.

## 6. Compatibility diagnostics

For each discovered plugin the runtime records:

```text
<plugin>: state=enabled|disabled|loaded|failed
          requires=<iface members used, when detectable>
          last_error=<traceback or ""}
```

An incompatible plugin reports which `iface` member it needed and that the
member is Tier C/D (`05`), so the user sees *why*.
