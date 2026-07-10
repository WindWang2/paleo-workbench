# tests/test_datapage_stress.py
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.import_service import import_folder
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterIndex
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from tests.perf.fixtures import make_mock_resources, make_tmp_tree, stress_n
from tests.perf.timing import print_stress, timed


class InstantProvider(PreviewProvider):
    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"ok:{asset.name}",
        )


def _wait_controller_idle(qtbot, controller: PreviewRequestController, timeout: int = 10_000) -> None:
    """Block until in-flight preview workers finish (avoids Qt teardown aborts)."""
    qtbot.waitUntil(
        lambda: (
            len(controller._jobs) == 0
            and controller._active is None
            and controller._pending is None
        ),
        timeout=timeout,
    )


def test_stress_s1_update_state(qtbot):
    n = stress_n(2000)
    page = DataPage(ProjectDocument.new("Stress"))
    qtbot.addWidget(page)
    resources = make_mock_resources(n)

    timing, _ = timed("S1_update", lambda: page.update_state({}, resources))
    print_stress("S1_update", n=n, ms=timing.ms)

    # Prefer public-ish access: asset table model row count
    model = page.asset_table.model
    assert model is not None
    assert model.rowCount() == n


def test_stress_s2_filter_index():
    n = stress_n(2000)
    resources = make_mock_resources(n)
    idx = FilterIndex()
    idx.rebuild(resources)

    # FilterIndex categories are Chinese catalog labels ("全部", "测井", …)
    timing_all, rows_all = timed("S2_filter_all", lambda: idx.filter("全部", ""))
    print_stress("S2_filter_all", n=n, ms=timing_all.ms)
    assert len(rows_all) == n

    timing_q, rows_q = timed(
        "S2_filter_search",
        lambda: idx.filter("测井", "asset_0000"),
    )
    print_stress("S2_filter_search", n=n, ms=timing_q.ms)
    assert len(rows_q) >= 1


def test_stress_s3_rapid_select(qtbot):
    n_sel = 30
    resources = make_mock_resources(max(n_sel, 50))
    controller = PreviewRequestController(provider=InstantProvider())

    last: list[str] = []
    controller.result_ready.connect(lambda r: last.append(getattr(r, "title", "") or ""))

    try:
        def run():
            for i in range(n_sel):
                controller.request(resources[i])
            # Process events so async jobs drain
            app = QApplication.instance()
            for _ in range(50):
                app.processEvents()

        timing, _ = timed("S3_rapid_select", run)
        print_stress("S3_rapid_select", n=n_sel, ms=timing.ms)

        _wait_controller_idle(qtbot, controller, timeout=10_000)
        assert last  # got at least one result
        # Latest-only: final title should be last requested when instant provider
        assert last[-1] == resources[n_sel - 1].name
    finally:
        controller.shutdown(wait_ms=5_000)


def test_stress_s4_import_folder(tmp_path):
    n = 300
    root = make_tmp_tree(tmp_path, n=n)
    timing, report = timed("S4_import_folder", lambda: import_folder(root, existing=[]))
    print_stress("S4_import_folder", n=n, ms=timing.ms)
    assert report.added_count == n
