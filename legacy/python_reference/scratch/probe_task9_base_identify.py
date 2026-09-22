# -*- coding: utf-8 -*-
"""Task 9 可行性探针（scratch，不写产品代码）：原生栈识别对基础镜像层的覆盖。

验证三件事（/tmp 副本工程 + offscreen 原生桥）：
  Q1. set_current_layer("home_workarea:wells_flagged") 是否被接受
      （桥对未知 doc_id 抛 invalid_argument；接受与否以回调 doc_id 为准）。
  Q2. 生产路径激活 identify（controller）后程序化点击井点，回调 JSON 的
      feature 标识是文档记录 id（wells:<well_id>）还是 Qgs 内部 fid 数字。
  Q3. 回调 feature_id 与 self._base_layers 记录 "id" 的对应关系
      （fidResolver 映射则顺序无关）。

关键教训：点击必须落在 shim._canvas_viewport()（真视口）；
widgets.canvas_viewport(shim.canvas) 在 QWidget 首包装下返回 None，
退化点到画布视图本身则工具链永远静默（bisect3 实证）。

运行：QT_QPA_PLATFORM=offscreen .venv/bin/python scratch/probe_task9_base_identify.py
成功标准：identify 回调到达且 layer_doc_id 为 wells_flagged 镜像层、
feature_id 为 "wells:<...>" 文档记录 id。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

SRC_DIR = "/home/kevin/projects/paleo_project/data/project_area"
TMP_ROOT = "/tmp/probe_task9"
TMP_DIR = os.path.join(TMP_ROOT, "project_area")


def log(*args):
    print("[probe]", *args, flush=True)


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    if os.path.isdir(TMP_ROOT):
        shutil.rmtree(TMP_ROOT)
    shutil.copytree(SRC_DIR, TMP_DIR)
    with open(os.path.join(TMP_DIR, "project_area.paleo.json"), encoding="utf-8") as fh:
        project = ProjectDocument.model_validate(json.load(fh))
    project.meta.project_root = TMP_DIR
    log("wells:", len(project.wells))

    app = QApplication.instance() or QApplication(sys.argv)
    document = CompositeDocument(project)
    document.resize(800, 600)
    document.show()
    app.processEvents()
    log("uses_native_stack:", document.uses_native_stack)
    if not document.uses_native_stack:
        log("NEEDS_CONTEXT: 原生栈不可用，探针无法继续")
        return 2
    base_ids = [layer.id for layer in document._base_layers]
    log("base layer ids:", base_ids)
    assert "home_workarea:wells_flagged" in base_ids, base_ids

    document._sync_composition_now()
    app.processEvents()
    t0 = time.time()
    while time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.05)

    flagged = next(
        layer for layer in document._base_layers
        if layer.id == "home_workarea:wells_flagged"
    )
    first = flagged.features[0]
    well_id = first.get("id")
    coords = first["geometry"]["coordinates"]
    well_name = (first.get("properties") or {}).get("name")
    log("target well:", well_id, well_name, coords)

    canvas = document.canvas
    log("mirrored_doc_ids:", getattr(canvas, "_mirrored_doc_ids", None))
    log("mirror_failures:", getattr(canvas, "_mirror_failures", None))
    # Q1 直接判定：桥级 set_current_layer 抛/不抛。
    try:
        canvas.stack.set_current_layer(canvas.canvas_address, "home_workarea:wells_flagged")
        log("Q1 bridge-level set_current_layer: ACCEPTED")
    except Exception as exc:  # noqa: BLE001
        log("Q1 bridge-level set_current_layer: REJECTED:", type(exc).__name__, exc)
        return 1
    try:
        canvas.stack.set_current_layer(canvas.canvas_address, "bogus:nope")
        log("Q1 control bogus: accepted (unexpected)")
    except Exception as exc:  # noqa: BLE001
        log("Q1 control bogus: rejected (expected):", type(exc).__name__)

    # 生产路径：current 指基础镜像层（不碰 edit_controller 活动层）→
    # controller 激活 identify（门禁 queryable>0 已放宽）→ 真视口点击。
    canvas.set_current_layer("home_workarea:wells_flagged")
    app.processEvents()
    raw: list = []
    routing_only = bool(os.environ.get("PROBE_ROUTING"))
    if not routing_only:
        canvas.stack.set_selection_callback(
            canvas.canvas_address,
            lambda action, payload: raw.append((action, json.loads(payload))))
        app.processEvents()
    else:
        log("routing-only mode: keep shim callback registration")
    signals: list = []
    canvas.native_identified.connect(signals.append)
    log("queryable_layer_count:", document.queryable_layer_count())
    document._on_command_requested("identify")
    app.processEvents()
    tool = document.edit_controller.tools.active_tool
    log("controller active_tool:", type(tool).__name__ if tool is not None else None,
        "tool_id:", getattr(tool, "tool_id", None))
    log("shim _last_native_tool:", getattr(canvas, "_last_native_tool", None))

    viewport = canvas._canvas_viewport()
    assert viewport is not None
    sx, sy = canvas.map_to_screen((float(coords[0]), float(coords[1])))
    log("click at:", (sx, sy), "viewport:", viewport.width(), viewport.height())
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(int(sx), int(sy)))
    t0 = time.time()
    while time.time() - t0 < 8 and not (raw or signals):
        app.processEvents()
        time.sleep(0.05)
    log("raw bridge callbacks:", [(a, p) for a, p in raw])
    log("native_identified signals:", signals)
    if routing_only:
        if signals and signals[-1].get("feature_id") == well_id:
            log("ROUTING PASS：shim 通道端到端可用")
            return 0
        log("NEEDS_CONTEXT：shim 路由异常")
        return 1
    if not raw:
        log("NEEDS_CONTEXT: 点击后 8s 无 identify 回调")
        return 1
    action, payload = raw[-1]
    ok_doc = payload.get("layer_doc_id") == "home_workarea:wells_flagged"
    ok_fid = payload.get("feature_id") == well_id
    log("Q1 current-layer accepted:", ok_doc)
    log("Q2 feature_id is doc record id:", ok_fid,
        "(got %r, want %r)" % (payload.get("feature_id"), well_id))
    hit = next((f for f in flagged.features if f.get("id") == payload.get("feature_id")), None)
    log("Q3 record lookup by feature_id:", "HIT" if hit is not None else "MISS",
        (hit.get("properties") or {}).get("name") if hit else None)
    if action == "identify" and ok_doc and ok_fid and hit is not None:
        log("PROBE PASS：原生栈可识别基础镜像层，回调键=文档记录 id")
    else:
        log("NEEDS_CONTEXT：回调语义与预期不符")
        return 1
    # 路由对照：恢复 shim 自身回调注册，同样点击应经 native_identified 到达。
    canvas.set_map_tool_controller(document.edit_controller.tools)
    app.processEvents()
    document._on_command_requested("identify")
    app.processEvents()
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(int(sx), int(sy)))
    t0 = time.time()
    while time.time() - t0 < 8 and not signals:
        app.processEvents()
        time.sleep(0.05)
    log("native_identified signals:", signals)
    log("panel rows pre-fix:", document.identify_results.tree.topLevelItemCount(),
        "(预期 0 = 待补缺口)")
    if signals and signals[-1].get("feature_id") == well_id:
        log("ROUTING PASS：shim 通道 + 生产激活路径端到端可用")
        return 0
    log("NEEDS_CONTEXT：shim 路由或二次激活异常")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
