# -*- coding: utf-8 -*-
"""Task 9 探针 bisect：裸画布 vs 文档画布 + 进程级污染检查。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

SRC_DIR = "/home/kevin/projects/paleo_project/data/project_area"
TMP_ROOT = "/tmp/probe_task9b"
TMP_DIR = os.path.join(TMP_ROOT, "project_area")

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "geometry": {"type": "Polygon", "coordinates":
                  [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]]},
     "properties": {"__pwb_fid": "f1", "name": "A"}}]}


def log(*args):
    print("[bisect]", *args, flush=True)


def click_identify(app, stack, addr, qtest_mod, point):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    import shiboken6
    from PySide6.QtWidgets import QGraphicsView
    w = shiboken6.wrapInstance(addr, QGraphicsView)
    vp = w.viewport()
    events: list = []
    stack.set_selection_callback(
        addr, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(addr, "identify")
    app.processEvents()
    scr = stack.map_to_screen(addr, point[0], point[1])
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(int(scr[0]), int(scr[1])))
    t0 = time.time()
    while time.time() - t0 < 5 and not events:
        app.processEvents()
        time.sleep(0.05)
    return events


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from qgis_render_bridge.mapstack import QgisMapStack

    app = QApplication.instance() or QApplication(sys.argv)
    stack = QgisMapStack()
    stack.initialize()

    # B1：裸画布（文档创建前）。
    import shiboken6
    from PySide6.QtWidgets import QGraphicsView
    addr1 = stack.create_canvas()
    w1 = shiboken6.wrapInstance(addr1, QGraphicsView)
    w1.resize(400, 400)
    w1.show()
    app.processEvents()
    stack.upsert_mirror_layer("doc-poly", "面", "Polygon", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(addr1, 0.0, 0.0, 10.0, 10.0)
    stack.set_current_layer(addr1, "doc-poly")
    ev1 = click_identify(app, stack, addr1, None, (6.5, 6.5))
    log("B1 bare-before-doc:", ev1)

    # 创建文档（含原生 shim 画布）。
    if os.path.isdir(TMP_ROOT):
        shutil.rmtree(TMP_ROOT)
    shutil.copytree(SRC_DIR, TMP_DIR)
    with open(os.path.join(TMP_DIR, "project_area.paleo.json"), encoding="utf-8") as fh:
        from paleo_workbench.project.models import ProjectDocument
        project = ProjectDocument.model_validate(json.load(fh))
    project.meta.project_root = TMP_DIR
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    document = CompositeDocument(project)
    document.resize(800, 600)
    document.show()
    app.processEvents()
    document._sync_composition_now()
    app.processEvents()
    t0 = time.time()
    while time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.05)

    # B2：同一进程再建裸画布（文档创建后，检查进程级污染）。
    addr2 = stack.create_canvas()
    w2 = shiboken6.wrapInstance(addr2, QGraphicsView)
    w2.resize(400, 400)
    w2.show()
    app.processEvents()
    stack.upsert_mirror_layer("doc-poly2", "面", "Polygon", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(addr2, 0.0, 0.0, 10.0, 10.0)
    stack.set_current_layer(addr2, "doc-poly2")
    ev2 = click_identify(app, stack, addr2, None, (6.5, 6.5))
    log("B2 bare-after-doc:", ev2)

    # B3：文档画布（shim 栈），桥级直连回调。
    shim = document.canvas
    raw: list = []
    shim.stack.set_current_layer(shim.canvas_address, "probe-doc-poly-x") \
        if False else None
    shim.stack.upsert_mirror_layer("probe-doc-poly", "面", "Polygon", "EPSG:4326",
                                   json.dumps(_FC), "", "", "", True, 1.0,
                                   is_reference=False, is_editable=True)
    shim.set_extent((0.0, 0.0, 10.0, 10.0))
    app.processEvents()
    shim.stack.set_current_layer(shim.canvas_address, "probe-doc-poly")
    shim.stack.set_selection_callback(
        shim.canvas_address,
        lambda action, payload: raw.append((action, json.loads(payload))))
    shim.stack.set_map_tool(shim.canvas_address, "identify")
    app.processEvents()
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from paleo_workbench.ui.qgis_stack.widgets import canvas_viewport
    vp = canvas_viewport(shim.canvas) or shim.canvas
    scr = shim.stack.map_to_screen(shim.canvas_address, 6.5, 6.5)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(int(scr[0]), int(scr[1])))
    t0 = time.time()
    while time.time() - t0 < 5 and not raw:
        app.processEvents()
        time.sleep(0.05)
    log("B3 doc-canvas-shim-stack:", raw)
    # B4：shim 的栈实例上建裸画布（顶层 show）——区分"栈实例级"与"画布实例级"。
    addr4 = shim.stack.create_canvas()
    w4 = shiboken6.wrapInstance(addr4, QGraphicsView)
    w4.resize(400, 400)
    w4.show()
    app.processEvents()
    shim.stack.upsert_mirror_layer("doc-poly4", "面", "Polygon", "EPSG:4326",
                                   json.dumps(_FC), "", "", "", True, 1.0,
                                   is_reference=False, is_editable=True)
    shim.stack.set_canvas_extent(addr4, 0.0, 0.0, 10.0, 10.0)
    shim.stack.set_current_layer(addr4, "doc-poly4")
    ev4 = click_identify(app, shim.stack, addr4, None, (6.5, 6.5))
    log("B4 bare-on-shim-stack:", ev4)
    stack.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
