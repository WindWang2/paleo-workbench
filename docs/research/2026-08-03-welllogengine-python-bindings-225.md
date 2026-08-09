# WellLogEngine Python bindings expansion (#225)

**Date:** 2026-08-03  
**Parent:** #207 · implements #225  
**Related research:** `docs/research/2026-08-03-welllogengine-gaps-for-workstation.md` (#215)

## Shipped in this ticket

| API | Purpose |
|-----|---------|
| `WellLogView.submit_multi_track(payload)` | Single-well **multi-track** document + `SetPresentationCommand` |
| `WellLogView.submit_multi_well_section(payload)` | Multi-well layout + shared depth viewport (+ markers/overlays) |
| `WellLogView.clear_multi_well_section()` | Clear multi-well layout/overlays |
| Host `engine_bridge.presentation_to_multi_track_payload` | Compile host template presentation → engine payload |
| Host shell **图件 → 打开引擎预览 / 引擎对比预览** | Optional path; host QPainter remains default |

### Payload sketch (`submit_multi_track`)

```python
{
  "document_id": "<uuid>",
  "depth": readonly_f64_ndarray,
  "depth_unit": "m",
  "axis_id": "<uuid>",  # optional
  "top": float, "bottom": float,  # optional viewport
  "curves": [
    {"curve_id": "<uuid>", "mnemonic": "GR", "values": ndarray, "value_unit": "API"},
  ],
  "tracks": [
    {"width_mm": 40, "scale_min": 0, "scale_max": 150, "scale_mode": "linear|log",
     "layers": [{"curve_id": "<uuid>", "color": "#rrggbb"}]},
  ],
  "markers": [{"id": "<uuid>", "depth": 1001.0, "label": "T1"}],  # optional
}
```

Rebuild note: regenerate Shiboken with `WELLLOG_BUILD_PYTHON=ON`. Reject
`welllog_sdk_version` / `manifest_sdk_requirement` (`std::string_view` static
fields crash Shiboken converters). Keep `TableModel` out of generated sources
until wrappers are listed in `WELLLOG_PYTHON_GENERATED_SOURCES`.

## Remaining gaps vs #215 (still open)

| Gap | Status after #225 |
|-----|-------------------|
| G1 Portable template codec | Host JSON still interim; engine has no presentation I/O codec |
| G2 Well metadata on document | Still host-side |
| G3 Interactive tops pick | Markers display via payload only; no pick API |
| G4 Session undo for layout/overlays | Unchanged |
| G5 Workspace catalog | Host (`well-log-engine/apps/wellplot-desktop/well_log_workstation`) |
| Full multi-track **per well** in multi-well section | **#232**: `curves`+`tracks` per well in `submit_multi_well_section` (legacy single-curve retained) |
| Grid layer / professional headers | Track header height set; no grid layer |
| Session/command surface in Python | Still convenience bridges, not full Session binding |

## How to exercise

```bash
export PYTHONPATH="well-log-engine/apps/wellplot-desktop:build/well-log-engine-python/python:well-log-engine/python${PYTHONPATH:+:$PYTHONPATH}"
# Rebuild if needed:
# cmake --build build/well-log-engine-python --target _QtWidgets -j
python -m well_log_workstation
# 应用图版 → 图件 → 打开引擎预览…
# 对比图 → 图件 → 引擎对比预览…
```
