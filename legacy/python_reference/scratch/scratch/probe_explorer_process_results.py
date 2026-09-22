"""Verify the new 「过程成果」group in the explorer's 历史与成果 view.

Builds a minimal fake project carrying ProjectDocument.mapping_workspace (the
shape composite_document._sync_workspace_state_to_project writes) and inspects
the tree spec WorkstationExplorer._spec_history() produces.

Writes .workbuddy/explorer_process_results.txt
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = REPO / ".workbuddy" / "explorer_process_results.txt"


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


OUT.write_text("", encoding="utf-8")

import paleo_workbench  # noqa: E402,F401
from PySide6.QtWidgets import QApplication  # noqa: E402

from paleo_workbench.mapping_workspace.layer_roles import LayerRole  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def membership(role: LayerRole, pinned: str = "") -> SimpleNamespace:
    return SimpleNamespace(role=role, source_version_id=pinned, layer_id="x")


def layer(layer_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=layer_id, name=name)


def build_project(with_workspace: bool) -> SimpleNamespace:
    layers = [
        layer("L1", "初始相图 校正稿"),
        layer("L2", "综合沉积相（草稿）"),
        layer("L3", "岸线约束"),
    ]
    if not with_workspace:
        return SimpleNamespace(
            meta=SimpleNamespace(name="测试工程"),
            user_vector_layers=layers,
            paleomap_documents=[],
            horizon_interpretations=[],
            export_artifacts=[],
            mapping_workspace=None,
        )
    workspace = SimpleNamespace(
        memberships={
            "L1": membership(LayerRole.INITIAL_FACIES_DRAFT, "ver_raw_0001"),
            "L2": membership(LayerRole.INTEGRATED_FACIES),
            "L3": membership(LayerRole.PALEO_SHORELINE),
        },
        # 键的约定是 "<kind>:<layer_id>"（create_facies_draft 的写法）
        artifact_maturity={
            "phase1_draft:L1": "draft",
            "integrated:L2": "reviewed",
            "constraint:L3": "frozen",
        },
    )
    return SimpleNamespace(
        meta=SimpleNamespace(name="测试工程"),
        user_vector_layers=layers,
        paleomap_documents=[],
        horizon_interpretations=[],
        export_artifacts=[],
        mapping_workspace=workspace,
    )


def walk(nodes, depth=0):
    for node in nodes:
        log("  " * depth + f"- [{node.payload.get('kind', '?')}] {node.label}")
        if node.tooltip:
            log("  " * depth + f"    tooltip: {node.tooltip.replace(chr(10), ' | ')}")
        walk(getattr(node, "children", []) or [], depth + 1)


from paleo_workbench.ui.workstation.explorer import WorkstationExplorer  # noqa: E402

log("=== A. project WITH mapping_workspace ===")
explorer = WorkstationExplorer(project=build_project(True))
walk(explorer._spec_history())

log("")
log("=== B. project WITHOUT mapping_workspace (old project / none open) ===")
explorer2 = WorkstationExplorer(project=build_project(False))
walk(explorer2._spec_history())

log("")
log("=== END ===")
