"""VersionWorkbenchDialog UI behavior (D6) — timeline, detail, diff, lifecycle.

Uses the real DataCatalogService on tmp_path (no service mocks); the dialog is
fully synchronous (single-asset service calls on the GUI thread), so tests
assert model state directly with no async waiting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QMessageBox

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages.version_workbench_dialog import (
    VersionWorkbenchDialog,
)


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def asset_versions(service, tmp_path):
    """One asset with 3 versions: RAW v1 → DERIVED v2 (producing run) →
    OUTPUT v3 (service.promote_version copies v2 as a new immutable OUTPUT)."""
    v1 = service.import_raw(
        _source(tmp_path, "core.las", b"raw-bytes"),
        name="岩心数据",
        type="well_log",
        format="las",
        metadata={"origin": "import"},
    )
    run = service.register_run(
        "grain-filter",
        input_version_ids=[v1.id],
        parameters={"cutoff": 5},
        generator="paleo-test 0.1",
        status="completed",
    )
    v2 = service.register_version(
        v1.asset_id,
        _source(tmp_path, "filtered.csv", b"derived-bytes"),
        DataStage.DERIVED,
        parent_version_ids=[v1.id],
        run_id=run.id,
        metadata={"purpose": "粒度过滤", "origin": "import"},
    )
    v3 = service.promote_version(v2.id, note="转正式")
    assert (v1.version_number, v2.version_number, v3.version_number) == (1, 2, 3)
    return v1, v2, v3


def _dialog_for(service, asset_id, qtbot) -> VersionWorkbenchDialog:
    dialog = VersionWorkbenchDialog(
        service_provider=lambda: service, asset_id=asset_id
    )
    qtbot.addWidget(dialog)
    return dialog


def _select_rows(dialog, *rows: int) -> None:
    """Programmatic multi-row selection (SelectRows behavior)."""
    model = dialog.versions_table.selectionModel()
    for row in rows:
        model.select(
            model.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )


def _yes_question(*args, **kwargs):
    return QMessageBox.StandardButton.Yes


def test_dialog_lists_versions_newest_first_with_current_marker(
    service, asset_versions, qtbot
):
    v1, v2, v3 = asset_versions
    dialog = _dialog_for(service, v1.asset_id, qtbot)

    table = dialog.versions_table
    assert table.rowCount() == 3
    # Newest first: v3 (promoted OUTPUT) on top and marked 当前.
    assert table.item(0, 0).text() == "v3（当前）"
    assert table.item(1, 0).text() == "v2"
    assert table.item(2, 0).text() == "v1"
    assert "当前" not in table.item(2, 0).text()
    # Header: asset name + type + current pointer; total count.
    asset = service.get_asset(v1.asset_id)
    assert asset.name in dialog.header_label.text()
    assert asset.type in dialog.header_label.text()
    assert "v3" in dialog.header_label.text()
    assert dialog.count_label.text() == "共 3 个版本"
    # Stage / source columns: RAW import is 托管, trashed would read 已删除.
    assert table.item(2, 1).text() == "RAW"
    assert table.item(0, 1).text() == "OUTPUT"
    assert table.item(2, 6).text() == "托管"
    assert table.item(2, 2).text() == v1.sha256[:12]
    assert table.item(2, 3).text() == "9 B"


def test_selection_populates_metadata_and_run_details(
    service, asset_versions, qtbot
):
    v1, v2, v3 = asset_versions
    dialog = _dialog_for(service, v1.asset_id, qtbot)

    # No selection yet: placeholders.
    assert dialog.detail_meta_text.toPlainText() == ""

    dialog.versions_table.selectRow(1)  # v2 — the DERIVED version with a run
    run = service.get_run(v2.run_id)
    assert f"v{v2.version_number}" in dialog.detail_title_label.text()
    assert "粒度过滤" in dialog.detail_meta_text.toPlainText()
    assert '"purpose"' in dialog.detail_meta_text.toPlainText()
    assert run.operation in dialog.detail_run_label.text()
    assert '"cutoff": 5' in dialog.detail_run_params.toPlainText()
    assert "源文件缺失" not in dialog.detail_resolved_label.text()
    assert v2.path in dialog.detail_path_label.text()
    # Parents resolve through the service lineage.
    assert v1.id in dialog.detail_parents_label.text()

    dialog.versions_table.clearSelection()
    assert dialog.detail_meta_text.toPlainText() == ""
    assert not dialog.promote_btn.isEnabled()
    assert not dialog.compare_btn.isEnabled()


def test_compare_button_gating_and_dialog_diff_markers(
    service, asset_versions, qtbot, monkeypatch
):
    v1, v2, v3 = asset_versions
    dialog = _dialog_for(service, v1.asset_id, qtbot)

    # Not exactly two rows selected → 对比元数据 stays disabled.
    assert not dialog.compare_btn.isEnabled()
    _select_rows(dialog, 0)
    assert not dialog.compare_btn.isEnabled()
    _select_rows(dialog, 2)
    assert dialog.compare_btn.isEnabled()

    captured: list[object] = []
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.version_workbench_dialog._VersionCompareDialog.exec",
        lambda self: captured.append(self) or 0,
    )
    dialog.compare_btn.click()
    assert len(captured) == 1
    compare = captured[0]
    table = compare.table

    sha_row = _find_row(table, "校验和")
    assert sha_row is not None
    # v3 and v1 payloads differ → 校验和 marker is 异.
    assert table.item(sha_row, 3).text() == "异"
    stage_row = _find_row(table, "阶段")
    assert table.item(stage_row, 3).text() == "异"
    # Shared asset format (both derive from asset metadata) → 同.
    format_row = _find_row(table, "格式")
    assert table.item(format_row, 3).text() == "同"
    # Metadata keys are a sorted union; promoted_from exists only on v3.
    promoted_row = _find_row(table, "元数据 · promoted_from")
    assert promoted_row is not None
    assert table.item(promoted_row, 3).text() == "异"


def _find_row(table, label: str) -> int | None:
    for row in range(table.rowCount()):
        if table.item(row, 0).text() == label:
            return row
    return None


def test_promote_trash_restore_roundtrip_updates_service_and_emits(
    service, asset_versions, qtbot, monkeypatch
):
    v1, v2, v3 = asset_versions
    dialog = _dialog_for(service, v1.asset_id, qtbot)
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.version_workbench_dialog.QMessageBox.question",
        _yes_question,
    )
    emitted: list[int] = []
    dialog.versions_changed.connect(lambda: emitted.append(1))

    # --- promote v1 (RAW, oldest row) → new immutable OUTPUT version ---------
    dialog.versions_table.selectRow(2)
    assert dialog.promote_btn.isEnabled()
    dialog.promote_btn.click()
    assert emitted == [1]
    versions = service.list_versions(v1.asset_id)
    assert len(versions) == 4
    promoted = versions[-1]
    assert promoted.stage == DataStage.OUTPUT
    assert promoted.metadata.get("promoted_from") == v1.id
    assert service.get_asset(v1.asset_id).current_version_id == promoted.id
    assert dialog.versions_table.rowCount() == 4
    assert dialog.versions_table.item(0, 0).text() == "v4（当前）"

    # --- trash the promoted version (stays visible, marked 已删除) -----------
    dialog.versions_table.selectRow(0)
    assert dialog.trash_btn.isEnabled()
    dialog.trash_btn.click()
    assert emitted == [1, 1]
    trashed = service.get_version(promoted.id)
    assert trashed.trashed is True
    assert dialog.versions_table.rowCount() == 4  # trashed rows stay visible
    assert dialog.versions_table.item(0, 1).text() == "已删除"
    # Reload cleared the selection: nothing actionable until a row is picked.
    assert not dialog.promote_btn.isEnabled()
    assert not dialog.restore_btn.isEnabled()
    # Re-select the trashed row: gating flips — cannot promote/trash, can restore.
    dialog.versions_table.selectRow(0)
    assert not dialog.promote_btn.isEnabled()
    assert not dialog.trash_btn.isEnabled()
    assert dialog.restore_btn.isEnabled()

    # --- restore returns the version -----------------------------------------
    dialog.restore_btn.click()
    assert emitted == [1, 1, 1]
    restored = service.get_version(promoted.id)
    assert restored.trashed is False
    assert dialog.versions_table.item(0, 1).text() == "OUTPUT"


def test_open_location_disabled_when_payload_missing(
    service, asset_versions, tmp_path, qtbot
):
    v1, v2, v3 = asset_versions
    dialog = _dialog_for(service, v1.asset_id, qtbot)

    dialog.versions_table.selectRow(2)  # v1 RAW — payload present
    assert dialog.open_btn.isEnabled()

    payload = service.resolve_path(v1)
    assert payload.is_file()
    payload.unlink()
    dialog.reload_versions()
    dialog.versions_table.selectRow(2)
    assert not dialog.open_btn.isEnabled()
    assert "源文件缺失" in dialog.detail_resolved_label.text()
