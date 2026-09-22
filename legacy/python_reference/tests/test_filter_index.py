from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.filter_index import FilterIndex, compute_category_counts


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


def test_filter_search_chinese_type_label():
    """Haystack includes Chinese type labels (e.g. 测井数据 for well_log)."""
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("全部", "测井数据") == [0]
    assert idx.filter("全部", "地震数据") == [1]


def test_filter_category_then_search():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("测井", "A1") == [0]
    assert idx.filter("测井", "cube") == []


def test_filter_missing_status_in_all():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    # "异常" category removed; missing-status items show under "全部" and their type
    assert idx.filter("全部", "") == [0, 1, 2]


def _res(rtype: str, status: str = "indexed", role: str | None = None) -> ResourceItem:
    return ResourceItem(
        name=f"{rtype}",
        path=f"/x/{rtype}",
        type=rtype,
        format="dat",
        status=status,
        artifact_role=role,
    )


def test_counts_total_and_types():
    resources = [_res("well_log"), _res("well_log"), _res("seismic")]
    counts = compute_category_counts(resources, [])
    assert counts["全部"] == 3
    assert counts["测井"] == 2
    assert counts["地震"] == 1


def test_counts_artifacts_and_types():
    resources = [_res("well_log"), _res("horizon")]
    artifacts = [ExportArtifact(linked_id="x", format="tiff", output_path="/x.tif")]
    counts = compute_category_counts(resources, artifacts)
    assert counts["全部"] == 3  # 2 resources + 1 artifact
    assert counts["测井"] == 1
    assert counts["层位"] == 1


def test_counts_types_no_overlap():
    resources = [
        _res("well_log", status="missing"),
        _res("document"),
        _res("image_reference"),
    ]
    counts = compute_category_counts(resources, [])
    assert counts["全部"] == 3
    assert counts["测井"] == 1
    assert counts["文档"] == 1
    assert counts["影像"] == 1
    # No overlap: sum of type counts == total
    type_sum = sum(v for k, v in counts.items() if k != "全部")
    assert type_sum == 3
