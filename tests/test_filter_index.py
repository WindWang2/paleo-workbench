from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.filter_index import FilterIndex


def _assets():
    return [
        ResourceItem(
            name="A1.las",
            path="/d/A1.las",
            type="well_log",
            format="las",
            status="indexed",
        ),
        ResourceItem(
            name="cube.sgy",
            path="/d/cube.sgy",
            type="seismic",
            format="sgy",
            status="missing",
        ),
        ExportArtifact(linked_id="m1", format="PDF", output_path="/d/map.pdf"),
    ]


def test_filter_all_returns_all_indices():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("全部", "") == [0, 1, 2]


def test_filter_category_well_log():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("测井", "") == [0]


def test_filter_search_substring():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("全部", "cube") == [1]


def test_filter_category_then_search():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("测井", "A1") == [0]
    assert idx.filter("测井", "cube") == []


def test_filter_issues_category():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("异常", "") == [1]
