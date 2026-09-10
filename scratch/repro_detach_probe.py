"""Probe: which transient-detach patterns survive a pump? (pre-fix baseline)"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from qgis_render_bridge.mapstack import QgisMapStack

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
     "properties": {}}]}


def fresh():
    s = QgisMapStack()
    s.initialize()
    c = s.create_canvas()
    return s, c


def mirror(s, doc="doc-a"):
    s.upsert_mirror_layer(doc, "L", "Point", "EPSG:4326",
                           json.dumps(_FC), "", "", "", True, 1.0)


def pump(n=5):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.1)


# A: guarded root->group move + pump (control, expect survive)
s, c = fresh()
mirror(s)
s.upsert_group("g1", "G1", "")
s.move_layer_to_group("doc-a", "g1", 0)
pump()
print("A guarded root->group:", s.project_layer_count(), "(expect 1)")
s.shutdown()

# C: move_group carrying a layer + pump
s, c = fresh()
mirror(s)
s.upsert_group("g1", "G1", "")
s.move_layer_to_group("doc-a", "g1", 0)
s.move_group("g1", "", 0)
pump()
print("C move_group with layer:", s.project_layer_count(), "(1=safe)")
s.shutdown()

# D: guarded group->root move (takeChild FROM subgroup) + pump
s, c = fresh()
mirror(s)
s.upsert_group("g1", "G1", "")
s.move_layer_to_group("doc-a", "g1", 0)
s.move_layer_to_group("doc-a", "", 0)
pump()
print("D guarded group->root:", s.project_layer_count(), "(1=safe)")
s.shutdown()
