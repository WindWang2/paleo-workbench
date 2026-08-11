"""Unified properties dialog changes presentation only."""

import layer_model_core

from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _layer():
    registry = layer_model_core.LayerRegistry()
    layer = registry.add_layer("facies", "Facies", layer_model_core.LayerType.Vector)
    layer.crs = "EPSG:3857"
    layer.source_ref = "catalog:working:facies"
    layer.set_metadata("algorithm", "manual")
    return layer


def test_layer_properties_has_one_common_sectioned_surface_and_emits_style(qtbot) -> None:
    layer = _layer()
    dialog = MapLayerPropertiesDialog(layer, style={"fill": "#123456", "labels": {"field": "name"}})
    qtbot.addWidget(dialog)
    received = []
    dialog.properties_applied.connect(lambda layer_id, payload: received.append((layer_id, payload)))

    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "General", "Source", "Symbology", "Labels", "Rendering", "Metadata / Provenance"
    ]
    dialog.name_edit.setText("Updated Facies")
    dialog.opacity_spin.setValue(0.35)
    dialog.label_field_edit.setText("facies")
    dialog.renderer_combo.setCurrentText("categorized")
    dialog.classification_field_edit.setText("facies")
    dialog.classes_edit.setPlainText('{"delta": "#e03131"}')
    dialog.apply()

    assert received[0][0] == "facies"
    assert received[0][1]["name"] == "Updated Facies"
    assert received[0][1]["opacity"] == 0.35
    assert received[0][1]["style"]["labels"]["field"] == "facies"
    assert received[0][1]["style"]["categories"]["delta"] == "#e03131"


def test_scalar_properties_change_native_display_style_without_grid_data_change(qtbot) -> None:
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 1.0], "grid_y": [0.0, 1.0],
            "grid_z": [[0.0, 1.0], [0.5, None]], "backend": "idw", "n_points": 3,
        },
        factor_name="Porosity", crs="EPSG:3857",
    )
    scene = MapScene()
    layer = scene.add_factor_grid(result, layer_id="porosity")
    scalar = scene.scalar_layer("porosity")
    assert scalar is not None
    data_revision = scalar.data_revision
    dialog = MapLayerPropertiesDialog(layer, style=scene.scalar_style("porosity"))
    qtbot.addWidget(dialog)
    received = []
    dialog.properties_applied.connect(lambda _id, payload: received.append(payload))

    dialog.color_ramp_combo.setCurrentText("grayscale")
    dialog.range_min_spin.setValue(0.1)
    dialog.range_max_spin.setValue(0.9)
    dialog.gamma_spin.setValue(1.5)
    dialog.apply()
    scalar_style = received[0]["scalar_style"]
    scene.set_scalar_style(
        "porosity",
        color_ramp_name=scalar_style["color_ramp"],
        color_range=tuple(scalar_style["color_range"]),
        gamma=scalar_style["gamma"],
        nodata=scalar_style["nodata"],
    )

    assert scalar.data_revision == data_revision
    assert scene.scalar_style("porosity") == {
        "color_ramp": "grayscale", "color_range": [0.1, 0.9], "gamma": 1.5,
        "nodata": "transparent",
    }
