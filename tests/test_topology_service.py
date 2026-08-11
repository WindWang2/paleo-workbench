"""Layer-based topology validation and opt-in shared-node editing."""

from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def test_topological_editing_updates_only_shared_vertices_in_map_layers() -> None:
    left = VectorLayer(
        id="left", name="Left", features=[
            VectorFeature("a", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
        ]
    )
    right = VectorLayer(
        id="right", name="Right", features=[
            VectorFeature("b", {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 0]]]})
        ]
    )
    other = VectorLayer(
        id="other", name="Other", features=[
            VectorFeature("c", {"type": "Point", "coordinates": [9, 9]})
        ]
    )
    left_session = left.start_editing()
    left_session.set_vertex("a", (0, 1), (1.5, 0))
    topology = TopologyService(enabled=True)

    result = topology.propagate_shared_vertex(
        [left, right, other], origin=(1, 0), replacement=(1.5, 0), skip=("left", "a", (0, 1))
    )

    assert right.edit_session.feature("b").geometry["coordinates"][0][0] == (1.5, 0.0)
    assert other.feature("c").geometry["coordinates"] == (9.0, 9.0)
    assert {layer_id for layer_id, _feature_id, _path in result.changed} == {"right"}


def test_topology_validation_reports_self_intersection_without_qgraphics_items() -> None:
    layer = VectorLayer(
        id="facies", name="Facies", features=[
            VectorFeature("bowtie", {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]})
        ]
    )

    issues = TopologyService().validate([layer])

    assert issues
    assert issues[0]["feature_id"] == "bowtie"
