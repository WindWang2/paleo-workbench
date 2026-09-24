# QGIS Native Python Runtime — Python Processing Scripts (Phase E) and Registry Unification (Phase K)

Date: 2026-09-23 · Base: `192422c60`

## 1. The single registry

```text
C++ Processing algorithms  ─┐
Python Processing scripts  ─┼─► the same QgsProcessingRegistry ─► GUI / Agent / Batch
Python provider plugins    ─┘
```

`third_party/qgis/src/core/processing/**` and
`third_party/qgis/src/analysis/processing/**` are already vendored, so the C++
side of that registry is the same object PyQGIS sees. There is **no**
`PaleoPythonScriptRunner`, **no** second `AlgorithmRegistry`, and **no** JSON
"execute script" contract (explicitly forbidden by the goal spec).

## 2. Python Processing scripts

| Aspect | Decision |
|---|---|
| discovery | QGIS's own script provider (`python/plugins/processing/script`) scans the user's processing scripts directory |
| loading | a `.py` file defining a `QgsProcessingAlgorithm` subclass is registered under its own algorithm id |
| GUI / Agent / batch | all three address it by the **same algorithm id** — no separate paleo script channel |
| feedback / cancel | QGIS `QgsProcessingFeedback` end-to-end; cancelling a Python algorithm is the same code path as cancelling a C++ one |
| outputs | outputs land in the real `QgsProject` / layer tree (Prompt 2 authority) |
| invalid script / exception | registration error + traceback surfaced; the algorithm does not appear as usable |
| execution context | `QgsProcessingContext` built by Prompt 4's scheduler — Python algorithms run inside that context, not beside it |

## 3. Python provider plugins

Plugins that expose a Processing provider go through
`startProcessingPlugin()` → `finalizeProcessingStartup()` (Phase F). Their
algorithms land in the same registry as everything else.

## 4. Agent unification (Phase K)

| Rule | Statement |
|---|---|
| K1 | the agent does not know whether an algorithm is C++ or Python — it knows an algorithm id |
| K2 | Prompt 4 owns Processing/Task execution; this branch owns **availability** of the Python algorithms |
| K3 | if an agent needs arbitrary Python, it must call a registered Processing algorithm |
| K4 | unrestricted `eval` is a **high-privilege explicit tool**, never part of the default agent loop (see `09`) |
| K5 | no silent execution of Python strings assembled from project content |

## 5. Background execution contract

- Python algorithms run inside QGIS's task/processing machinery;
- they must not touch GUI objects directly from a worker thread;
- a Python algorithm that is still running at app shutdown is cancelled before
  `exitPython()` (Phase O).

## 6. Tests

| Test | Assertion |
|---|---|
| script discovery | a shipped sample `.py` algorithm appears in `QgsApplication::processingRegistry()` |
| execution | running it produces the expected output layer in the real project |
| feedback/cancel | cancellation propagates and the algorithm stops |
| invalid script | registration fails with a traceback, no crash |
| exception | in-algorithm exception surfaces a traceback, algorithm reports failure |
| id parity | GUI, agent and batch resolve the same algorithm id |
