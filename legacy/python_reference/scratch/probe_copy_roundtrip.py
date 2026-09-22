"""复制 → 保存 → 重开 往返探针：副本在经过持久化往返后还能不能渲染。

app 里源层用户可见、副本重启后不可见且落「未分类」。怀疑：
  (a) 副本未持久化角色（UserVectorLayer 无 role 字段），重开后靠
      mapping_workspace memberships 恢复；
  (b) 样式 dict 持久化往返丢失（qgis_style renderer_xml）；
  (c) 分类器读不到角色 → 兜底进 legacy 组且样式为空 → 不渲染。

流程：project_area → 建源层（mock 风格，工区坐标域）→ duplicate →
保存工程（工程文件写副本，先备份）→ 重开工程 → 导出 PNG 对照。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "copy_roundtrip_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()
    print(line)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

SRC = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")
# 工作在工程文件副本上，绝不污染真工程
WORK = Path(tempfile.mkdtemp(prefix="paleo_rt_")) / SRC.name
shutil.copy(SRC, WORK)
out(f"work copy: {WORK}")

from paleo_workbench.project.manager import ProjectManager  # noqa: E402


def build_doc(path):
    project = ProjectManager(path).load()
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    doc = CompositeDocument(project)
    doc.resize(1200, 800)
    doc.show()
    app.processEvents()
    return doc


def dump(doc, tag):
    out(f"--- [{tag}] ---")
    canvas = doc.canvas
    stack = getattr(canvas, "stack", None)
    addr = getattr(canvas, "canvas_address", 0)
    if stack is not None and addr:
        tree = json.loads(stack.tree_snapshot_json())

        def walk(nodes, depth=0):
            for node in nodes:
                out(f"{'  ' * depth}{node['type']:6s} {node.get('name')!r} "
                    f"visible={node.get('visible')}")
                walk(node.get("children") or [], depth + 1)

        walk(tree["children"])
        out(f"scale={stack.canvas_scale(addr)}")
    out(f"failures={getattr(canvas, '_mirror_failures', None)!r}")
    # 编辑控制器层样式快照
    for lid, layer in doc.edit_controller._layers.items():
        style = dict(layer.style or {})
        keys = sorted(style.keys())
        has_renderer = bool(
            isinstance(style.get("qgis_style"), dict)
            and str(style["qgis_style"].get("renderer_xml") or "").strip())
        out(f"layer {lid}: name={layer.name!r} crs={layer.crs!r} "
            f"features={len(list(layer.features()))} style_keys={keys} "
            f"qgis_renderer={has_renderer}")
    try:
        png = ROOT / ".workbuddy" / f"probe_rt_{tag}.png"
        canvas.export_png(str(png))
        out(f"png -> {png}")
    except Exception as exc:
        out(f"export_png failed: {exc!r}")
    out()


# 阶段 1：源 + 副本
doc1 = build_doc(WORK)
from paleo_workbench.mapping.vector_layer import VectorFeature  # noqa: E402
from paleo_workbench.mapping_workspace.layer_roles import LayerRole  # noqa: E402
from paleo_workbench.ui.workstation.stage_actions import _categorized_facies_style  # noqa: E402

POLYS = [
    ([(3000, 4000), (5000, 4000), (5000, 6000), (3000, 6000)], "三角洲前缘"),
    ([(5200, 4200), (7000, 4200), (7000, 5800), (5200, 5800)], "滨浅湖"),
]
features = [
    ({"type": "Polygon",
      "coordinates": [[list(pt) for pt in ring] + [list(ring[0])]]},
     {"facies_name": name, "horizon": "C3"})
    for ring, name in POLYS
]
src = doc1.edit_controller.create_layer(
    "地震相面预测（mock）·C3", "polygon",
    role=LayerRole.SEISMIC_FACIES_PREDICTION)
doc1.stage_controller.group_controller.register_layer(
    src.id, LayerRole.SEISMIC_FACIES_PREDICTION, factor_task_id="t1")
doc1.edit_controller.import_layer_features(src.id, [
    VectorFeature(feature_id=f"m{i}", geometry=g, attributes=dict(p))
    for i, (g, p) in enumerate(features)
])
style = _categorized_facies_style(features)
if style:
    doc1.edit_controller.set_layer_style(src.id, style)
doc1._sync_composition_now()
dump(doc1, "1_source")

copy = doc1.edit_controller.duplicate_layer(src.id)
out(f"copy: id={copy.id} name={copy.name!r}")
# 宿主层（本探针用现 cwd 代码 = 修复后）：RAW → INITIAL_FACIES_DRAFT
doc1._duplicate_vector_layer.__self__  # noqa 只是确认类存在
from paleo_workbench.ui.workstation.composite_document import CompositeDocument  # noqa: E402


class _H:
    edit_controller = doc1.edit_controller
    stage_controller = doc1.stage_controller
    _project = doc1._project

    class status_message:
        @classmethod
        def emit(cls, t): out(f"status: {t}")


CompositeDocument._duplicate_vector_layer(_H(), src.id)
copy = next(l for l in doc1.edit_controller._layers.values()
            if l.name.endswith(" 副本"))
m = doc1.stage_controller.state.membership(copy.id)
out(f"copy membership role={getattr(m, 'role', None)}")
doc1._sync_composition_now()
app.processEvents()
import time
time.sleep(1)
app.processEvents()
dump(doc1, "2_after_duplicate")

# 阶段 2：正常 flush（内部会 _sync_workspace_state_to_project）→ 保存
doc1.flush_edit_sessions()
doc1.edit_controller.sync_to_project(doc1._project)
ProjectManager(WORK).save(doc1._project)
out(f"saved. user_vector_layers in file:")
saved = json.loads(WORK.read_text(encoding="utf-8"))
for l in saved.get("user_vector_layers") or []:
    s = l.get("style") or {}
    qs = s.get("qgis_style") or {}
    out(f"  {l.get('name')!r} crs={l.get('crs')!r} feats={len(l.get('features') or [])} "
        f"style_keys={sorted(s.keys())} renderer_xml={'yes' if qs.get('renderer_xml') else 'NO'}")
mems = (saved.get("mapping_workspace") or {}).get("memberships") or {}
out(f"memberships persisted: {json.dumps(mems, ensure_ascii=False)[:400]}")
try:
    doc1.close()
    doc1.deleteLater()
    app.processEvents()
except Exception as exc:
    out(f"doc1 close: {exc!r}")

# 阶段 3：重开同一工程 → 副本应当还在且可见
doc2 = build_doc(WORK)
dump(doc2, "3_reloaded")
out("DONE")
