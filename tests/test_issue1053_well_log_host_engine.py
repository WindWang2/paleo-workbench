"""#1053: main well-log screen backend selection (native engine vs Legacy).

Coverage honesty note:

- ``PALEO_USE_WELLLOG_ENGINE=0`` and binding-uninstalled cases exercise the
  REAL production path end to end (real probe, real QPainter tracks).
- The native-engine cases monkeypatch ``engine_adapter.try_import_welllog``
  with a fake ``WellLogView``.  They verify the *selection logic* only —
  engine surface chosen, document submitted, failure falls back.  They are
  NOT a native rendering verification: this environment has no built
  ``welllog`` binding (import fails with GLIBCXX ImportError, so the real
  probe reports "not installed" and the host falls back to Legacy).
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from PySide6.QtWidgets import QFrame

from geoviz import CurveData, WellLogData

import paleo_workbench.viz.hosts.well_log_host as host_module
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter
from paleo_workbench.viz.hosts.well_log_host import WellLogHost
from paleo_workbench.viz.models import VizPayload

_HOST_LOGGER = "paleo_workbench.viz.hosts.well_log_host"


def _payload(n: int = 64) -> VizPayload:
    depth = np.linspace(1000.0, 1000.0 + n, n, dtype=np.float64)
    values = 50.0 + 20.0 * np.sin(np.linspace(0.0, 6.0, n))
    data = WellLogData(
        well_name="W-1053",
        top_depth=float(depth[0]),
        bottom_depth=float(depth[-1]),
        curves=[
            CurveData(
                name="GR",
                unit="API",
                depth=depth,
                values=values,
                display_range=(0.0, 150.0),
            )
        ],
    )
    return VizPayload(kind="well_log", label="W-1053", well_log=data)


class FakeNativeView(QFrame):
    """Duck-typed WellLogView for branch-selection tests (not a renderer)."""

    instances: list["FakeNativeView"] = []

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.submitted: list[dict] = []
        FakeNativeView.instances.append(self)

    def submit_multi_track(self, payload: dict) -> dict:
        self.submitted.append(payload)
        return {
            "curve_count": len(payload["curves"]),
            "track_count": len(payload["tracks"]),
        }


class ExplodingNativeView(QFrame):
    """Binding that imports but explodes when a document is submitted."""

    def submit_multi_track(self, payload: dict) -> dict:
        raise RuntimeError("native submission exploded")


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    FakeNativeView.instances = []
    yield
    FakeNativeView.instances = []


# --- real production paths (no probe monkeypatching) ----------------------


def test_env_off_renders_legacy_real_path(qtbot, monkeypatch):
    """PALEO_USE_WELLLOG_ENGINE=0 must take the real Legacy QPainter path."""
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    assert len(host.canvas.tracks) > 0
    assert host.view_stack.currentWidget() is host.scroll_area
    assert host._engine_view is None
    assert host.export_capabilities() == frozenset({"PNG", "SVG", "PDF"})
    assert host.has_data() is True


def test_default_env_without_binding_falls_back_to_legacy_real_path(
    qtbot, monkeypatch
):
    """Default env + binding genuinely not installed -> real fallback path.

    The precondition is asserted, not simulated: on hosts where the welllog
    binding is built the engine branch is the expected outcome, so this test
    skips rather than lie about which branch ran.
    """
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    _mod, view_cls, _err = engine_adapter.try_import_welllog()
    if view_cls is not None:
        pytest.skip("built welllog binding present: engine branch is expected")

    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    assert len(host.canvas.tracks) > 0
    assert host.view_stack.currentWidget() is host.scroll_area
    assert host._engine_view is None
    # The real probe ran and honestly recorded why the engine was declined.
    assert host._engine_error == "welllog 绑定未安装"


# --- branch-selection tests (monkeypatched probe, NOT native rendering) ---


def test_engine_branch_selected_when_binding_available(qtbot, monkeypatch):
    """BRANCH-SELECTION TEST (#1053): probe patched with a fake view class.

    Env default on + importable binding -> native engine surface owns the
    view, the document is submitted, and the legacy canvas is cleared (#381
    export honesty: engine surface claims PNG only).
    """
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    assert isinstance(host._engine_view, FakeNativeView)
    assert host.view_stack.currentWidget() is host.engine_host
    # Engine owns the view: legacy canvas intentionally empty.
    assert host.canvas.tracks == []
    # One complete document transaction was submitted.
    assert len(host._engine_view.submitted) == 1
    payload = host._engine_view.submitted[0]
    assert payload["curves"][0]["mnemonic"] == "GR"
    assert host._engine_load["curve_count"] == 1
    assert host._engine_load["update_kind"] == "full_replace"
    # #381: engine surface must claim PNG grab only.
    assert host.export_capabilities() == frozenset({"PNG"})
    assert host.has_data() is True
    assert "WellLogEngine" in host.track_bar.text()


def test_env_off_overrides_available_binding(qtbot, monkeypatch):
    """BRANCH-SELECTION TEST: env off wins even when the binding imports."""
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    assert host._engine_view is None
    assert FakeNativeView.instances == []
    assert host.view_stack.currentWidget() is host.scroll_area
    assert len(host.canvas.tracks) > 0
    assert host.export_capabilities() == frozenset({"PNG", "SVG", "PDF"})


def test_engine_submission_failure_falls_back_to_legacy(qtbot, monkeypatch, caplog):
    """BRANCH-SELECTION TEST: engine submit raises -> Legacy fallback, logged.

    No crash, no blank screen: apply still returns True with real QPainter
    tracks on screen, and the native document is released.
    """
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), ExplodingNativeView, object()),
    )
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    with caplog.at_level(logging.WARNING, logger=_HOST_LOGGER):
        assert host.apply(_payload()) is True

    assert len(host.canvas.tracks) > 0
    assert host.view_stack.currentWidget() is host.scroll_area
    assert host._engine_view is None
    assert host._engine_plan is None
    assert "RuntimeError" in (host._engine_error or "")
    assert any(
        "WellLogEngine" in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    )
    # Fallback keeps vector export honest.
    assert host.export_capabilities() == frozenset({"PNG", "SVG", "PDF"})


def test_engine_plan_failure_raises_are_caught_by_apply(qtbot, monkeypatch, caplog):
    """BRANCH-SELECTION TEST: unexpected exception in the engine pipeline
    (here: plan construction) never escapes apply(); the host falls back."""
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )

    def _explode(data):
        raise ValueError("adapter regression")

    monkeypatch.setattr(host_module.engine_adapter, "adapt_well_log_data", _explode)
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    with caplog.at_level(logging.WARNING, logger=_HOST_LOGGER):
        assert host.apply(_payload()) is True

    assert len(host.canvas.tracks) > 0
    assert host.view_stack.currentWidget() is host.scroll_area
    assert host._engine_view is None
    assert "ValueError" in (host._engine_error or "")
    assert any(
        "falling back to Legacy" in record.message for record in caplog.records
    )


def test_engine_to_legacy_switch_releases_native_document(qtbot, monkeypatch):
    """BRANCH-SELECTION TEST: engine -> legacy re-apply must release the
    retained native view/document (no invisible retained session)."""
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    engine_view = host._engine_view
    assert engine_view is not None and host._engine_plan is not None

    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    assert host.apply(_payload()) is True

    # _release_engine_document semantics preserved on the fallback branch.
    assert host._engine_view is None
    assert host._engine_plan is None
    assert host._engine_load is None
    assert host.view_stack.currentWidget() is host.scroll_area
    assert len(host.canvas.tracks) > 0
    assert host.export_capabilities() == frozenset({"PNG", "SVG", "PDF"})

    # clear() after an engine render also drops the retained document.
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    assert host.apply(_payload()) is True
    host.clear()
    assert host._engine_view is None
    assert host._engine_plan is None
    assert host.view_stack.currentWidget() is host.scroll_area
    assert host.canvas.tracks == []
    assert host.has_data() is False


def test_engine_update_of_same_document_reuses_view(qtbot, monkeypatch):
    """BRANCH-SELECTION TEST: same document re-apply keeps the retained view
    (viewport/LOD survive), matching the prediction-panel contract."""
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )
    host = WellLogHost()
    qtbot.addWidget(host.widget)

    assert host.apply(_payload()) is True
    first_view = host._engine_view
    assert host.apply(_payload()) is True
    assert host._engine_view is first_view
    # Identical data: the adapter reuses the retained document (unchanged).
    assert host._engine_load["update_kind"] == "unchanged"
    assert host.view_stack.currentWidget() is host.engine_host
