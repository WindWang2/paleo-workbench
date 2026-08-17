"""Regressions for #651 (asset table sort) and #671 (adjacent_only flag)."""

from __future__ import annotations

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.asset_table_model import AssetTableModel
from paleo_workbench.workflow.correlation_session import adjacent_links_for_marker
from paleo_workbench.workflow.stratigraphy_models import FormationTop


def test_asset_table_sorts_size_version_and_type_by_meaning(qtbot) -> None:
    """#651: size/version must not sort formatted strings; type uses display label."""
    from PySide6.QtCore import Qt

    small = ResourceItem(
        name="small.las",
        path="small.las",
        type="well_log",
        format="las",
        parsed_summary={"size_bytes": 980_000_000},
    )
    large = ResourceItem(
        name="large.sgy",
        path="large.sgy",
        type="seismic",
        format="sgy",
        parsed_summary={"size_bytes": 1_000_000_000},
    )
    mid = ResourceItem(
        name="mid.las",
        path="mid.las",
        type="horizon",
        format="json",
        parsed_summary={"size_bytes": 500_000_000},
    )
    model = AssetTableModel()
    model.set_column_keys(["name", "size", "version", "type"])
    model.set_assets([small, large, mid])
    # Pin display labels that sort wrongly as strings (1.0 GB < 980 MB).
    model._views[0].size_bytes = 980 * 1024 * 1024
    model._views[0].size_formatted = "980 MB"
    model._views[0].current_version = "v10"
    model._views[1].size_bytes = 1024 * 1024 * 1024
    model._views[1].size_formatted = "1.0 GB"
    model._views[1].current_version = "v2 (10)"
    model._views[2].size_bytes = 500 * 1024
    model._views[2].size_formatted = "500 KB"
    model._views[2].current_version = "v2"

    model.sort(1, Qt.SortOrder.AscendingOrder)
    names = [model._views[i].name for i in model._filtered_rows]
    assert names == ["mid.las", "small.las", "large.sgy"]

    model.sort(2, Qt.SortOrder.AscendingOrder)
    versions = [model._views[i].current_version for i in model._filtered_rows]
    assert versions == ["v2", "v2 (10)", "v10"]

    model.sort(3, Qt.SortOrder.AscendingOrder)
    type_labels = [model._views[i].type_label for i in model._filtered_rows]
    assert type_labels == sorted(type_labels)


def test_gapped_correlation_links_are_not_marked_adjacent_only() -> None:
    """#671: well-order gaps must not persist adjacent_only=True."""
    tops = [
        FormationTop(id="tA", well_id="A", well_name="A", marker="H1", depth=100.0),
        FormationTop(id="tC", well_id="C", well_name="C", marker="H1", depth=110.0),
    ]
    links = adjacent_links_for_marker(tops, well_order=["A", "B", "C"])
    assert len(links) == 1
    assert links[0].adjacent_only is False

    adjacent = adjacent_links_for_marker(
        [
            FormationTop(id="tA", well_id="A", well_name="A", marker="H1", depth=100.0),
            FormationTop(id="tB", well_id="B", well_name="B", marker="H1", depth=105.0),
        ],
        well_order=["A", "B", "C"],
    )
    assert len(adjacent) == 1
    assert adjacent[0].adjacent_only is True
