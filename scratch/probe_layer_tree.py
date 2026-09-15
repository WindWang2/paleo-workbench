"""Which layers will the 图层管理 tree actually contain for project_area?

The layer manager binds (base work-area layers + reference layers + user
vector layers). For this project only the base snapshot can be non-empty.
Print its layer names so the user can match what they see on screen, and
state per layer whether the context menu would offer
「复制为草稿…」 (needs raw_protected) or 「开始编辑」 (needs editable).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")

OUT = ROOT / ".workbuddy" / "layer_tree_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


from paleo_workbench.project.manager import ProjectManager  # noqa: E402

project = ProjectManager(PROJECT).load()
out("=== base work-area layers (build_workarea_map_snapshot) ===")

from paleo_workbench.mapping.workarea_map_snapshot import (  # noqa: E402
    build_workarea_map_snapshot,
)

snap = build_workarea_map_snapshot(project)
if not snap.layers:
    out("  (none)")
for layer in snap.layers:
    feats = getattr(layer, "features", None) or ()
    out(f"  name={layer.name!r:24s} id={layer.id!r:24s} kind={getattr(layer, 'geometry_kind', '?')!r} features={len(feats)}")

out()
out("=== reference layers (workstation_reference_layers, vector only) ===")
refs = [
    layer
    for layer in (getattr(project, "workstation_reference_layers", None) or [])
    if getattr(layer, "source_kind", "") == "vector"
]
out(f"  count = {len(refs)}")
for r in refs:
    out(f"    {getattr(r, 'name', '?')!r}")

out()
out("=== user vector layers (edit_controller authority) ===")
out("  source: composite_document.set_project -> edit_controller.load_from_project(project)")
for attr in (
    "paleomap_documents",
    "horizon_interpretations",
    "constraint_layers",
    "contour_drafts",
    "prediction_tasks",
    "version_sets",
):
    v = getattr(project, attr, None)
    out(f"  project.{attr:24s} = {len(v) if v is not None else '<absent>'}")

out()
out("=== mapping_workspace memberships (stage/role layers) ===")
mw = getattr(project, "mapping_workspace", None)
if isinstance(mw, dict):
    members = mw.get("memberships") or []
    out(f"  memberships = {len(members)}")
    for m in members:
        out(f"    {m}")
else:
    out(f"  type = {type(mw).__name__}")

out()
out("=== paleomap_documents detail ===")
for doc in getattr(project, "paleomap_documents", None) or []:
    polys = getattr(doc, "facies_polygons", None) or []
    lines = getattr(doc, "line_features", None) or []
    labels = getattr(doc, "label_features", None) or []
    refs2 = getattr(doc, "reference_layers", None) or []
    out(f"  {getattr(doc, 'name', '?')!r}: facies_polygons={len(polys)} "
        f"line_features={len(lines)} label_features={len(labels)} "
        f"reference_layers={len(refs2)} overlays={len(getattr(doc, 'well_overlays', None) or [])}")

out()
out("=== verdict ===")
out("  raw_protected layer present?  -> determines whether 「复制为草稿…」 appears")
out("  editable layer present?       -> determines whether 「开始编辑」 appears")
out("  base layers (工区边界/地震工区/井位) are NEITHER -> only the read-only items show")

_fh.close()
print("done")
