"""像素级复现：真桥 + 真工程（project_area）离屏跑叠加地震相预测。

流程（与 app 一致）：
  CompositeDocument(project_area)  →  运行 mock 地震相预测  →  叠加地震相预测
  → 每层导出 PNG + 画布 scale/extent + 树快照 + 镜像失败列表。

输出 PNG 到 .workbuddy/probe_overlay_*.png，文本到
.workbuddy/overlay_probe.txt。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "overlay_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()
    print(line)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

PROJECT = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")

from paleo_workbench.project.manager import ProjectManager  # noqa: E402

project = ProjectManager(PROJECT).load()
out(f"project loaded: crs={project.coordinate.project_crs!r}")
wells = getattr(project, "wells", None) or []
surveys = getattr(project, "seismic_surveys", None) or []
horizons = getattr(project, "horizons", None) or getattr(project, "horizon_items", None) or []
tasks = getattr(project, "prediction_tasks", None) or []
out(f"wells={len(wells)} surveys={len(surveys)} "
    f"horizons={len(horizons)} tasks={len(tasks)}")

from paleo_workbench.ui.workstation.composite_document import CompositeDocument  # noqa: E402

doc = CompositeDocument(project)
doc.resize(1200, 800)
doc.show()
app.processEvents()

from paleo_workbench.ui.qgis_stack.canvas_shim import bridge_available  # noqa: E402

out(f"bridge_available={bridge_available()}")
canvas = doc.canvas
out(f"canvas class={type(canvas).__name__}")
if hasattr(canvas, "backend_status"):
    out(f"backend_status={canvas.backend_status!r}")
if hasattr(canvas, "_mirror_failures"):
    out(f"mirror_failures={canvas._mirror_failures!r}")


def dump_canvas(tag: str) -> None:
    out(f"--- [{tag}] ---")
    stack = getattr(canvas, "stack", None)
    addr = getattr(canvas, "canvas_address", 0)
    if stack is not None and addr:
        out(f"scale={stack.canvas_scale(addr)}")
        out(f"extent={stack.canvas_extent(addr)}")
        out(f"dest_crs={stack.canvas_destination_crs(addr)!r}")
        tree = json.loads(stack.tree_snapshot_json())

        def walk(nodes, depth=0):
            for node in nodes:
                out(f"{'  ' * depth}{node['type']:6s} {node.get('name')!r} "
                    f"id={node['id']!r} visible={node.get('visible')}")
                walk(node.get("children") or [], depth + 1)

        walk(tree["children"])
    if hasattr(canvas, "_mirror_failures"):
        out(f"mirror_failures={canvas._mirror_failures!r}")
    try:
        png = ROOT / ".workbuddy" / f"probe_overlay_{tag}.png"
        canvas.export_png(str(png))
        out(f"png -> {png}")
    except Exception as exc:
        out(f"export_png failed: {exc!r}")
    out()


dump_canvas("loaded")

# 设定编图层位（阶段条 C3 的等价物）：stratigraphy.target_horizon
horizon = ""
try:
    from paleo_workbench.workflow.stratigraphy import horizons_from_data

    options = horizons_from_data(project)
    out(f"horizon options: {options[:5]}")
    if options:
        project.stratigraphy.target_horizon = options[0]
        horizon = options[0]
        out(f"target horizon = {horizon!r}")
except Exception as exc:
    out(f"set horizon failed: {exc!r}")

# 1)+2) 直接复刻 _overlay_polygon_predictions 的建层链路（mock run 需编目
# 服务，离屏无；但叠加层本身是纯编辑控制器链路）：
#   create_layer(role=SEISMIC_FACIES_PREDICTION) → register_layer →
#   import polygon features（工区坐标域）→ _categorized_facies_style
from paleo_workbench.mapping.vector_layer import VectorFeature  # noqa: E402
from paleo_workbench.mapping_workspace.layer_roles import LayerRole  # noqa: E402
from paleo_workbench.ui.workstation.stage_actions import (  # noqa: E402
    _categorized_facies_style,
)

# 工区坐标域（地震工区内）：x 0..12793, y 0..16406 的局部坐标
POLYS = [
    ([(3000, 4000), (5000, 4000), (5000, 6000), (3000, 6000)], "三角洲前缘"),
    ([(5200, 4200), (7000, 4200), (7000, 5800), (5200, 5800)], "滨浅湖"),
    ([(7200, 4000), (9000, 4000), (9000, 6200), (7200, 6200)], "扇三角洲"),
]
features = [
    (
        {"type": "Polygon",
         "coordinates": [[list(pt) for pt in ring] + [list(ring[0])]]},
        {"facies_name": name, "horizon": "C3"},
    )
    for ring, name in POLYS
]

layer = doc.edit_controller.create_layer(
    "地震相面预测（mock）·C3", "polygon",
    role=LayerRole.SEISMIC_FACIES_PREDICTION)
doc.stage_controller.group_controller.register_layer(
    layer.id, LayerRole.SEISMIC_FACIES_PREDICTION, factor_task_id="task-mock")
doc.edit_controller.import_layer_features(layer.id, [
    VectorFeature(feature_id=f"mf{i}", geometry=geometry,
                  attributes=dict(props))
    for i, (geometry, props) in enumerate(features)
])
style = _categorized_facies_style(features)
out(f"categorized style: {json.dumps(style, ensure_ascii=False)[:400]}")
if style:
    doc.edit_controller.set_layer_style(layer.id, style)
doc._sync_composition_now()
app.processEvents()
import time
time.sleep(1)
app.processEvents()
dump_canvas("after_overlay")

# 3) 缩放到新图层再导一张
stack = getattr(canvas, "stack", None)
addr = getattr(canvas, "canvas_address", 0)
if stack is not None and addr:
    try:
        ids = json.loads(stack.tree_snapshot_json())
        target = None

        def find(nodes):
            global target
            for node in nodes:
                if "副本" not in str(node.get("name")) and node["type"] == "layer":
                    target = node["id"]
                find(node.get("children") or [])

        find(ids["children"])
        if target:
            stack.zoom_to_layer(addr, target)
            app.processEvents()
            import time
            time.sleep(1)
            app.processEvents()
            out(f"zoomed to {target!r}")
            png = ROOT / ".workbuddy" / "probe_overlay_zoomed.png"
            canvas.export_png(str(png))
            out(f"scale after zoom={stack.canvas_scale(addr)}")
    except Exception as exc:
        out(f"zoom/export failed: {exc!r}")

out("DONE")
