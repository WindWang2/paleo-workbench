"""Bisect: is the reopen wipe bridge-level (ledger no-op) or panel-level?

Raw QgisMapStack + mirror_snapshot_to_stack twice (2nd = ledger no-op),
no panels, no controllers.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from qgis_render_bridge.mapstack import QgisMapStack
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.mapping.workarea_map_snapshot import build_workarea_map_snapshot
from paleo_workbench.mapping.qgis_mirror import mirror_snapshot_to_stack

stack = QgisMapStack()
stack.initialize()
canvas = stack.create_canvas()

project = ProjectManager("/tmp/repro_project_area/project_area.paleo.json").load()
snap = build_workarea_map_snapshot(project)
print(f"snapshot layers={[l.id for l in snap.layers]} crs={snap.project_crs!r}")
print(f"revisions={[getattr(l, 'data_revision', None) for l in snap.layers]}")

m1, s1, f1 = mirror_snapshot_to_stack(stack, canvas, snap, groups=True)
print(f"pub1: mirrored={len(m1)} failures={f1} proj={stack.project_layer_count()}")
app.processEvents()
time.sleep(0.3)
print(f"after pump1: proj={stack.project_layer_count()}")

m2, s2, f2 = mirror_snapshot_to_stack(stack, canvas, snap, groups=True)
print(f"pub2: mirrored={len(m2)} seen={s2} failures={f2} proj={stack.project_layer_count()}")
for i in range(5):
    app.processEvents()
    time.sleep(0.2)
    print(f"pump2 t={(i + 1) * 200}ms proj={stack.project_layer_count()}")

ok = stack.project_layer_count() == len(snap.layers)
print("bisect1 mirror-only:", "GREEN" if ok else "RED")

# ---- bisect2: + group reconcile (ensure_memberships + reconcile), pump ----
from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController)
from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState


class _ShimLike:
    def __init__(self, stack, addr):
        self.stack = stack
        self.canvas_address = addr


state = MappingWorkspaceState()
gc = LayerGroupController(state)
gc.attach_canvas(_ShimLike(stack, canvas))
print(f"groups_available={gc.groups_available}")
gc.ensure_memberships(list(snap.layers))
gc.reconcile(list(snap.layers))
print(f"after reconcile: proj={stack.project_layer_count()}")
for i in range(5):
    app.processEvents()
    time.sleep(0.2)
    print(f"pump3 t={(i + 1) * 200}ms proj={stack.project_layer_count()}")

import json as _json
payload = _json.loads(stack.tree_snapshot_json())
base = [n for n in payload["children"] if n["id"] == "base.reference"]
print("base kids:", [(c.get("type"), c.get("id")) for c in base[0]["children"]] if base else "<absent>")
ok2 = bool(base) and len(base[0]["children"]) == len(snap.layers)
print("bisect2 +reconcile:", "GREEN" if ok2 else "RED")
print("VERDICT:", "GREEN" if (ok and ok2) else "RED")
stack.shutdown()
sys.exit(0 if (ok and ok2) else 1)
