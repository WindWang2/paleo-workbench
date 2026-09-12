"""Layer-based topology validation."""

from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def test_python_shared_vertex_propagation_retired() -> None:
    """M5：Python 共享节点传播已下线；校验面仍在。"""
    assert not hasattr(TopologyService, "propagate_shared_vertex")


def test_topology_validation_reports_self_intersection_without_qgraphics_items() -> None:
    layer = VectorLayer(
        id="facies", name="Facies", features=[
            VectorFeature("bowtie", {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]})
        ]
    )

    issues = TopologyService().validate([layer])

    assert issues
    assert issues[0]["feature_id"] == "bowtie"
