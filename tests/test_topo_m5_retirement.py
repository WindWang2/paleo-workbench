# -*- coding: utf-8 -*-
"""拓扑编辑迁移 M5：Python 拓扑服务退休（规格 §8 → §2）。

原生顶点上线即停 ``propagate_shared_vertex``；``CompoundUndoGroup`` 被
手势管理器替代。本文件钉生产路径无双轨残留。悬挂点规则不在 M5。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping import topology as topology_mod
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController
from paleo_workbench.ui.pages import mapping_page


def test_python_vertex_paths_do_not_call_shared_vertex_propagate() -> None:
    """工作站 / 编图页顶点路径不再挂 Python 共享节点传播。"""
    import inspect

    editing_src = inspect.getsource(CompositeEditController.activate_tool)
    assert "_propagate_shared_vertex" not in editing_src
    page_src = inspect.getsource(mapping_page.MappingPage)
    assert "propagate_shared_vertex" not in page_src


def test_no_python_propagation_api_on_topology_service() -> None:
    assert not hasattr(topology_mod.TopologyService, "propagate_shared_vertex")
    assert "CompoundUndoGroup" not in topology_mod.__all__


def test_production_modules_have_no_python_propagation_dual_track() -> None:
    root = Path(__file__).resolve().parents[1] / "paleo_workbench"
    needles = ("propagate_shared_vertex", "CompoundUndoGroup", "pending_compound")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(needle in text for needle in needles):
            offenders.append(str(path.relative_to(root.parent)))
    assert offenders == []
