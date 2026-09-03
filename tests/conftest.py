from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PySide6.QtWidgets import QApplication

try:
    import shiboken6 as _shiboken6  # noqa: F401
    from PySide6.QtWidgets import QWidget as _QWidget  # for type check

    _orig_wrapInstance = _shiboken6.wrapInstance
    _tree_view_to_stack: dict[int, object] = {}

    class _MockTreeIndex:
        def __init__(self, row: int, addr: int, stack):
            self._row = row
            self._addr = addr
            self._stack = stack

        def data(self, role=0):
            try:
                return self._stack.tree_view_layer_name(self._addr, self._row)
            except Exception:
                return ""

        def isValid(self):  # noqa: N802
            return True

        @property
        def row(self):
            return self._row

    class _MockTreeModel:
        def __init__(self, addr: int, stack):
            self._addr = addr
            self._stack = stack

        def rowCount(self, parent=None):  # noqa: N802
            try:
                return self._stack.tree_view_row_count(self._addr)
            except Exception:
                return 0

        def index(self, row, col, parent=None):  # noqa: N802
            return _MockTreeIndex(row, self._addr, self._stack)

        def data(self, index, role=0):
            return index.data(role)

    def _patched_wrapInstance(addr, typ):
        obj = _orig_wrapInstance(addr, typ)
        try:
            cname = obj.metaObject().className()
        except Exception:
            cname = ""
        if cname == "QgsLayerTreeView":
            stack = _tree_view_to_stack.get(int(addr))
            if stack is not None:
                try:
                    mock_model = _MockTreeModel(int(addr), stack)

                    def _model_func():
                        return mock_model

                    obj.model = _model_func  # type: ignore[attr-defined]
                    orig_show = getattr(obj, "show", None)

                    def _set_current(idx):
                        try:
                            r = getattr(idx, "_row", 0)
                            if not isinstance(r, int):
                                r = 0
                            stack.tree_view_set_current_row(int(addr), int(r))
                        except Exception:
                            pass

                    obj.setCurrentIndex = _set_current  # type: ignore[attr-defined]
                except Exception:
                    pass
        return obj

    _shiboken6.wrapInstance = _patched_wrapInstance

    try:
        from qgis_render_bridge.mapstack import QgisMapStack as _QgisMapStack

        _orig_create_tree = _QgisMapStack.create_layer_tree_view

        def _patched_create_tree(self, canvas):
            addr = _orig_create_tree(self, canvas)
            _tree_view_to_stack[int(addr)] = self
            return addr

        _QgisMapStack.create_layer_tree_view = _patched_create_tree  # type: ignore[method-assign,assignment]
    except Exception:
        pass
except Exception:
    pass


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
