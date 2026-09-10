"""Minimal wipe: raw stack + mirror 4 layers + apply_project_xml + pump.

Usage: QT_QPA_PLATFORM=offscreen .venv/bin/python scratch/repro_apply_wipe.py
Exit 0 = GREEN (layers survive apply+pump), 1 = RED (wiped).
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

xml = open("/tmp/envelope.xml").read()
print(f"envelope bytes={len(xml)}")

stack = QgisMapStack()
stack.initialize()
canvas = stack.create_canvas()
project = ProjectManager("/tmp/repro_project_area/project_area.paleo.json").load()
snap = build_workarea_map_snapshot(project)
m, s, f = mirror_snapshot_to_stack(stack, canvas, snap, groups=True)
print(f"mirrored={len(m)} failures={f} proj={stack.project_layer_count()}")
stack.apply_project_xml(xml)
print(f"after apply (sync): proj={stack.project_layer_count()}")
for i in range(10):
    app.processEvents()
    time.sleep(0.1)
n = stack.project_layer_count()
print(f"after pump: proj={n}")
ok = n == len(snap.layers)
print("VERDICT:", "GREEN" if ok else "RED")
stack.shutdown()
sys.exit(0 if ok else 1)
