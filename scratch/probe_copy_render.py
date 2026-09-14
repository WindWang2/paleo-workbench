"""复现探针：复制图层后画布不显示。

复刻 app 链路的 headless 版：
  duplicate_layer → snapshot_layers → mirror_snapshot_to_stack(groups=True)
  → stage_controller.sync_composition()（ensure_memberships / reconcile /
  apply_stage_visibility）

输出到 .workbuddy/copy_render_probe.txt：
  - 复制前后 QGIS 树（含可见性）
  - 副本的 membership 归类结果
  - 镜像层要素数 / 可见性
  - 画布 zoom_to_full_extent 后的 scale/extent
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "copy_render_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()
    print(line)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from paleo_workbench.qgis_runtime.loader import prepare_bridge_load  # noqa: E402

try:
    prepare_bridge_load()
except Exception as exc:  # pragma: no cover - probe only
    out(f"prepare_bridge_load warning: {exc}")

from qgis_render_bridge.mapstack import QgisMapStack  # noqa: E402

stack = QgisMapStack()
stack.initialize()
addr = stack.create_canvas()

from paleo_workbench.mapping import qgis_mirror  # noqa: E402
from paleo_workbench.mapping.vector_layer import VectorFeature  # noqa: E402
from paleo_workbench.mapping_workspace.controller import (  # noqa: E402
    MappingStageController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole  # noqa: E402
from paleo_workbench.mapping_workspace.stages import MappingStage  # noqa: E402
from paleo_workbench.ui.workstation.composite_editing import (  # noqa: E402
    CompositeEditController,
)

PROJECT_CRS = "EPSG:4326"  # app 状态栏所示工程 CRS
# app 的 mock 数据坐标量级（X≈23003, Y≈5921，超出度域）
RING = [[23000.0, 5900.0], [23100.0, 5900.0], [23100.0, 6000.0],
        [23000.0, 6000.0], [23000.0, 5900.0]]
FEAT = {"type": "Polygon", "coordinates": [RING]}

edit = CompositeEditController(project_crs=PROJECT_CRS)
stage = MappingStageController()
stage.set_stage(MappingStage.FACIES_CALIBRATION)
stage.set_snapshot_provider(edit.snapshot_layers)

canvas_like = SimpleNamespace(stack=stack, canvas_address=addr)
stage.group_controller.attach_canvas(canvas_like)

source = edit.create_layer(
    "地震相面预测（mock）·C3", "polygon",
    role=LayerRole.SEISMIC_FACIES_PREDICTION)
edit.import_layer_features(source.id, [
    VectorFeature(feature_id="f1", geometry=dict(FEAT),
                  attributes={"facies_name": "三角洲前缘"}),
])
# 与 _create_role_layer 相同：显式注册角色成员资格
stage.group_controller.register_layer(
    source.id, LayerRole.SEISMIC_FACIES_PREDICTION, factor_task_id="task-1")


def publish_and_reconcile(tag: str) -> None:
    snaps = list(edit.snapshot_layers())
    snapshot = SimpleNamespace(project_crs=edit.project_crs, layers=snaps)
    diags: list = []
    ids, seen, failures = qgis_mirror.mirror_snapshot_to_stack(
        stack, addr, snapshot, diags=diags, groups=True)
    out(f"--- [{tag}] mirror ---")
    out(f"mirrored={ids}")
    out(f"seen={seen}")
    out(f"failures={failures}")
    for d in diags:
        out(f"diag: {d}")
    stage.sync_composition()
    out(f"--- [{tag}] tree ---")
    tree = json.loads(stack.tree_snapshot_json())

    def walk(nodes, depth=0):
        for node in nodes:
            vis = node.get("visible")
            out(f"{'  ' * depth}{node['type']:6s} {node['id']:36s} "
                f"name={node.get('name')!r} visible={vis}")
            walk(node.get("children") or [], depth + 1)

    walk(tree["children"])
    for lid in seen:
        try:
            feats = stack.mirror_features_json(lid)
            n = len(json.loads(feats).get("features", []))
        except Exception as exc:
            n = f"<err {exc}>"
        try:
            vis = stack.mirror_layer_visibility(lid)
        except Exception as exc:
            vis = f"<err {exc}>"
        out(f"layer {lid}: features={n} visible={vis}")
    mem = stage.state.membership
    for lid in seen:
        m = mem(lid)
        out(f"membership {lid}: role={getattr(m, 'role', None) if m else None}")
    stack.zoom_to_full_extent(addr)
    out(f"canvas scale={stack.canvas_scale(addr)} "
        f"extent={stack.canvas_extent(addr)} crs={stack.canvas_destination_crs(addr)}")
    out()


publish_and_reconcile("before duplicate")

# === 复制：走真实宿主处理器 composite_document._duplicate_vector_layer ===
from paleo_workbench.ui.workstation.composite_document import CompositeDocument  # noqa: E402


class _Host:
    edit_controller = edit
    stage_controller = stage
    _project = object()

    class status_message:
        @classmethod
        def emit(cls, text: str) -> None:
            out(f"status: {text}")


CompositeDocument._duplicate_vector_layer(_Host(), source.id)
copy = next(l for l in edit._layers.values() if l.name.endswith(" 副本"))
out(f"copy created: id={copy.id} name={copy.name!r} crs={copy.crs!r} "
    f"features={len(list(copy.features()))}")
out()

publish_and_reconcile("after duplicate")

stack.shutdown()
out("DONE")
