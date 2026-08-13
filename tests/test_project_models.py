from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY


def test_package_imports():
    import paleo_workbench

    assert paleo_workbench.__version__ == "0.2.17a0"


def test_project_defaults_include_crs_and_empty_workflow():
    project = ProjectDocument.new(name="HZ26 Demo", region="惠州26区")

    assert project.meta.name == "HZ26 Demo"
    assert project.meta.region == "惠州26区"
    assert project.coordinate.project_crs == "EPSG:4326 / WGS84"
    assert project.coordinate.display_crs == "EPSG:4326 / WGS84"
    assert project.resources == []
    assert project.compilation_runs == []


def test_screen_inventory_includes_required_pages():
    page_ids = [page["id"] for page in SCREEN_INVENTORY["pages"]]

    assert page_ids == [
        "dashboard",
        "data",
        "well_log_prediction",
        "seismic_prediction",
        "sequence_framework",
        "stratigraphy_correlation",
        "visualization",
        "preparation",
        "paleomap",
        "qc_export",
    ]
