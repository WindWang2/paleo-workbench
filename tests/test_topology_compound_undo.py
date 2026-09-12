"""M5：Python 复合撤销组随共享节点传播一起退休。

跨层拓扑撤销改由原生 QgsVectorLayer::undoStack + 手势管理器承担。
"""
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def test_compound_undo_api_retired() -> None:
    assert not hasattr(TopologyService, "pending_compound")
    assert not hasattr(TopologyService, "undo_compound")
    assert not hasattr(TopologyService, "redo_compound")
    assert not hasattr(CompositeEditController, "_propagate_shared_vertex")
