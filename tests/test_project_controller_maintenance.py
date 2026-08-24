"""Tests for ProjectController catalog maintenance cancellation and domain_binding cancellation tokens (Issue #970)."""

from pathlib import Path
import threading
import time
from unittest.mock import MagicMock
from paleo_workbench.catalog.domain_binding import stage_resources
from paleo_workbench.project.models import ProjectDocument, ProjectMeta, ResourceItem


def test_stage_resources_cancels_on_event(tmp_path: Path):
    """stage_resources must promptly break loop when cancel_event is set."""
    project = ProjectDocument(meta=ProjectMeta(name="test"))
    resources = [
        ResourceItem(
            id=f"res_{i}",
            name=f"Res {i}",
            type="seismic",
            format="sgy",
            path=str(tmp_path / f"res_{i}.sgy"),
        )
        for i in range(100)
    ]
    cancel_event = threading.Event()
    cancel_event.set()  # Cancel immediately

    resolver = lambda p: Path(p)
    staged = stage_resources(project, resources, path_resolver=resolver, cancel_event=cancel_event)

    # Should have broken immediately without staging all 100
    assert len(staged) == 0


def test_project_controller_maintenance_cancellation():
    """ProjectController._end_current_session sets _maintenance_cancel event."""
    from paleo_workbench.ui.project_controller import ProjectController

    mock_window = MagicMock()
    mock_window.project_path = "test.paleo.json"
    mock_window.app_shell = None

    controller = ProjectController(mock_window)
    cancel_event = threading.Event()
    controller._maintenance_cancel = cancel_event

    # Simulate running maintenance thread
    def long_task():
        while not cancel_event.is_set():
            time.sleep(0.01)

    t = threading.Thread(target=long_task)
    controller._maintenance_thread = t
    t.start()

    # _end_current_session should signal cancel and join within timeout
    res = controller._end_current_session()
    assert cancel_event.is_set()
    assert not t.is_alive()
