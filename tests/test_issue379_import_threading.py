"""Regression tests for issue #379: Data Manager heavy I/O off the GUI thread.

Import-finish catalog registration (per-file SHA-256 + full copy + catalog
saves), directory rescan (rglob + per-file hashes) and delivery payload
copies previously ran synchronously in GUI-thread slots, freezing the window
for the whole I/O duration on GB-scale data.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, QTimer

from paleo_workbench.catalog.lifecycle import register_resource_input
from paleo_workbench.project.models import ExportArtifact, ProjectDocument
from paleo_workbench.ui.pages.data_page import DataPage


def _tiny_las(path: Path) -> None:
    path.write_text("~Version\n~Well\n~Curve\nDEPT\n~A\n0\n", encoding="utf-8")


def _make_page(qtbot, tmp_path: Path) -> tuple[DataPage, Path]:
    project = ProjectDocument.new("Thread")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    las = tmp_path / "well.las"
    _tiny_las(las)
    return page, las


def test_import_registration_runs_off_gui_thread(qtbot, tmp_path: Path, monkeypatch):
    page, las = _make_page(qtbot, tmp_path)
    threads: list = []
    real = register_resource_input

    def spy(resource, **kwargs):
        threads.append(QThread.currentThread())
        return real(resource, **kwargs)

    monkeypatch.setattr(
        "paleo_workbench.catalog.lifecycle.register_resource_input", spy
    )

    with qtbot.waitSignal(page.import_finished, timeout=5000):
        assert page.begin_import_paths([las])

    assert threads, "registration must have run"
    assert all(t is not page.thread() for t in threads)
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()


def test_import_registration_keeps_gui_responsive(qtbot, tmp_path: Path, monkeypatch):
    """While registration is blocked on I/O, the GUI event loop must keep ticking."""
    page, las = _make_page(qtbot, tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocking(resource, **kwargs):
        entered.set()
        assert release.wait(timeout=5.0)
        return register_resource_input(resource, **kwargs)

    monkeypatch.setattr(
        "paleo_workbench.catalog.lifecycle.register_resource_input", blocking
    )

    assert page.begin_import_paths([las]) is True
    qtbot.waitUntil(lambda: page._register_job.is_running, timeout=5000)

    ticks = {"n": 0}
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
    timer.start()
    qtbot.wait(300)
    timer.stop()

    assert ticks["n"] > 0, "GUI thread must keep processing events during registration"
    release.set()
    with qtbot.waitSignal(page.import_finished, timeout=5000):
        pass


def test_rescan_runs_off_gui_thread(qtbot, tmp_path: Path, monkeypatch):
    page, las = _make_page(qtbot, tmp_path)
    page.import_paths([las])
    page.asset_table.table.selectRow(0)

    threads: list = []
    real_scan = None
    import paleo_workbench.ui.data_lifecycle_controller as dlc_mod

    real_scan = dlc_mod.scan_resources

    def spy(folder, project_path=None):
        threads.append(QThread.currentThread())
        return real_scan(folder, project_path=project_path)

    monkeypatch.setattr(dlc_mod, "scan_resources", spy)

    assert page.rescan_selected_asset() is True
    qtbot.waitUntil(
        lambda: "已重新扫描" in page.data_toolbar.operation_status_label.text(),
        timeout=5000,
    )
    assert threads, "rescan must have run"
    assert all(t is not page.thread() for t in threads)


def test_deliver_copy_runs_off_gui_thread(qtbot, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    import paleo_workbench.ui.data_lifecycle_controller as dlc_mod

    page, las = _make_page(qtbot, tmp_path)
    page.import_paths([las])
    resource = page.project.resources[0]
    page.project_path = tmp_path / "demo.paleo.json"

    destination = tmp_path / "handoff" / "well-copy.las"

    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):  # noqa: A003 - Qt API name
            return QDialog.DialogCode.Accepted

        def output_path(self):
            return destination

    monkeypatch.setattr(dlc_mod, "_DeliveryDialog", AcceptedDialog)

    threads: list = []
    real_copy = page._lifecycle.run_delivery_copy

    def spy(source, dest):
        threads.append(QThread.currentThread())
        return real_copy(source, dest)

    monkeypatch.setattr(page._lifecycle, "run_delivery_copy", spy)

    page._deliver_asset(resource)
    qtbot.waitUntil(
        lambda: "已导出 / 交付" in page.data_toolbar.operation_status_label.text(),
        timeout=5000,
    )
    assert threads, "delivery copy must have run"
    assert all(t is not page.thread() for t in threads)
    assert destination.read_bytes() == las.read_bytes()


def test_legacy_sync_import_paths_still_applies(qtbot, tmp_path: Path):
    """The synchronous import_paths() path keeps its apply-on-call contract."""
    page, las = _make_page(qtbot, tmp_path)
    report = page.import_paths([las])
    assert report.added_count == 1
    assert page.project.resources[0].name == "well.las"
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()
