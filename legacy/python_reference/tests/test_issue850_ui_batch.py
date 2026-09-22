"""#850: UI batch — sorting/multi-select/refresh guard, integrity honesty,
truncation visibility, contour-worker snapshot, prediction busy state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import (
    ExportArtifact,
    FactorMapTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.resources.preview_parsers.models import PreviewResult
from paleo_workbench.ui.pages.contour_draft_worker import ContourDraftWorker
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_view_models import (
    IntegrityState,
    asset_view_from_artifact,
)
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage


def _resource(name: str) -> ResourceItem:
    return ResourceItem(
        name=name,
        path=f"/tmp/{name}.las",
        type="well_log",
        format="las",
    )


def _sorted_names(table) -> list[str]:
    model = table.table.model()
    return [
        model.data(model.index(r, 0)) or ""
        for r in range(model.rowCount())
    ]


# --- #850-1: filter change must not silently reset the header sort --------


def test_asset_table_sort_survives_filter_change(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [_resource("Alpha"), _resource("Charlie"), _resource("Bravo")]
    table.update_assets(resources, [])

    # User clicks the 文件名 header (real interaction path).
    header = table.table.horizontalHeader()
    header.sectionClicked.emit(0)
    header.sectionClicked.emit(0)  # second click toggles to descending
    assert _sorted_names(table) == ["Charlie", "Bravo", "Alpha"]
    assert header.isSortIndicatorShown()
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    # A filter change rebuilds the model; the visible order must keep the
    # sorted state the indicator still claims (#850-1).
    table.set_category("测井")

    assert table.table.horizontalHeader().isSortIndicatorShown()
    assert _sorted_names(table) == ["Charlie", "Bravo", "Alpha"]


# --- #850-2: multi-selection must shrink with the filter -------------------


def test_asset_table_filter_shrinks_multi_selection_to_visible_rows(qtbot):
    from PySide6.QtCore import QItemSelectionModel

    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [_resource("Alpha"), _resource("Bravo"), _resource("Charlie")]
    table.update_assets(resources, [])
    sel = table.table.selectionModel()
    for row in range(table.table.model().rowCount()):
        sel.select(
            table.model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Rows
            | QItemSelectionModel.SelectionFlag.Select,
        )
    assert sorted(a.name for a in table._selected_assets) == ["Alpha", "Bravo", "Charlie"]

    emitted: list[list[object]] = []
    table.selected_assets_changed.connect(emitted.append)

    table.set_search_text("bravo")

    assert table_row_count(table) == 1
    # The stale multi-selection must not survive: batch operations may only
    # act on rows the user can actually see (#850-2).
    assert table._selected_assets == [resources[1]]
    assert table._selected_asset is resources[1]
    assert emitted and emitted[-1] == [resources[1]]


def table_row_count(table) -> int:
    return table.table.model().rowCount()


# --- #850-3: refresh must not run O(N) resizeColumnsToContents ------------


def test_asset_table_skips_content_resize_on_large_tables(qtbot, monkeypatch):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        _resource(f"w{i}") for i in range(5000)
    ]
    calls = {"n": 0}
    original = table.table.resizeColumnsToContents

    def _spy():
        calls["n"] += 1
        original()

    monkeypatch.setattr(table.table, "resizeColumnsToContents", _spy)

    # 5000 rows × 8 default columns ≫ the 10k-cell guard (mirrors
    # TablePreviewWidget.MAX_PREVIEW_CELLS guard) — no content measurement.
    table.update_assets(resources, [])
    assert calls["n"] == 0
    assert table_row_count(table) == 5000

    # A same-columns refresh no longer re-fits at all (#894-1: routine
    # refreshes must not touch widths, so a user-dragged width survives).
    table.update_assets(resources[:100], [])
    assert calls["n"] == 0

    # Small tables keep the fit-to-content behavior when auto-fit does run
    # (first fill / column-set change, #894-1).
    table.set_visible_columns([*table.visible_column_keys(), "format"])
    table.update_assets(resources[:100], [])
    assert calls["n"] >= 1


# --- #850-4: integrity column honesty for artifacts without checksums ------


def test_artifact_integrity_never_claims_verified_without_checksum(tmp_path):
    out_file = tmp_path / "result.json"
    out_file.write_text("{}")
    artifact = ExportArtifact(
        id="art_1",
        format="json",
        output_path=str(out_file),
        linked_id="res_1",
        generated_at="2026-01-01T00:00:00Z",
    )
    view = asset_view_from_artifact(artifact, project_root=tmp_path)
    # An ExportArtifact carries no recorded checksum bytes; "已校验" on mere
    # file existence was never a true statement (#850-4).
    assert view.integrity_state == IntegrityState.UNKNOWN
    assert view.integrity_label == "未校验"

    missing = artifact.model_copy(update={"output_path": "/no/such/result.json"})
    view2 = asset_view_from_artifact(missing, project_root=tmp_path)
    assert view2.integrity_state == IntegrityState.MISSING


# --- #850-5: table truncation must be visible, not tooltip-only ------------


def test_reader_panel_shows_table_truncation_in_warning_label(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    headers = tuple(f"c{i}" for i in range(10))
    # #1039 raised the defensive cap from 50k to 1M cells (the virtualized
    # model removed the per-cell allocation that made 50k the freeze
    # threshold); exceed the NEW cap so the truncation contract still holds
    rows = tuple(
        tuple(str(i * 10 + j) for j in range(10)) for i in range(120_000)
    )  # 1.2M cells > 1M preview cap
    panel.render(
        PreviewResult(
            mode="table",
            title="big.csv",
            table_headers=headers,
            table_rows=rows,
        )
    )
    assert panel.table_preview.truncated is True
    # The user must see the deeper truncation without hovering (#850-5).
    assert "表格预览已截断" in panel.table_preview.truncation_message
    assert "截断" in panel.warning_label.text()
    assert "表格预览已截断" in panel.warning_label.text()


# --- #850-6: ContourDraftWorker must take a narrow snapshot -----------------


def test_contour_worker_uses_narrow_snapshot_not_deep_copy():
    project = ProjectDocument.new("Big")
    for i in range(50):
        project.resources.append(_resource(f"r{i}"))
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="IDW",
        status="complete",
        parameters={
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[1.0, 2.0], [3.0, 4.0]],
            "grid_n": 2,
        },
    )
    project.factor_map_tasks.append(task)

    worker = ContourDraftWorker(project)
    snap = worker._project
    assert snap is not project
    # Tasks are shared (grids resolve through the live cache by task id); the
    # bulk resource/prediction data is NOT copied into the snapshot (#850-6,
    # mirroring FactorPrepareWorker's narrow-snapshot contract).
    assert snap.factor_map_tasks[0] is task
    assert len(snap.resources) == 0
    assert len(project.resources) == 50

    # The narrow snapshot still supports the extraction core.
    worker._cancellation_token.cancel()
    worker.run()
    assert worker._project.factor_map_tasks[0].id == task.id


# --- #850-7: prediction run must expose a busy state -----------------------


class _FakeJob:
    is_running = False

    def start(self, worker, **kwargs) -> None:
        self.started = worker

    def shutdown(self, wait_ms: int = 3_000) -> bool:
        return True


class _FakeRun:
    id = "run-1"

    def __init__(self) -> None:
        self.parameters: dict = {}


def test_evidence_panel_busy_disables_run_actions(qtbot):
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)
    task = MockPredictionAdapter().run(ProjectDocument.new("T"), [], seed=1)
    panel.update_state(task)
    assert panel.run_btn.isEnabled()
    assert panel.demo_btn.isEnabled()

    panel.set_inferring(True)
    assert not panel.run_btn.isEnabled()
    assert not panel.demo_btn.isEnabled()
    # A state refresh while busy must not silently re-enable the actions.
    panel.update_state(task)
    assert not panel.run_btn.isEnabled()
    assert not panel.demo_btn.isEnabled()

    panel.set_inferring(False)
    assert panel.run_btn.isEnabled()
    assert panel.demo_btn.isEnabled()


def test_well_log_prediction_start_sets_busy_and_failure_clears(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.well_log_prediction_page as mod

    monkeypatch.setattr(mod, "start_inference", lambda *a, **k: _FakeRun())
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page._inference_job = _FakeJob()
    project = ProjectDocument.new("P")
    page.update_state([], project=project)

    page._start_inference(
        object(),
        "mv-1",
        workflow="well_log_facies",
        name_prefix="测井相预测",
        demo=True,
    )
    assert page.evidence_panel.run_btn.isEnabled() is False
    assert page.evidence_panel.demo_btn.isEnabled() is False

    page._on_inference_failed_if_current("boom")
    assert page.evidence_panel.run_btn.isEnabled() is True
    assert page.evidence_panel.demo_btn.isEnabled() is True


def test_seismic_prediction_start_sets_busy_and_failure_clears(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.seismic_prediction_page as mod

    monkeypatch.setattr(mod, "start_inference", lambda *a, **k: _FakeRun())
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page._inference_job = _FakeJob()
    project = ProjectDocument.new("P")
    page.update_state([], project=project)

    page._start_inference(
        object(),
        "mv-1",
        workflow="seismic_facies",
        name_prefix="地震相预测",
        demo=True,
    )
    assert page.context_toolbar.run_btn.isEnabled() is False
    assert page.context_toolbar.demo_btn.isEnabled() is False

    page._on_inference_failed_if_current("boom")
    assert page.context_toolbar.run_btn.isEnabled() is True
    assert page.context_toolbar.demo_btn.isEnabled() is True