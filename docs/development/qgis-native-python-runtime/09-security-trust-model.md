# QGIS Native Python Runtime — Startup Mechanisms (Phase H), Trust Model (Phase N) and Package Policy (Phase M)

Date: 2026-09-23 · Base: `192422c60`

## 1. Trust classes

| Class | What it is | Powers |
|---|---|---|
| **Trusted local code** | console opened by the user, script run by the user, plugin the user enabled | full local Python capability. **We do not pretend it is sandboxed** |
| **Untrusted project content** | any `.py` found inside a project directory, project metadata, downloaded scripts | **never executed automatically** |
| **Agent-generated code** | Python produced by the autonomy/agent layer | only via registered Processing algorithms; unrestricted eval is a high-privilege explicit tool |

## 2. Startup mechanisms

Standard QGIS mechanisms are honoured, unchanged in semantics:

| Mechanism | Status | Notes |
|---|---|---|
| `PYQGIS_STARTUP` environment variable | **supported** — standard QGIS behaviour | path is logged at startup (sanitised) |
| `startup.py` in the user's Python path | **supported** — standard QGIS behaviour | executed by QGIS's own init sequence, not by paleo |
| profile Python paths | **supported** | QGIS profile resolution |
| paleo project startup script | **opt-in only** | see §3 |

## 3. Paleo project startup (opt-in, if ever added)

| Requirement | Statement |
|---|---|
| opt-in | disabled by default; a project never runs code because it was opened |
| visible source | the resolved script path is shown in the diagnostics panel |
| disableable | one setting turns it off globally |
| logged | every execution is recorded with path + timestamp + result |
| not a replacement | it never replaces or shadows QGIS's standard startup |

## 4. Prohibitions (enforced by design, not by convention)

| # | Prohibited behaviour |
|---|---|
| P1 | auto-executing unknown `.py` found in a project directory on open |
| P2 | `eval`-ing Python stored in project metadata / layer custom properties |
| P3 | silently executing a script after a network download |
| P4 | the default agent loop running arbitrary Python source strings |
| P5 | auto-enabling / auto-starting a plugin that the user has not enabled |
| P6 | swallowing a plugin load traceback |

## 5. Plugin trust rules

- disabled ⇒ never started (L1 in `07`);
- load failure fails honestly with the traceback;
- `unload()` always runs on disable and on shutdown;
- enabling is a user action; there is no "trust by default".

## 6. Package / pip policy (Phase M)

| Rule | Statement |
|---|---|
| M1 | the QGIS Python runtime is the base environment; paleo does not create a competing venv |
| M2 | **no** automatic `pip install` at startup |
| M3 | **no** automatic network dependency installation |
| M4 | Conda is never a product requirement |
| M5 | a plugin with a missing dependency follows QGIS's own mechanism and produces a diagnostic naming the missing package |
| M6 | if profile-local packages are ever needed, they must match the QGIS Python ABI exactly (same interpreter, same PyQt6/SIP) |
| M7 | the diagnostics panel shows the resolved environment so a user can install a dependency themselves |

## 7. Python expression functions (Phase I)

QGIS's own Python expression-function registration is used as-is: user
functions are registered through `QgsExpression`/`qgis.utils` the same way
upstream does, and land in QGIS's expression engine — usable from labels,
styles, templates, fields and derived geological attributes. **No paleo
expression engine.**

## 8. Paleo domain Python API (Phase J)

Principles applied when deciding whether `paleo.*` exists at all:

1. if it can be expressed with PyQGIS → do **not** add `paleo.*`;
2. if it can be expressed with QGIS custom properties → do **not** duplicate the model;
3. only genuinely domain-specific entities are bound (wells, horizons, facies, provenance runs);
4. ownership/lifetime is explicit — Python references never outlive the C++ object;
5. no dangling C++ pointers are held by Python;
6. Python is never the domain datastore authority;
7. the binding must be ABI-compatible with the current QGIS bindings/SIP — no second binding runtime.
