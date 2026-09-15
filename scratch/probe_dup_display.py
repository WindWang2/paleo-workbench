"""Reproduce "the copied layer does not display".

Headless, but it uses the REAL window + the REAL project, so every number is
the same number the GUI would show:

  open project -> run mock seismic prediction -> duplicate that layer
and print the CRS authority / layer list / canvas extent at each step.

Writes incrementally so a late crash still leaves the earlier steps.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")

OUT = ROOT / ".workbuddy" / "dup_display_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


import paleo_workbench  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
out("step0 Qt ready")

from paleo_workbench.app import PaleoWorkbenchWindow  # noqa: E402

win = PaleoWorkbenchWindow()
out("step1 window built")


def snapshot(tag: str) -> None:
    """Everything relevant to 'why is the canvas blank'."""
    project = win.project
    comp = win.app_shell.workstation.composite
    coord = getattr(project, "coordinate", None)
    out(f"--- {tag} ---")
    out(f"  project.coordinate.project_crs = {getattr(coord, 'project_crs', None)!r}")
    out(f"  project.coordinate.display_crs = {getattr(coord, 'display_crs', None)!r}")
    out(f"  edit_controller.project_crs    = {comp.edit_controller.project_crs!r}")
    out(f"  layer_manager._project_crs     = {getattr(comp.layer_manager, '_project_crs', None)!r}")
    out(f"  readiness(initial_facies_crs)  = {_readiness()!r}")

    from paleo_workbench.mapping.crs_contract import panel_publish_crs, resolve_crs

    declared = getattr(coord, "project_crs", "")
    res = resolve_crs(declared, purpose="probe")
    out(f"  resolve_crs({declared!r}) -> declared={res.declared} "
        f"crs={res.crs!r} reason={getattr(res, 'degraded_reason', None)!r}")
    out(f"  panel_publish_crs({declared!r}) -> {panel_publish_crs(declared)!r}")

    try:
        canvas = comp.canvas
        out(f"  canvas type    = {type(canvas).__name__}")
        try:
            out(f"  canvas dest crs= {canvas.destination_crs()!r}")
        except Exception as exc:  # noqa: BLE001
            out(f"  canvas.destination_crs failed: {type(exc).__name__}: {exc}")
        for name in ("extent", "map_extent", "current_extent"):
            fn = getattr(canvas, name, None)
            if callable(fn):
                try:
                    out(f"  canvas.{name}()  = {fn()!r}")
                except Exception as exc:  # noqa: BLE001
                    out(f"  canvas.{name}() failed: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        out(f"  canvas probe failed: {type(exc).__name__}: {exc}")

    layers = list(getattr(comp.layer_manager, "_layers", []))
    out(f"  layer count = {len(layers)}")
    for layer in layers:
        meta = getattr(layer, "metadata", None) or {}
        feats = getattr(layer, "features", None)
        n = len(feats()) if callable(feats) else "?"
        out(f"    - {layer.name!r:44s} id={layer.id!r:24s} "
            f"role={meta.get('role', '')!r:32s} editable={meta.get('editable')!r:7s} "
            f"crs={getattr(layer, 'crs', None)!r} feats={n}")


def _readiness():
    from paleo_workbench.mapping_workspace.readiness import check_initial_facies_crs

    item = check_initial_facies_crs(win.project)
    return f"{item.status.value} {item.title} / {item.detail}"


out()
out("=== phase A: right after opening the project ===")
ok = False
try:
    ok = win.project_controller.open_project_path(PROJECT)
except Exception as exc:  # noqa: BLE001
    out(f"  open_project_path raised: {type(exc).__name__}: {exc}")
out(f"  open_project_path -> {ok}")
if not ok:
    out(f"  last_open_error = {getattr(win.project_controller, '_last_open_error', None)!r}")
snapshot("after open")

comp = win.app_shell.workstation.composite

out()
out("=== phase B: run mock seismic prediction ===")
try:
    comp.stage_actions.run_seismic_facies_mock()
    out("  run_seismic_facies_mock() returned")
except Exception as exc:  # noqa: BLE001
    out(f"  raised: {type(exc).__name__}: {exc}")
snapshot("after mock seismic")

out()
out("=== phase C: duplicate the seismic prediction layer ===")
target = None
for layer in list(getattr(comp.layer_manager, "_layers", [])):
    meta = getattr(layer, "metadata", None) or {}
    if meta.get("role") == "seismic_facies_prediction":
        target = layer
        break
if target is None:
    out("  no seismic_facies_prediction layer found -> cannot duplicate")
else:
    out(f"  target = {target.name!r} ({target.id})")
    try:
        comp._duplicate_vector_layer(target.id)
        out("  _duplicate_vector_layer() returned")
    except Exception as exc:  # noqa: BLE001
        out(f"  raised: {type(exc).__name__}: {exc}")
snapshot("after duplicate")

out()
out("=== phase D: what actually gets published to the canvas ===")
try:
    snap = comp.layer_manager._make_snapshot()
    out(f"  snapshot.project_crs = {snap.project_crs!r}")
    out(f"  snapshot layers = {len(snap.layers)}")
    for layer in snap.layers:
        out(f"    - {layer.name!r}")
        out(f"        id={layer.id!r} type={layer.layer_type!r} visible={layer.visible} "
            f"opacity={layer.opacity}")
        out(f"        crs={layer.crs!r} extent={layer.extent!r} "
            f"scale_range={layer.scale_range!r}")
        out(f"        data_rev={layer.data_revision} style_rev={layer.style_revision} "
            f"features={len(layer.features)}")
        out(f"        style keys={sorted(layer.style)!r} "
            f"renderer_payload={'set' if layer.renderer_payload is not None else None}")
except Exception as exc:  # noqa: BLE001
    out(f"  snapshot probe failed: {type(exc).__name__}: {exc}")

out()
out("=== phase E: per-layer view state from the edit authority ===")
try:
    ctl = comp.edit_controller
    for layer in ctl.snapshot_layers():
        out(f"  {layer.name!r}: visible={getattr(layer, 'visible', None)} "
            f"opacity={getattr(layer, 'opacity', None)} "
            f"features={len(layer.features()) if hasattr(layer, 'features') else '?'} "
            f"style={getattr(layer, 'style', None)!r}")
except Exception as exc:  # noqa: BLE001
    out(f"  edit-controller probe failed: {type(exc).__name__}: {exc}")

out()
out("DONE")
_fh.close()
print("done")
