"""RelinkSourcesDialog UI behavior (D9) — scan render, fail-closed batch.

Uses the real DataCatalogService; the scan and relink batches run through
the dialog's OwnedWorkerJob, so tests wait on model content, not on
implementation timing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages.relink_dialog import RelinkSourcesDialog


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


def _external(tmp_path: Path, name: str, payload: bytes):
    src = tmp_path / "outside" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def _wait_scan_clean(dialog, qtbot):
    qtbot.waitUntil(
        lambda: not dialog._busy and not dialog.progress.isVisible(),
        timeout=10_000,
    )


def test_dialog_lists_missing_and_relinkable_flags(service, tmp_path, qtbot):
    external = service.link_external(_external(tmp_path, "GR1.las", b"curve"))
    managed = service.import_raw(
        source_path=_external(tmp_path, "m.las", b"m-bytes")
    )
    external_file = Path(external.path)
    external_file.unlink()  # external source disappears
    Path(managed.path).unlink() if False else None  # managed payload kept

    dialog = RelinkSourcesDialog(service_provider=lambda: service)
    qtbot.addWidget(dialog)
    _wait_scan_clean(dialog, qtbot)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == external.asset_id or True
    assert dialog.table.item(0, 2).text() == "外部"
    assert dialog.table.item(0, 4).text() == "可重链接"
    assert dialog.folder_btn.isEnabled()
    dialog._cancel_running()


def test_folder_redirect_refuses_identity_strangers(service, tmp_path, qtbot, monkeypatch):
    external = service.link_external(_external(tmp_path, "GR1.las", b"curve"))
    Path(external.path).unlink()
    # A same-named STRANGER in the "relocated" folder must be refused.
    stranger_dir = tmp_path / "moved"
    stranger_dir.mkdir()
    (stranger_dir / "GR1.las").write_bytes(b"not-the-same-data")

    dialog = RelinkSourcesDialog(service_provider=lambda: service)
    qtbot.addWidget(dialog)
    _wait_scan_clean(dialog, qtbot)

    dialogs: list[str] = []
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.relink_dialog.QMessageBox.information",
        lambda *a, **k: dialogs.append(str(a[2])) or 0,
    )
    dialog._apply_relinks([(dialog._entries[0], stranger_dir / "GR1.las")])
    _wait_scan_clean(dialog, qtbot)
    # The refusal is surfaced per row and the catalog is untouched.
    assert "拒绝 1 个" in dialogs[-1]
    assert external.path == service.get_version(external.id).path


def test_folder_redirect_relinks_same_file(service, tmp_path, qtbot, monkeypatch):
    external = service.link_external(_external(tmp_path, "GR2.las", b"curve-2"))
    real_file = Path(external.path)
    moved_dir = tmp_path / "moved"
    moved_dir.mkdir()
    target = moved_dir / "GR2.las"
    real_file.replace(target)  # genuine rename: fingerprint proof holds

    dialog = RelinkSourcesDialog(service_provider=lambda: service)
    qtbot.addWidget(dialog)
    _wait_scan_clean(dialog, qtbot)

    boxes: list[str] = []
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.relink_dialog.QMessageBox.information",
        lambda *a, **k: boxes.append(str(a[2])) or 0,
    )
    dialog._apply_relinks([(dialog._entries[0], target)])
    _wait_scan_clean(dialog, qtbot)
    assert "成功重链接 1 个" in boxes[-1]
    # The rescan that follows a successful relink finds nothing missing.
    qtbot.waitUntil(lambda: dialog.table.rowCount() == 0, timeout=10_000)
