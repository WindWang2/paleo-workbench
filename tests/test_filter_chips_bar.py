"""Filter chips bar (D5) — chips render the active query, removals re-issue
it, and saved filters round-trip through QSettings without touching data.

Also pins the entity-view SQL mapping (D10): a bounded entity membership
set is served by the paged SQL path instead of falling back to the
materialized path.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages.filter_chips_bar import (
    SAVED_FILTERS_KEY,
    FilterChipsBar,
)
from paleo_workbench.ui.pages.filter_index import FilterQuery
from paleo_workbench.ui.pages.paged_asset_model import (
    CatalogPageProvider,
    PagedAssetTableModel,
)


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at a scratch file (mirrors the session fixture)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    settings = QSettings("paleo-test", "paleo-test")
    settings.clear()
    yield
    settings.clear()


@pytest.fixture
def service(tmp_path):
    project_path = _make_project(tmp_path)
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def test_chips_render_and_remove_dimensions(qtbot):
    bar = FilterChipsBar()
    qtbot.addWidget(bar)
    query = FilterQuery(
        node_type="stage",
        node_value="raw",
        search_text="gr",
        stage="raw",
        tags=["qc", "2024"],
        tag_operator="or",
    )
    bar.set_query(query)
    labels = [
        bar._chips_layout.itemAt(i).widget().text()
        for i in range(bar._chips_layout.count())
    ]
    assert any("视图" in text for text in labels)
    assert any("搜索: gr" in text for text in labels)
    assert any("阶段: raw" in text for text in labels)
    assert sum(1 for text in labels if text.startswith("标签:")) == 2
    assert not bar.clear_btn.isHidden()

    # Removing one tag chip re-issues the query without it.
    removed: list[str] = []
    bar.chip_removed.connect(removed.append)
    bar._add_chip("tag:qc", "标签: qc  ✕")
    for i in range(bar._chips_layout.count()):
        widget = bar._chips_layout.itemAt(i).widget()
        if widget.text() == "标签: qc  ✕":
            widget.clicked.emit("tag:qc")
            break
    assert removed == ["tag:qc"]


def test_saved_filters_roundtrip(qtbot):
    bar = FilterChipsBar()
    qtbot.addWidget(bar)
    bar.set_query(FilterQuery(node_type="all", search_text="well_01", stage="raw"))
    # QInputDialog blocks a headless test; persist exactly what _save_current
    # stores after gathering a name, then exercise the apply/delete paths.
    payload = [
        {
            "name": "最近测井",
            "query": {
                "node_type": "all",
                "search_text": "well_01",
                "stage": "raw",
                "tags": ["qc"],
                "tag_operator": "and",
            },
        }
    ]
    QSettings().setValue(SAVED_FILTERS_KEY, json.dumps(payload, ensure_ascii=False))
    bar.reload_saved()
    assert bar.saved_combo.count() == 2

    applied: list[FilterQuery] = []
    bar.filter_applied.connect(applied.append)
    index = bar.saved_combo.findText("最近测井")
    bar._apply_saved(index)
    assert len(applied) == 1
    assert applied[0].search_text == "well_01"
    assert applied[0].stage == "raw"
    assert applied[0].tags == ["qc"]

    # Delete the saved filter again.
    bar.saved_combo.setCurrentIndex(bar.saved_combo.findText("最近测井"))
    bar._delete_saved()
    assert bar.saved_combo.count() == 1
    assert QSettings().value(SAVED_FILTERS_KEY, "") in ("", None, "[]")


def test_entity_view_maps_to_sql(service):
    """A bounded entity membership set stays in the paged SQL path (D10):
    object browsing no longer falls back to full materialization."""
    ids = {}
    with service.batch_save():
        for i in range(6):
            src = _make_source(service, f"well_{i}")
            v = service.import_raw(source_path=src, name=f"well_{i}")
            ids[v.asset_id] = v

    provider = CatalogPageProvider(service)
    query = FilterQuery(
        node_type="entity",
        node_value="entity-1",
        entity_asset_ids=frozenset(sorted(ids)[:2]),
    )
    assert provider.apply_filter_query(query) is True
    assert provider.total() == 2
    rows = provider.page(0)
    assert {row.id for row in rows} == set(sorted(ids)[:2])

    # A huge membership set refuses honestly (materialized fallback).
    huge = FilterQuery(
        node_type="entity_group",
        node_value="well",
        entity_asset_ids=frozenset(str(i) for i in range(10_000)),
    )
    assert provider.apply_filter_query(huge) is False


def _make_source(service, name: str) -> Path:
    src = service.project_path.parent / "incoming" / f"{name}.las"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(f"curve {name}", encoding="utf-8")
    return src
