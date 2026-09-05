"""Regression — a failed project open left a dead shell that killed the window.

A failed shell rebuild (an exception escaping ``AppShell`` construction, e.g.
the time-depth AttributeError during ``bind_project``) leaves
``window.app_shell`` pointing at the OLD shell wrapper whose C++ object the
``deleteLater()`` in ``_refresh_shell`` already destroyed. The next
``_restore_current_shell_after_failed_stop`` (closeEvent after a failed
stop) called ``app_shell.hide()`` on that dead wrapper → ``RuntimeError:
AppShell C++ object already deleted`` (app.py:302) — so the failed open took
the window down with it. ``_refresh_shell`` now skips the teardown of an
already-destroyed shell and simply builds the replacement; these tests pin
that a dead-shell restore rebuilds a usable UI instead of raising.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shiboken6")

import shiboken6

from paleo_workbench.app import PaleoWorkbenchWindow


@pytest.fixture()
def window(qtbot):
    win = PaleoWorkbenchWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def _simulate_failed_rebuild(qtbot, window) -> None:
    """Reproduce the post-crash state after a failed ``_refresh_shell``.

    The failed rebuild detached the old shell and ``deleteLater()``ed it, but
    the replacement never took its place (the ``AppShell`` constructor
    raised) — once the deferred deletion runs, ``app_shell`` wraps a
    destroyed C++ object.
    """
    window.setCentralWidget(None)
    window.app_shell.setParent(None)
    window.app_shell.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(window.app_shell))


def test_refresh_shell_rebuilds_after_dead_shell(qtbot, window):
    _simulate_failed_rebuild(qtbot, window)

    window._refresh_shell()  # used to RuntimeError on the deleted shell

    assert shiboken6.isValid(window.app_shell)
    assert window.app_shell.parent() is window, "replacement must be re-attached"


def test_close_after_failed_stop_with_dead_shell_rebuilds(
    qtbot, window, monkeypatch
):
    """The reported cascade: closeEvent → failed stop → restore path must
    not call Qt methods on the destroyed shell."""
    _simulate_failed_rebuild(qtbot, window)

    class _FakeMessageBox:
        calls: ClassVar[list[tuple]] = []

        @staticmethod
        def warning(*args, **kwargs):
            _FakeMessageBox.calls.append(args)

    class _FakeApp:
        @staticmethod
        def platformName() -> str:
            # NOT "offscreen": force the user-facing warning branch so the
            # test does not depend on the host Qt platform plugin.
            return "testhost"

    monkeypatch.setattr(
        window.project_controller, "shutdown_current_session", lambda: False
    )
    monkeypatch.setattr("paleo_workbench.app.QMessageBox", _FakeMessageBox)
    monkeypatch.setattr("paleo_workbench.app.QApplication", _FakeApp)

    window.close()  # used to RuntimeError from _refresh_shell → hide()

    assert shiboken6.isValid(window.app_shell), (
        "a failed stop must restore a usable shell, not crash on the dead one"
    )
    assert window.isVisible(), "close was refused (background stop failed); window stays open"
    assert _FakeMessageBox.calls, "user must still get the failed-stop warning"
