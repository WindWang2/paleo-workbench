from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolate_qsettings(tmp_path_factory):
    """Keep QSettings-backed stores off the real user profile for the suite.

    Default-constructed ``QSettings(organization, application)`` instances —
    e.g. the workbench layout persistence — write to the user's real config
    dir. Redirecting the default path to a session temp dir makes every test
    hermetic suite-wide; tests that need stricter per-test isolation (or a
    pre-seeded store) bind their own explicit ini on top.

    Qt 6.11：双参构造 ``QSettings(org, app)`` 不再遵循 ``setDefaultFormat``，
    恒为 NativeFormat（``~/.config``），仅 ``setPath(IniFormat, …)`` 拦不住
    它们——必须同时重定向 ``XDG_CONFIG_HOME``，否则测试读写真实用户配置，
    跨运行互相污染（布局 blob 会被上一次运行的状态污染）。
    """
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

    V8: two supported recipes, selected by ``PALEO_QGIS_CONDA_QT``:

    * **default (self-contained vendor)** — the authoring-style build whose
      ``output/bin`` carries every third-party runtime the QGIS DLLs need
      (incl. Qt6Core5Compat).  The loader authority is
      ``qgis_style.ensure_qgis_bridge_dll_dirs`` (vendor bin + PySide6 dir +
      MSVCP pre-pin); PySide6 must match the vendor build's Qt minor
      (6.8.x).  No conda preloads here: mixing a second Qt family breaks
      the load with WinError 127.
    * ``PALEO_QGIS_CONDA_QT=1`` (conda-Qt unification, cartography legacy
      machine recipe) — neutral minimal vendor dir + conda deps bin with
      the conda Qt set preloaded BEFORE PySide6 (ADR 0059 private-ABI
      rule); the osgeo python binding resolves its own gdal from the deps
      prefix (cp312 ABI match).

    Both are overridable via env so CI keeps its own layout.  No-op when
    the directories are absent (bridge stays unimportable and the qgis
    marker keeps skipping honestly).
    """
    if os.name != "nt":
        return
    conda_qt = os.environ.get("PALEO_QGIS_CONDA_QT", "").strip().lower() in {
        "1", "true", "yes", "on"}
    if not conda_qt:
        # V8 default recipe: single loader authority, no Qt preloads.
        try:
            from paleo_workbench.mapping.qgis_style import (
                ensure_qgis_bridge_dll_dirs,
            )

            ensure_qgis_bridge_dll_dirs()
        except Exception:
            pass
        return
    for sub in (
        os.path.join(os.environ.get(
            "PALEO_QGIS_BUILD_DIR",
            r"C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor"),
            "output", "bin"),
        os.path.join(os.environ.get(
            "PALEO_QGIS_DEPS_DIR", r"C:\Users\wangj.KEVIN\paleo-qgis-deps"),
            "Library", "bin"),
    ):
        if os.path.isdir(sub):
            try:
                os.add_dll_directory(sub)
            except (OSError, ValueError):
                pass
    # Windows loader order: qgis_*.dll dependents (Qt Multimedia, QCA,
    # keychain, Core5Compat, protobuf-lite, spatialindex, ...) must be
    # pre-resolved before the qgis DLLs themselves, otherwise the import
    # fails with ERROR_MOD_NOT_FOUND even with the directories registered
    # (first Windows bridge build, v7). Preload once per session.
    try:
        import ctypes
        import glob as _glob

        _preload_dirs = [
            os.path.join(os.environ.get(
                "PALEO_QGIS_DEPS_DIR", r"C:\Users\wangj.KEVIN\paleo-qgis-deps"),
                "Library", "bin"),
        ]
        # Core Qt set FIRST: PySide6 (imported below) and QGIS then
        # share this one Qt, never the wheel-bundled copy.  Deliberately
        # NOT the Qml/Quick/extra-widgets family: preloading conda's
        # Qt6Qml (etc.) before PySide6 poisons the wheel's bundled Qml
        # modules; those resolve on demand via add_dll_directory instead.
        _preload_names = ("Qt6Core", "Qt6Gui", "Qt6Widgets",
                          "Qt6Multimedia", "qca-qt6", "qt6keychain",
                          "Qt6Core5Compat", "libprotobuf-lite", "Qt6Network",
                          "Qt6Sql", "Qt6Concurrent", "Qt6Xml",
                          "Qt6Svg", "Qt6PrintSupport",
                          "spatialindex-64", "exiv2", "zip",
                          # Geo C libs FIRST (bisected): native extensions
                          # (grid_render_core import chain) otherwise pin
                          # incompatible sqlite3/zlib/expat process-wide and
                          # qgis_core fails with ERROR_MOD_NOT_FOUND.  These
                          # are the exact versions QGIS was built against.
                          "sqlite3", "zlib", "libexpat", "gdal",
                          "geos_c", "proj_9", "spatialite", "zstd")
        for _name in _preload_names:
            for _dir in _preload_dirs:
                for _hit in _glob.glob(os.path.join(_dir, _name + ".dll")):
                    try:
                        ctypes.WinDLL(_hit)
                    except OSError:
                        pass
                    break
    except Exception:
        pass


_register_qgis_dll_directories()

# PySide6 AFTER the loader registration above.  In the default V8 recipe
# the process Qt IS PySide6's own wheel copy (single-Qt rule); in the
# conda-Qt legacy recipe the conda set preloaded above is the one Qt for
# the whole process (PySide6 + bridge + vendored QGIS), mirroring the CI
# leg's LD_LIBRARY_PATH unification (ADR 0059 private-ABI rule).
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer
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
    # 共享 QgsProject 卫生：Qt 析构期间禁止重入 QGIS API，销毁路径收不掉
    # 的镜像层在这里确定性收尾（否则泄漏进下一个用例的镜像计数）。
    try:
        from paleo_workbench.ui.qgis_stack.canvas_shim import shutdown_live_shims

        shutdown_live_shims()
    except ImportError:
        pass  # 桥未构建时无 shim 存在
    app = QApplication.instance()
    if app is not None:
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        except Exception:
            pass
