# 05 — Runtime dependency & fallback audit (this branch)

Re-run at final HEAD against the branch diff plus the geoviz surfaces.

## Scans

```
rg "Python.h|pybind11|Py_Initialize|PyRun|PyImport|Py_XDECREF" libs apps   → product closure: 0 real hits
rg "QProcess" libs apps                                                     → 0
rg "python3|python.exe" libs apps (C++ sources)                            → diagnostics/self-check probes only
rg "\.py['\"]|qt_add_resources" libs apps cmake                             → no .py resources in product
rg -i "fallback|python_fallback" libs apps                                  → no Python fallback; list below
```

Fallback adjudication (all hits): native Qt map-render backend fallback
(`ui_canvas`), composer-export fail-closed refusal, contour-draft
fail-closed until the native hook binds, UnavailableJointHost placeholder,
preview "message" tier, lenient enum defaults — every one degrades inside
C++ or fails closed; none reaches Python.

## This branch's new runtime paths

* **Job plumbing**: all joint-analysis GUI effects run in the queued
  `on_finished` hop (job_bridge contract); the worker only builds values
  (round-1 P0 fix — verified by adversarial round 2).
* **Stale-delivery guards**: project-directory identity + registration
  pointer identity (volume switch inside a project) before applying any
  stratal overlay.
* **Sidecar writes**: QSaveFile atomic commits (joint_analysis.json,
  geo3d_workspace.json); commit failures are surfaced (stderr/status), and
  corrupt/unreadable geo3d sidecars reset the workspace instead of leaking
  the previous project's objects.
* **Capability truth**: geomodel kernel row now reports its real state
  (`Pwb::GeoModel` probe — the alias was wrong since before this branch —
  and the runtime detail names the joint-analysis consumer when wired).
