from __future__ import annotations

# Archived-suite bootstrap: make the retired package importable when this
# suite is run from the archive (reference / oracle use only — never part of
# the C++ product; see legacy/python_reference/README.md).
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "product"))

import os

import pytest

# #1427: tests must not assume production-machine core counts — hosted CI
# runners expose 2 cores, where the lazily-created default governor's
# background ceiling (cores − interactive reserve = 1) refuses the
# multi-core admissions several provider/harness tests make. Pin the
# budget's logical-core column for the whole suite; explicit
# ResourceBudget(logical_cores=N) constructions and set_budget() calls in
# individual tests bypass this env and keep working. setdefault keeps a
# caller-provided value authoritative.
os.environ.setdefault("PALEO_BUDGET_CORES", "8")


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

    V10 M-A: both recipes (default self-contained vendor / conda-Qt
    unification via ``PALEO_QGIS_CONDA_QT=1``) are implemented by the single
    loader authority :mod:`paleo_workbench.qgis_runtime.loader`; this hook
    only triggers it before PySide6 is imported (the conda recipe's Qt
    preload must win the race against the wheel's bundled Qt — ADR 0059
    private-ABI rule).

    geotopo: DLL 目录注册后立即预导入桥。Windows 加载器按**模块名**复用
    已载入 DLL——CPython 自带的 libcrypto-3.dll / sqlite3.dll（hashlib /
    sqlite3 触发）与桥链接的 vcpkg 同名构建导出表不同，一旦先载入，
    桥的 qgis_core/gdal 解析到它们即 0xC0000139（找不到指定的程序）。
    采集期先导入桥即锁死正确顺序（无桥环境静默跳过）。
    """
    if os.name != "nt":
        return
    try:
        from paleo_workbench.qgis_runtime.loader import prepare_bridge_load

        prepare_bridge_load()
    except Exception:
        pass
        return
    try:
        import qgis_render_bridge  # noqa: F401
    except Exception:
        pass
    _assert_bridge_origin()


def _assert_bridge_origin() -> None:
    """桥产物必须来自 ``native/qgis_render_bridge/``（V12 M0-5）。

    手写 ``setup.py build_ext --inplace`` 若在仓库根目录执行，会把 .pyd 落到
    **仓库根**；根目录在 ``sys.path`` 里且优先于包目录，于是所有测试与启动
    静默加载这个"影子桥"，包内产物反而失效——"改了源码没生效 / 修复误判为
    生效"都可能由此产生（编辑工具链诊断期踩到过一次）。这里 fail fast。
    """
    import importlib.util
    from pathlib import Path

    try:
        spec = importlib.util.find_spec("qgis_render_bridge")
    except Exception:
        return
    if spec is None or not spec.origin:
        return
    # Archived-suite note: repo root is three levels up from this conftest.
    expected = Path(__file__).resolve().parents[3] / "native" / "qgis_render_bridge"
    origin = Path(spec.origin).resolve()
    if expected not in origin.parents:
        raise RuntimeError(
            f"qgis_render_bridge 从意外位置加载：{origin}\n"
            f"期望位于 {expected} 之下——多半是手工 build_ext --inplace 在"
            "仓库根目录留下的影子产物，请删除后重建（见 docs/development/"
            "qgis-editing-authoring-v12/00-baseline.md §5）。"
        )


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
        # Qt 样式表引擎的孤儿助手清理（e2e/test_a0_style_broadcast 文档串描述的
        # 跨用例滞留控件问题的可收口子集）：每次 setStyleSheet 抛光都会在
        # QStyleSheetStyle 侧实例化隐藏的、无父对象、完全匿名的助手控件
        # （QLineEdit/QToolButton/QFrame 等）。它们不进任何 Qt 父子树，
        # qtbot 的回收够不到，跨用例线性累积（实测每壳循环 +8）；累积到数千后
        # 全局重抛光会逐个触碰它们——在半拆包装器上 segfault（~82% CI hang /
        # #951 族 / dead-shell 崩溃的累积性引信）。这里在 DeferredDelete 冲刷后
        # 对「无父 + 隐藏 + 完全匿名 + 无窗口标题」的顶层控件补 deleteLater。
        # 可见悬浮窗/有标题菜单都不满足条件，不会被误删。
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
                        continue  # 真菜单（有标题/动作）不是样式助手
                    w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        except Exception:
            pass
