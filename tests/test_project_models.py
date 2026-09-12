from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY


def test_package_imports():
    import paleo_workbench

    assert paleo_workbench.__version__ == "0.2.17a0"


def test_project_defaults_include_crs_and_empty_workflow():
    project = ProjectDocument.new(name="HZ26 Demo", region="惠州26区")

    assert project.meta.name == "HZ26 Demo"
    assert project.meta.region == "惠州26区"
    # 拓扑编辑迁移 M0 §6：新工程不预设地理 CRS——未声明即按本地坐标，
    # 首次导入数据按坐标范围推断（crs_contract.infer_crs_from_extent）。
    assert project.coordinate.project_crs == ""
    assert not project.coordinate.crs_locked
    assert project.coordinate.display_crs == "EPSG:4326 / WGS84"
    assert project.resources == []
    assert project.compilation_runs == []


def test_screen_inventory_includes_required_pages():
    """V7 D13：清单从 navigation 派生（旧 11 页硬编码与实际 UI 脱节）。"""
    hubs = {hub["name"]: hub["submodules"] for hub in SCREEN_INVENTORY["hubs"]}
    assert [entry[0] for entry in hubs["编图"]] == ["canvas", "preparation", "review"]
    assert [entry[0] for entry in hubs["数据"]] == ["overview", "management"]
    docks = SCREEN_INVENTORY["workstation"]["docks"]
    assert len(docks) == 13 and SCREEN_INVENTORY["workstation"]["central_document"] == "composite"
