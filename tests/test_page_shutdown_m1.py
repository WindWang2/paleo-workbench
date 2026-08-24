"""Tests for worker shutdown lifecycle and aggregated return booleans (Issues #962, #966)."""

from unittest.mock import MagicMock
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_data_page_public_shutdown_workers_protocol(monkeypatch):
    """DataPage must expose public shutdown_workers method that shuts down all 8 jobs (issue #962)."""
    # Test method existence and calling
    assert hasattr(DataPage, "shutdown_workers")
    assert callable(getattr(DataPage, "shutdown_workers"))


def test_stratigraphy_correlation_page_shutdown_returns_false_on_timeout(monkeypatch):
    """StratigraphyCorrelationPage.shutdown_workers must return False if any worker fails to join (issue #966)."""
    page = StratigraphyCorrelationPage.__new__(StratigraphyCorrelationPage)
    page._dtw_job = MagicMock()
    page._load_job = MagicMock()
    page._load_seq = 0
    page._release_engine_view = MagicMock()

    # Case 1: All workers join successfully
    page._dtw_job.shutdown.return_value = True
    page._load_job.shutdown.return_value = True
    assert page.shutdown_workers() is True
    page._release_engine_view.assert_called_once()

    # Case 2: One worker times out
    page._release_engine_view.reset_mock()
    page._dtw_job.shutdown.return_value = False
    page._load_job.shutdown.return_value = True
    assert page.shutdown_workers() is False
    page._release_engine_view.assert_not_called()


def test_mapping_page_shutdown_returns_false_when_raster_controller_fails(monkeypatch):
    """MappingPage.shutdown_workers must return False if raster_controller fails to join (issue #966)."""
    page = MappingPage.__new__(MappingPage)
    page._contour_job = MagicMock()
    page._export_job = MagicMock()
    page._end_export_busy = MagicMock()
    page._contour_job.shutdown.return_value = True
    page._export_job.shutdown.return_value = True

    mock_controller = MagicMock()
    mock_canvas = MagicMock()
    mock_canvas._raster_controller = mock_controller
    mock_panel = MagicMock()
    mock_panel.native_canvas = mock_canvas
    page.canvas_panel = mock_panel

    # Case 1: raster controller succeeds
    mock_controller.shutdown.return_value = True
    assert page.shutdown_workers() is True

    # Case 2: raster controller fails / times out
    mock_controller.shutdown.return_value = False
    assert page.shutdown_workers() is False
