from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True, scope="session")
def isolate_qsettings(tmp_path_factory):
    """Keep QSettings-backed stores off the real user profile for the suite.

    Default-constructed ``QSettings(organization, application)`` instances —
    e.g. the workbench layout persistence — write to the user's real config
    dir. Redirecting the default path to a session temp dir makes every test
    hermetic suite-wide; tests that need stricter per-test isolation (or a
    pre-seeded store) bind their own explicit ini on top.
    """
    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)


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
    # WellLog native-binding contract (#917): needs a BUILT welllog pybind
    # module, which no CI leg installs today. The fast gate deselects the
    # family but asserts its collection so the contract cannot silently
    # vanish (same fail-closed pattern as the `slow` family).
    config.addinivalue_line(
        "markers",
        "welllog_binding: workbench↔WellLogEngine native binding contract "
        "(requires built binding; deselected in binding-less gates)",
    )


def pytest_sessionstart(session):
    """Fail-closed gate for required QGIS CI legs (#1147)."""
    import os

    if os.environ.get("PALEO_REQUIRE_QGIS", "").strip().lower() in {"1", "true", "yes"}:
        from tests.qgis_support import QGIS_SKIP_REASON, qgis_bridge_available

        if not qgis_bridge_available():
            pytest.exit(
                f"FATAL: PALEO_REQUIRE_QGIS=1 is set but qgis_render_bridge is not importable.\n"
                f"Ensure the bridge was compiled: {QGIS_SKIP_REASON}",
                returncode=1,
            )


def pytest_runtest_setup(item):
    """Automatically gate all tests carrying the @pytest.mark.qgis marker (#1147)."""
    marker = item.get_closest_marker("qgis")
    if marker is not None:
        import os
        from tests.qgis_support import QGIS_SKIP_REASON, qgis_bridge_available

        if not qgis_bridge_available():
            strict = os.environ.get("PALEO_REQUIRE_QGIS", "").strip().lower() in {"1", "true", "yes"}
            if strict:
                pytest.fail(
                    f"Test {item.nodeid} requires QGIS (PALEO_REQUIRE_QGIS=1), "
                    f"but qgis_render_bridge is not importable."
                )
            else:
                pytest.skip(QGIS_SKIP_REASON)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    """Timer fence (#951): stop every still-armed QTimer BEFORE pytest-qt's
    qtbot tears the test's widgets down.

    The CI 3.13 SIGSEGV signature is QTimerInfoList::activateTimers() →
    QCoreApplication::notifyInternal2() on a QObject whose C++ side is already
    destroyed: a timer left running by a finished test fires during a LATER
    test's event processing, with zero project frames to trace. Stopping the
    timers while their targets are still alive closes that window; the
    DeferredDelete flush in ``cleanup_qt_deferred_deletes`` (which runs after
    qtbot's own teardown) remains the second line of defense.
    """
    app = QApplication.instance()
    if app is not None:
        try:
            for timer in app.findChildren(QTimer):
                if timer.isActive():
                    timer.stop()
        except Exception:
            pass
    yield


@pytest.fixture(autouse=True)
def cleanup_qt_deferred_deletes():
    """Force execution of all DeferredDelete events at the end of every test.
    This prevents QThread/QObject deletion events from leaking into subsequent
    tests, avoiding concurrent Shiboken wrapper destruction and intermittent
    segmentation faults or Bus errors under offscreen *or* live platforms.
    """
    yield
    from paleo_workbench.mapping.map_render_backend import shutdown_live_fallback_backends

    shutdown_live_fallback_backends()
    app = QApplication.instance()
    if app is not None:
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        except Exception:
            pass
