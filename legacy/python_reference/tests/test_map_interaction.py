"""Selection and snapping are cached host-side geometry operations."""

from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex, SnappingService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _layer() -> VectorLayer:
    return VectorLayer(
        id="facies",
        name="Facies",
        features=[
            VectorFeature(
                "polygon",
                {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
            ),
            VectorFeature("line", {"type": "LineString", "coordinates": [[20, 0], [30, 0]]}),
        ],
    )


def test_spatial_index_selects_geometry_and_vertices_by_stable_feature_id() -> None:
    index = FeatureSpatialIndex(_layer())

    assert index.identify((5, 5), tolerance=0.5) == "polygon"
    assert index.identify((25, 0.2), tolerance=0.5) == "line"
    assert index.identify_vertex((10.1, 0.1), tolerance=0.5) == ("polygon", (0, 1))
    assert index.select_rectangle((9, -1), (11, 1)) == {"polygon"}


def test_snapping_service_reuses_index_and_refreshes_after_edit_revision() -> None:
    layer = _layer()
    snapping = SnappingService()
    snapping.enabled = True
    snapping.modes = {"vertex"}

    assert snapping.snap((20.2, 0.1), tolerance=0.5, layers=[layer]) == (20.0, 0.0)
    first_index = snapping.index_for(layer)
    session = layer.start_editing()
    session.move_feature("line", 10, 0)

    assert snapping.snap((30.1, 0.1), tolerance=0.5, layers=[layer]) == (30.0, 0.0)
    assert snapping.index_for(layer) is first_index


def test_snap_modes_cover_endpoint_intersection_grid_reference_and_layer_configuration() -> None:
    layer = VectorLayer(
        id="lines",
        name="Lines",
        features=[
            VectorFeature("horizontal", {"type": "LineString", "coordinates": [[0, 5], [10, 5]]}),
            VectorFeature("vertical", {"type": "LineString", "coordinates": [[5, 0], [5, 10]]}),
        ],
    )
    snapping = SnappingService()
    snapping.enabled = True
    snapping.modes = {"endpoint"}
    assert snapping.snap((0.1, 5.1), tolerance=0.5, layers=[layer]) == (0.0, 5.0)

    snapping.modes = {"intersection"}
    assert snapping.snap((5.1, 5.1), tolerance=0.5, layers=[layer]) == (5.0, 5.0)

    snapping.modes = {"grid", "reference"}
    snapping.set_grid((2.0, 2.0))
    snapping.set_reference_points([(8.1, 8.1)])
    assert snapping.snap((4.2, 6.1), tolerance=0.5, layers=[layer]) == (4.0, 6.0)
    assert snapping.snap((8.2, 8.1), tolerance=0.5, layers=[layer]) == (8.1, 8.1)

    snapping.modes = {"vertex"}
    snapping.layer_enabled[layer.id] = False
    assert snapping.snap((0.1, 5.1), tolerance=0.5, layers=[layer]) == (0.1, 5.1)
