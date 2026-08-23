from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt

from paleo_workbench.resources.import_service import import_files
from paleo_workbench.ui.pages.filter_index import FilterIndex, FilterQuery
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


def _write_layer(
    path: Path,
    *,
    property_name: str,
    property_value: str,
    product_id: str | None = None,
) -> Path:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {property_name: property_value},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[0, 0], [1, 0], [1, 1], [0, 0]],
                    ],
                },
            }
        ],
    }
    if product_id:
        payload["metadata"] = {"product_id": product_id}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_geojson_import_records_vector_metadata(tmp_path):
    source = _write_layer(
        tmp_path / "regional_boundary.geojson",
        property_name="name",
        property_value="研究区",
    )

    report = import_files([source], existing=[])

    assert report.added_count == 1
    resource = report.added[0]
    assert resource.type == "geojson"
    assert resource.format == "geojson"
    assert resource.parsed_summary["geojson_valid"] is True
    assert resource.parsed_summary["feature_count"] == 1
    assert resource.parsed_summary["geometry_types"] == ["Polygon"]
    assert resource.artifact_role == "input"


def test_generic_json_feature_collection_is_managed_as_geojson(tmp_path):
    source = _write_layer(
        tmp_path / "delivery.json",
        property_name="name",
        property_value="研究区边界",
    )

    resource = import_files([source], existing=[]).added[0]

    assert resource.type == "geojson"
    assert resource.format == "json"
    assert resource.parsed_summary["geojson_valid"] is True


def test_three_facies_geojsons_form_one_complete_output_group(tmp_path):
    paths = [
        _write_layer(
            tmp_path / "tool-result_facies.geojson",
            property_name="facies",
            property_value="三角洲",
        ),
        _write_layer(
            tmp_path / "tool-result_subfacies.geojson",
            property_name="subfacies",
            property_value="三角洲前缘",
        ),
        _write_layer(
            tmp_path / "tool-result_microfacies.geojson",
            property_name="microfacies",
            property_value="水下分流河道",
        ),
    ]

    report = import_files(paths, existing=[])

    assert report.added_count == 3
    assert report.facies_product_count == 1
    assert "相图成果 1 组" in report.summary_text()
    by_role = {
        resource.parsed_summary["geojson_layer_role"]: resource
        for resource in report.added
    }
    assert set(by_role) == {"facies", "subfacies", "microfacies"}
    group_ids = {
        resource.parsed_summary["facies_product_group_id"]
        for resource in report.added
    }
    assert len(group_ids) == 1
    assert {
        resource.parsed_summary["geojson_layer_label"]
        for resource in report.added
    } == {"相", "亚相", "微相"}
    for resource in report.added:
        assert resource.parsed_summary["facies_product_complete"] is True
        assert resource.parsed_summary["facies_product_layer_count"] == 3
        assert resource.artifact_role == "output"
        assert "output" in resource.tags
        assert "facies-map" in resource.tags


def test_incomplete_facies_siblings_remain_inputs_and_warn(tmp_path):
    paths = [
        _write_layer(
            tmp_path / "result_相.geojson",
            property_name="facies",
            property_value="湖泊",
        ),
        _write_layer(
            tmp_path / "result_亚相.geojson",
            property_name="subfacies",
            property_value="滨浅湖",
        ),
    ]

    report = import_files(paths, existing=[])

    assert report.facies_product_count == 0
    assert len(report.warnings) == 1
    assert "缺少微相" in report.warnings[0]
    assert all(resource.artifact_role == "input" for resource in report.added)
    assert all(
        resource.parsed_summary["facies_product_complete"] is False
        for resource in report.added
    )


def test_malformed_named_layer_is_not_promoted_into_complete_product(tmp_path):
    paths = [
        _write_layer(
            tmp_path / "result_facies.geojson",
            property_name="facies",
            property_value="湖泊",
        ),
        _write_layer(
            tmp_path / "result_subfacies.geojson",
            property_name="subfacies",
            property_value="滨浅湖",
        ),
    ]
    malformed = tmp_path / "result_microfacies.geojson"
    malformed.write_text('{"type": "not-a-feature-collection"}', encoding="utf-8")

    report = import_files([*paths, malformed], existing=[])

    assert report.facies_product_count == 0
    invalid = next(resource for resource in report.added if resource.path == str(malformed))
    assert invalid.parsed_summary["geojson_valid"] is False
    assert "geojson_layer_role" not in invalid.parsed_summary
    assert all(resource.artifact_role == "input" for resource in report.added)


def test_explicit_product_id_groups_generic_hierarchy_filenames(tmp_path):
    paths = [
        _write_layer(
            tmp_path / "facies.geojson",
            property_name="facies",
            property_value="扇三角洲",
            product_id="tool-run-42",
        ),
        _write_layer(
            tmp_path / "subfacies.geojson",
            property_name="subfacies",
            property_value="扇三角洲前缘",
            product_id="tool-run-42",
        ),
        _write_layer(
            tmp_path / "microfacies.geojson",
            property_name="microfacies",
            property_value="辫状水道",
            product_id="tool-run-42",
        ),
    ]

    report = import_files(paths, existing=[])

    assert report.facies_product_count == 1
    assert {
        resource.parsed_summary["facies_product_source_id"]
        for resource in report.added
    } == {"tool-run-42"}


def test_data_navigation_and_filter_expose_geojson_vectors(qtbot, tmp_path):
    source = _write_layer(
        tmp_path / "facies.geojson",
        property_name="facies",
        property_value="河流",
    )
    resource = import_files([source], existing=[]).added[0]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([resource], [])

    item = tree.find_category_item("GeoJSON矢量")
    assert item is not None
    query = item.data(0, Qt.ItemDataRole.UserRole)
    assert query.node_type == "type"
    assert query.node_value == "geojson"
    assert item.text(0).endswith("1")

    index = FilterIndex()
    index.rebuild([resource])
    assert index.filter_query(FilterQuery(node_type="type", node_value="geojson")) == [
        0
    ]
