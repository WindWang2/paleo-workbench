from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


def pytest_configure(config):
    """Qt platform policy for tests (never force X11/xcb).

    - **CI / headless**: workflows set ``QT_QPA_PLATFORM=offscreen`` — leave it.
    - **Local Wayland session**: leave unset (or clear accidental ``xcb``) so Qt
      uses Wayland; do **not** default to xcb.
    - Interactive GUI smoke: same as the app — Wayland session native.
    """
    from paleo_workbench.qt_platform import configure_qt_platform_for_session

    configure_qt_platform_for_session(warn=False)

    # QGIS renderer tests are opt-in (packaging #437): they self-skip unless
    # the bridge was built, and `pytest -m qgis` selects them explicitly in a
    # QGIS-enabled leg.
    config.addinivalue_line(
        "markers", "qgis: QGIS production-renderer tests (opt-in bridge build)"
    )


@pytest.fixture(autouse=True)
def cleanup_qt_deferred_deletes():
    """Force execution of all DeferredDelete events at the end of every test.
    This prevents QThread/QObject deletion events from leaking into subsequent
    tests, avoiding concurrent Shiboken wrapper destruction and intermittent
    segmentation faults or Bus errors under offscreen *or* live platforms.
    """
    yield
    app = QApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
