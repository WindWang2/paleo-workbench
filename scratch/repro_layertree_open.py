"""RED-loop repro: open the real project_area copy, assert base.reference tree.

Usage (repo root):
  QT_QPA_PLATFORM=offscreen .venv/bin/python scratch/repro_layertree_open.py [--patch-extent-fit]

Exit 0 = GREEN (base.reference group present and holds workarea layers).
Exit 1 = RED (group missing or empty of workarea layers).
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATCH = "--patch-extent-fit" in sys.argv

if PATCH:
    import paleo_workbench.mapping.qgis_mirror as _qm

    _qm._extent_fits_crs = lambda crs, extent: True  # noqa: E731
    print("[repro] monkeypatched qgis_mirror._extent_fits_crs -> always True")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

PROJECT_JSON = "/tmp/repro_project_area/project_area.paleo.json"

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.mapping_workspace.layer_groups import BASE_REFERENCE_GROUP_ID

project = ProjectManager(PROJECT_JSON).load()
doc = CompositeDocument(project)
doc.resize(900, 600)
doc.show()

deadline = time.monotonic() + 3.0
while time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.02)

# ---- six diagnostics ----
print(f"[diag1] len(_base_layers)={len(doc._base_layers)}")
print(f"[diag1] base ids={[l.id for l in doc._base_layers]}")
for layer in doc._base_layers:
    print(f"[diag1] layer id={layer.id} crs={getattr(layer, 'crs', '')!r} "
          f"extent={getattr(layer, 'extent', None)} nfeat={len(getattr(layer, 'features', ()))})")

gc = doc.stage_controller.group_controller
print(f"[diag2] groups_available={gc.groups_available}")
print(f"[diag2] memberships={dict(getattr(gc.state, 'memberships', {}))}")

desired = gc.build_desired_tree(list(doc.layer_manager._layers))
roots = [(n.group_id if hasattr(n, 'group_id') else getattr(n, 'layer_id', '?'),
          type(n).__name__) for n in desired.children]
print(f"[diag3] desired roots={roots}")
for n in desired.children:
    gid = getattr(n, 'group_id', None)
    if gid == BASE_REFERENCE_GROUP_ID:
        print(f"[diag3] desired base.reference children="
              f"{[getattr(c, 'layer_id', getattr(c, 'group_id', '?')) for c in n.children]}")

stack = doc.canvas.stack
addr = doc.canvas.canvas_address
try:
    canvas_n = stack.canvas_layer_count(addr)
except Exception as exc:
    canvas_n = f"<err {exc}>"
try:
    proj_n = stack.project_layer_count()
except Exception as exc:
    proj_n = f"<err {exc}>"
print(f"[diag4] canvas_layers={canvas_n} project_layers={proj_n} "
      f"uses_native_stack={doc.uses_native_stack}")

try:
    payload = json.loads(stack.tree_snapshot_json())
    top = [(n.get("type"), n.get("id")) for n in payload.get("children", [])]
    print(f"[diag5] tree top={top}")
    for node in payload.get("children", []):
        if node.get("id") == BASE_REFERENCE_GROUP_ID:
            print(f"[diag5] base.reference children="
                  f"{[(c.get('type'), c.get('id')) for c in node.get('children', [])]}")
except Exception as exc:
    print(f"[diag5] tree_snapshot_json err: {exc}")

print(f"[diag6] mirror_failures={getattr(doc.canvas, '_mirror_failures', None)}")
try:
    print(f"[diag6] backend_status={doc.canvas.backend_status!r}")
except Exception as exc:
    print(f"[diag6] backend_status err: {exc}")
print(f"[diag6] project_crs={getattr(doc.edit_controller, 'project_crs', None)!r}")
from paleo_workbench.mapping.workarea_map_snapshot import (
    build_workarea_map_snapshot, workarea_view_extent)
snap = build_workarea_map_snapshot(project)
print(f"[diag6] snapshot.project_crs={snap.project_crs!r} "
      f"view_extent={workarea_view_extent(snap)}")

# ---- verdict ----
def check_tree(tag: str) -> bool:
    ok = False
    detail = ""
    try:
        payload = json.loads(stack.tree_snapshot_json())
        base = [n for n in payload.get("children", [])
                if n.get("id") == BASE_REFERENCE_GROUP_ID]
        if base:
            kids = {c.get("id") for c in base[0].get("children", [])}
            want = {"home_workarea:boundary"} | (
                {lid for lid in ("home_workarea:wells", "home_workarea:wells_flagged")
                 if lid in [l.id for l in doc._base_layers]})
            missing = want - kids
            ok = not missing
            detail = f"kids={sorted(kids)} want={sorted(want)} missing={sorted(missing)}"
        else:
            detail = "base.reference group ABSENT from tree"
    except Exception as exc:
        detail = f"snapshot err: {exc}"
    print(f"VERDICT[{tag}]:", "GREEN" if ok else "RED", detail)
    return ok


def pump(seconds: float = 1.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def dump_state(tag: str) -> None:
    gc = doc.stage_controller.group_controller
    print(f"[{tag} diag2] memberships={sorted(getattr(gc.state, 'memberships', {}))}")
    desired = gc.build_desired_tree(list(doc.layer_manager._layers))
    for n in desired.children:
        if getattr(n, 'group_id', None) == BASE_REFERENCE_GROUP_ID:
            print(f"[{tag} diag3] desired base kids="
                  f"{[getattr(c, 'layer_id', getattr(c, 'group_id', '?')) for c in n.children]}")
    try:
        canvas_n = stack.canvas_layer_count(addr)
    except Exception as exc:
        canvas_n = f"<err {exc}>"
    try:
        proj_n = stack.project_layer_count()
    except Exception as exc:
        proj_n = f"<err {exc}>"
    print(f"[{tag} diag4] canvas_layers={canvas_n} project_layers={proj_n}")
    try:
        payload = json.loads(stack.tree_snapshot_json())
        top = [(n.get("type"), n.get("id")) for n in payload.get("children", [])]
        print(f"[{tag} diag5] tree top={top}")
        for node in payload.get("children", []):
            if node.get("id") == BASE_REFERENCE_GROUP_ID:
                print(f"[{tag} diag5] base kids="
                      f"{[(c.get('type'), c.get('id')) for c in node.get('children', [])]}")
    except Exception as exc:
        print(f"[{tag} diag5] err: {exc}")
    print(f"[{tag} diag6] mirror_failures={getattr(doc.canvas, '_mirror_failures', None)}")
    try:
        print(f"[{tag} diag6] backend_status={doc.canvas.backend_status!r}")
    except Exception as exc:
        print(f"[{tag} diag6] backend_status err: {exc}")


results = [check_tree("open")]
if "--reopen" in sys.argv:
    if "--no-observe" in sys.argv:
        _gc = doc.stage_controller.group_controller
        _gc.observe_tree_nodes = lambda nodes: True
        print("[repro] monkeypatched group_controller.observe_tree_nodes -> no-op True")
    import paleo_workbench.mapping.qgis_mirror as _qm

    _orig_mirror = _qm.mirror_snapshot_to_stack

    def _spy(stack, addr, snapshot, diags=None, **kw):
        print(f"[spy] publish: n_layers={len(snapshot.layers)} "
              f"ids={[l.id for l in snapshot.layers]} "
              f"crs={getattr(snapshot, 'project_crs', '')!r} groups={kw.get('groups')}")
        out = _orig_mirror(stack, addr, snapshot, diags, **kw)
        print(f"[spy] result: mirrored={len(out[0])} seen={out[1]} failures={out[2]}")
        print(f"[spy] ledger_entries={len(_qm._MIRROR_LEDGER)}")
        return out

    _qm.mirror_snapshot_to_stack = _spy
    # canvas_shim holds its own reference (from ...ui.qgis_stack.mirror import)
    import paleo_workbench.ui.qgis_stack.canvas_shim as _shim_mod

    _shim_mod.mirror_snapshot_to_stack = _spy
    import traceback as _tb

    _doc = doc

    def _counted(name, obj, meth):
        _orig = getattr(obj, meth)

        def _wrap(*a, **k):
            before = stack.project_layer_count()
            r = _orig(*a, **k)
            after = stack.project_layer_count()
            flag = "  <-- CHANGED" if before != after else ""
            print(f"[phase] {name}: proj {before}->{after}{flag}")
            return r

        # instance attribute assignment may fail on some Qt objects; fall back
        try:
            setattr(obj, meth, _wrap)
        except AttributeError:
            print(f"[phase] cannot wrap {name}")
        return _orig

    _counted("load_from_project", _doc.edit_controller, "load_from_project")
    _counted("sync_composition_now", _doc, "_sync_composition_now")
    _counted("layer_publish", _doc.layer_manager, "_publish")
    _counted("shim_set_snapshot", _doc.canvas, "set_layer_snapshot")
    _counted("canvas_set_extent", _doc.canvas, "set_extent")
    _counted("write_xml", _doc, "_write_map_project_xml")
    _counted("restore_stage_view", _doc.stage_controller, "restore_stage_view")
    _counted("stage_sync_composition", _doc.stage_controller, "sync_composition")
    _counted("reconcile", _doc.stage_controller.group_controller, "reconcile")
    _counted("on_tree_struct", _doc, "_on_tree_structure_changed")
    try:
        _counted("expand_groups", _doc.layer_manager, "expand_layer_groups")
    except Exception as exc:
        print(f"[phase] expand wrap note: {exc}")
    _counted("input_refresh", _doc.input_tree, "refresh")
    _counted("panel_tree_change", _doc.layer_manager, "_on_tree_change")
    _counted("observe", _doc.stage_controller.group_controller, "observe_tree_nodes")
    _counted("apply_tree", _doc.stage_controller.group_controller, "_apply_tree")
    _counted("notify_display", _doc, "notify_display_changed")
    print(f"[spy] proj_before_reopen={stack.project_layer_count()}")
    doc.set_project(project)  # 第二次打开同一工程
    import sys as _sys

    _SUSPECT = {"remove_mirror_layers_except", "clear_project_layers",
                "remove_layer", "remove_groups_except", "apply_project_xml",
                "move_layer_to_group", "shutdown", "observe_tree_nodes",
                "reconcile", "_apply_tree", "_on_tree_change",
                "mirror_snapshot_to_stack", "upsert_mirror_layer",
                "set_mirror_layer_order", "_place_all", "_place_delta",
                "sync_composition", "_sync_composition_now", "_publish",
                "set_layer_snapshot", "apply_group_expanded",
                "apply_stage_visibility", "set_group_visibility"}
    _counts = {}
    _last = {"n": stack.project_layer_count()}

    def _tracer(frame, event, arg):
        if event == "call":
            name = frame.f_code.co_name
            if name in _SUSPECT:
                mod = frame.f_globals.get("__name__", "?")
                print(f"[trace] call {mod}.{name} proj={stack.project_layer_count()}")
            _counts[id(frame)] = stack.project_layer_count()
        elif event == "return":
            before = _counts.pop(id(frame), None)
            if before is not None:
                after = stack.project_layer_count()
                if after != before:
                    print(f"[trace] DROP inside {frame.f_code.co_name} "
                          f"({frame.f_code.co_filename.split('/')[-1]}:"
                          f"{frame.f_lineno}): proj {before}->{after}")
        return _tracer

    from PySide6.QtCore import QTimer as _QTimer

    _ticks = {"n": 0}

    def _poll():
        _ticks["n"] += 1
        print(f"[poll] t={_ticks['n'] * 100}ms proj={stack.project_layer_count()} "
              f"timer_active={doc._composition_timer.isActive()}")
        if _ticks["n"] < 15:
            _QTimer.singleShot(100, _poll)

    _QTimer.singleShot(100, _poll)
    _sys.settrace(_tracer)
    try:
        pump(2.0)
    finally:
        _sys.settrace(None)
    print(f"[reopen diag1] len(_base_layers)={len(doc._base_layers)} "
          f"manager_layers={[l.id for l in doc.layer_manager._layers]}")
    dump_state("reopen")
    results.append(check_tree("reopen"))
if "--stages" in sys.argv:
    from paleo_workbench.mapping_workspace.stages import MappingStage

    for stage in MappingStage:
        doc.stage_controller.set_stage(stage)
        pump(0.5)
        results.append(check_tree(f"stage={stage.value}"))
print("OVERALL:", "GREEN" if all(results) else "RED")
sys.exit(0 if all(results) else 1)
