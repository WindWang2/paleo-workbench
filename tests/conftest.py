from __future__ import annotations

import os

import pytest

# Remaining-suite conftest after the Python product retirement
# (docs/development/python-retirement/): the retired implementation and its
# full pytest suite live under legacy/python_reference (with the original
# conftest). This trimmed conftest serves the active suite only — C++ product
# support tests, native-extension contract tests, QGIS bridge tests, and
# integrity guards — and imports nothing from the retired package.


@pytest.fixture(autouse=True, scope="session")
def isolate_qsettings(tmp_path_factory):
    """Keep QSettings-backed stores off the real user profile for the suite.

    Default-constructed ``QSettings(organization, application)`` instances
    write to the user's real config dir. Redirecting the default path to a
    session temp dir makes every test hermetic suite-wide; tests that need
    stricter per-test isolation (or a pre-seeded store) bind their own
    explicit ini on top.

    Qt 6.11：双参构造 ``QSettings(org, app)`` 不再遵循 ``setDefaultFormat``，
    恒为 NativeFormat（``~/.config``），仅 ``setPath(IniFormat, …)`` 拦不住
    它们——必须同时重定向 ``XDG_CONFIG_HOME``，否则测试读写真实用户配置，
    跨运行互相污染。
    """
    from PySide6.QtCore import QSettings

    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    old_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(settings_dir)
    yield
    if old_xdg is None:
        os.environ.pop("XDG_CONFIG_HOME", None)
    else:
        os.environ["XDG_CONFIG_HOME"] = old_xdg


def _register_qgis_dll_directories() -> None:
    """Windows: make the vendored QGIS + dependency DLLs loadable.

    The retired implementation's loader authority was
    ``paleo_workbench.qgis_runtime.loader``; it is archived now, so on
    Windows this hook degrades to a no-op (bridge tests on Windows must
    arrange their own DLL path). POSIX hosts never needed it.
    """
    if os.name != "nt":
        return
    try:
        import qgis_render_bridge  # noqa: F401
    except Exception:
        pass


_register_qgis_dll_directories()

# PySide6 AFTER any loader registration above.
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication


def pytest_configure(config):
    """Qt platform policy for tests (never force X11/xcb).

    - **CI / headless**: workflows set ``QT_QPA_PLATFORM=offscreen`` — leave it.
    - **Local Wayland session**: leave unset (or clear accidental ``xcb``) so
      Qt uses Wayland; do **not** default to xcb.

    (Inline replacement for the retired ``paleo_workbench.qt_platform``
    helper — same observable policy for the test suite.)
    """
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform == "xcb" and not os.environ.get("PALEO_FORCE_XCB"):
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            os.environ.pop("QT_QPA_PLATFORM", None)

    config.addinivalue_line(
        "markers", "qgis: QGIS production-renderer tests (opt-in bridge build)"
    )
    config.addinivalue_line(
        "markers",
        "welllog_binding: workbench↔WellLogEngine native binding contract "
        "(family retired with the Python product; marker kept for history)",
    )


def pytest_sessionstart(session):
    """Fail-closed gate for required QGIS CI legs (#1147)."""
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
    qtbot tears the test's widgets down — a timer left running by a finished
    test firing during a LATER test's event processing is the classic
    cross-test SIGSEGV signature."""
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
    """Force execution of all DeferredDelete events at the end of every test
    (generic Qt hygiene; product-backend shutdowns retired with the product
    suite). Also sweeps the anonymous top-level helper widgets the Qt style
    engine leaves behind, so they cannot accumulate across tests."""
    yield
    app = QApplication.instance()
    if app is not None:
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QMenu

            for w in app.topLevelWidgets():
                if (
                    w.parentWidget() is None
                    and not w.isVisible()
                    and not w.objectName()
                    and not w.windowTitle()
                ):
                    if isinstance(w, QMenu) and (w.title() or w.actions()):
                        continue  # real menus are not style helpers
                    w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        except Exception:
            pass
