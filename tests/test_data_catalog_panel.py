from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel


def test_catalog_renders_categories(qtbot):
    panel = DataCatalogPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "DataCatalogPanel"
    assert "全部" in panel.category_labels
    assert "测井" in panel.category_labels
    assert "成果" in panel.category_labels


def test_catalog_updates_counts(qtbot):
    panel = DataCatalogPanel()
    qtbot.addWidget(panel)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        ),
        ResourceItem(
            name="cube.sgy",
            path="/tmp/cube.sgy",
            type="seismic",
            format="sgy",
        ),
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    panel.update_counts(resources, artifacts)

    assert panel.category_labels["全部"].text().endswith("3")
    assert panel.category_labels["测井"].text().endswith("1")
    assert panel.category_labels["成果"].text().endswith("1")
