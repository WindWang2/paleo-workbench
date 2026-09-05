"""Native symbology dialog bridge contract (requires the bridge).

The dialogs run modally inside the native bridge.  These tests drive them
headlessly: a queued Qt event closes/accepts the active modal widget, which
also proves the QGIS widgets live on the same QApplication as the PySide6
host (single Qt runtime) and that ownership never leaks into Python.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QPushButton,
)

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

from paleo_workbench.ui.map_symbology_bridge import (
    SymbologyBridgeError,
    open_renderer_properties,
    open_style_manager,
    open_symbol_selector,
)


def _style(**overrides: Any) -> dict[str, Any]:
    style = {"fill": "#6c8ebf", "stroke": "#26364d", "stroke_width": 1.0}
    style.update(overrides)
    return style


def _accept_active_modal(remaining_ms: int = 3000) -> None:
    """Click the OK button of the active native modal dialog (polling).

    The dialog may open later than the timer fires under load (full-suite
    QGIS runs); asserting here would raise inside the event loop of an
    unrelated later test, so poll and give up silently — the owning test
    still fails on its own assertion if the dialog never appeared.
    """
    application = QApplication.instance()
    dialog = application.activeModalWidget()
    if dialog is None:
        if remaining_ms > 0:
            QTimer.singleShot(100, lambda: _accept_active_modal(remaining_ms - 100))
        return
    buttons = dialog.findChildren(QDialogButtonBox)
    if buttons:
        accept = buttons[0].button(QDialogButtonBox.StandardButton.Ok)
        if accept is not None:
            accept.click()
            return
    # Fallback for dialogs without a button box.
    for push in dialog.findChildren(QPushButton):
        if push.text().lower() in {"ok", "apply", "close"}:
            push.click()
            return
    dialog.reject()


def _cancel_active_modal(remaining_ms: int = 3000) -> None:
    dialog = QApplication.instance().activeModalWidget()
    if dialog is None:
        if remaining_ms > 0:
            QTimer.singleShot(100, lambda: _cancel_active_modal(remaining_ms - 100))
        return
    dialog.reject()


def _run_with_timer(delay_ms: int, action) -> None:
    QTimer.singleShot(delay_ms, action)


def test_renderer_dialog_accept_returns_updated_payload(qtbot) -> None:
    _run_with_timer(400, _accept_active_modal)
    result = open_renderer_properties(
        None,
        title="Symbology — Facies",
        features=(),
        crs="EPSG:3857",
        fields=("lithology", "facies"),
        style=_style(),
    )
    assert result is not None
    payload = result["qgis_style"]
    assert payload["renderer_xml"]
    assert payload["revision"] == 1


def test_renderer_dialog_cancel_returns_none(qtbot) -> None:
    _run_with_timer(400, _cancel_active_modal)
    result = open_renderer_properties(
        None,
        title="Symbology — Facies",
        features=(),
        crs="EPSG:3857",
        fields=("lithology",),
        style=_style(),
    )
    assert result is None


def test_symbol_selector_requires_existing_payload(qtbot) -> None:
    with pytest.raises(SymbologyBridgeError, match="payload"):
        open_symbol_selector(
            None,
            title="Symbol",
            symbol_index=0,
            style=_style(),
        )


def test_symbol_selector_edits_first_symbol(qtbot) -> None:
    from paleo_workbench.mapping.qgis_style import migrate_legacy_style

    migrated = migrate_legacy_style(_style(), "Polygon")
    assert migrated is not None
    styled = _style(qgis_style=migrated.to_dict())
    _run_with_timer(600, _accept_active_modal)
    result = open_symbol_selector(
        None,
        title="Symbol — layer",
        symbol_index=0,
        crs="EPSG:3857",
        style=styled,
    )
    assert result is not None
    updated = result["qgis_style"]
    assert updated["renderer_xml"] == migrated.renderer_xml or updated["revision"] > migrated.revision


def test_invalid_current_payload_raises_typed_error(qtbot) -> None:
    # No modal can appear here (validation raises synchronously) — arming
    # a cancel timer would leak it into the next test's event loop.
    with pytest.raises(SymbologyBridgeError):
        open_renderer_properties(
            None,
            title="broken",
            style=_style(qgis_style={"renderer_xml": "<junk/>"}),
        )


def test_style_manager_opens_and_closes(qtbot, tmp_path) -> None:
    db_path = tmp_path / "paleo-style.sqlite"
    _run_with_timer(600, _cancel_active_modal)
    accepted = open_style_manager(None, style_db_path=str(db_path))
    assert accepted is False  # cancelled, but the database was created
    assert db_path.exists()


def test_style_manager_requires_a_path(qtbot) -> None:
    with pytest.raises(SymbologyBridgeError):
        open_style_manager(None, style_db_path="")
