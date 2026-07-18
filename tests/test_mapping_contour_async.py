from __future__ import annotations

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage


def test_contour_pages_share_owned_worker_job_lifecycle(qtbot):
    pages = (PreparationPage(), MappingPage())
    for page in pages:
        qtbot.addWidget(page)
        assert isinstance(page._contour_job, OwnedWorkerJob)
        assert not hasattr(page, "_contour_thread")
        assert not hasattr(page, "_contour_worker")
        assert not hasattr(page, "_contour_token")
        assert not hasattr(page, "_contour_target_project")
