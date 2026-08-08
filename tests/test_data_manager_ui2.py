"""Comprehensive test suite for Data Manager UI 2.0 features and interactions.
"""
import pytest
from pathlib import Path
from PySide6.QtCore import Qt

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_view_models import (
    DataStage,
    IntegrityState,
    asset_view_from_resource,
)
from paleo_workbench.ui.pages.filter_index import FilterQuery
from paleo_workbench.ui.pages.integrity_worker import IntegrityWorker


def test_ui2_lifecycle_navigation(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    res_raw = ResourceItem(name="raw1.las", path="/raw1.las", type="well_log", format="las", artifact_role="input")
    res_derived = ResourceItem(name="der1.las", path="/der1.las", type="well_log", format="las", artifact_role="derived")
    page.project.resources.extend([res_raw, res_derived])
    page._refresh()

    # Filter by stage RAW (Core enum values are lowercase since the DataStage
    # unification — node_value must match DataStage.RAW.value == "raw")
    page.navigation_tree.filter_query_changed.emit(FilterQuery(node_type="stage", node_value=DataStage.RAW.value))
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "raw1.las"

    # Filter by stage DERIVED
    page.navigation_tree.filter_query_changed.emit(FilterQuery(node_type="stage", node_value=DataStage.DERIVED.value))
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "der1.las"


def test_ui2_tag_filtering_and_search(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    res1 = ResourceItem(name="A.las", path="/a.las", type="well_log", format="las", tags=["重点井"])
    res2 = ResourceItem(name="B.sgy", path="/b.sgy", type="seismic", format="sgy", tags=["区域扫面"])
    page.project.resources.extend([res1, res2])
    page._refresh()

    # Filter by tag
    page.navigation_tree.filter_query_changed.emit(FilterQuery(node_type="tag", node_value="重点井"))
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "A.las"

    # Reset tag filter and search text for tag content
    page.navigation_tree.filter_query_changed.emit(FilterQuery(node_type="all"))
    page.asset_table.set_search_text("区域扫面")
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "B.sgy"


def test_ui2_combined_filtering(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    res1 = ResourceItem(name="Target1.las", path="/t1.las", type="well_log", format="las", tags=["重点"], artifact_role="input")
    res2 = ResourceItem(name="Target2.las", path="/t2.las", type="well_log", format="las", tags=["普通"], artifact_role="derived")
    page.project.resources.extend([res1, res2])
    page._refresh()

    # Combined stage=RAW and tag=重点 (lowercase Core enum value)
    query = FilterQuery(node_type="stage", node_value=DataStage.RAW.value, tag="重点")
    page.asset_table.set_filter_query(query)
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "Target1.las"


def test_ui2_raw_safety_and_create_derived(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    raw_res = ResourceItem(name="locked_raw.las", path="/locked_raw.las", type="well_log", format="las", artifact_role="input")
    page.project.resources.append(raw_res)
    page._refresh()

    view = asset_view_from_resource(raw_res)
    assert view.is_raw is True
    assert view.stage == DataStage.RAW

    # Execute create derived copy
    page._create_derived_copy(raw_res)
    assert len(page.project.resources) == 2
    derived_res = page.project.resources[1]
    assert derived_res.name == "locked_raw.las_derived"
    assert derived_res.artifact_role == "derived"
    assert "派生" in derived_res.tags


def test_ui2_inspector_sections_and_tags(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    res = ResourceItem(name="inspect_me.las", path="/path/inspect_me.las", type="well_log", format="las", checksum="1234567890abcdef")
    page.project.resources.append(res)
    page._refresh()
    page._set_selected_asset(res)

    inspector = page.inspector_panel
    assert inspector.tabs.count() == 6
    assert inspector.title_label.text() == "数据资产检查器"

    # Add tag via inspector signal
    page._handle_tag_added(res, "新标签")
    assert "新标签" in res.tags

    # Remove tag via inspector signal
    page._handle_tag_removed(res, "新标签")
    assert "新标签" not in res.tags


def test_ui2_integrity_worker_non_blocking(qtbot, tmp_path: Path):
    file1 = tmp_path / "valid.txt"
    file1.write_text("hello world")

    res1 = ResourceItem(name="valid.txt", path=str(file1), type="document", format="txt")
    res2 = ResourceItem(name="missing.txt", path=str(tmp_path / "nonexistent.txt"), type="document", format="txt")

    worker = IntegrityWorker([res1, res2], project_root=tmp_path)
    reports = []
    worker.finished.connect(reports.append)

    # Run worker logic
    worker.run()

    assert len(reports) == 1
    report = reports[0]
    assert report.total_checked == 2
    assert report.verified_count == 1
    assert report.missing_count == 1


def test_ui2_multi_select_and_bulk_actions(qtbot):
    page = DataPage(project=ProjectDocument.new("UI2 Test"))
    qtbot.addWidget(page)

    res1 = ResourceItem(name="bulk1.las", path="/b1.las", type="well_log", format="las")
    res2 = ResourceItem(name="bulk2.las", path="/b2.las", type="well_log", format="las")
    page.project.resources.extend([res1, res2])
    page._refresh()

    # Multi selection
    page._set_selected_assets([res1, res2])
    assert len(page._selected_assets) == 2

    # Bulk remove
    page.remove_assets([res1, res2])
    assert len(page.project.resources) == 0
