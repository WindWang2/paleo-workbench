"""#843: mapping-page contour-draft failure must surface as visible text.

The preparation page's twin flow writes the failure into the summary label;
the mapping page only wrote it into the button tooltip (invisible until
hover). Mirror the preparation page so a failed draft is never silent.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def _contour_project() -> ProjectDocument:
    project = ProjectDocument.new("MapContourFail")
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
    return project


def test_mapping_page_contour_failure_is_visible(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    from paleo_workbench.ui.pages import contour_draft_worker as worker_mod

    def _boom(project, **kwargs):
        raise ValueError("模拟等值线编译失败")

    monkeypatch.setattr(worker_mod, "compile_contour_drafts_for_project", _boom)

    project = _contour_project()
    page = MappingPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state(project.paleomap_documents, factor_tasks=project.factor_map_tasks)

    page.bottom_workbench.factor_shelf.contour_draft_btn.click()

    qtbot.waitUntil(
        lambda: page.bottom_workbench.factor_shelf.contour_draft_btn.isEnabled(),
        timeout=5_000,
    )
    # A tooltip is not a visible error surface.  The status bar must carry the
    # failure text the user can actually see (#843).
    assert "等值线初稿失败" in page.status_bar.scale.text()
    page.shutdown_workers(2_000)