"""Independent joint layer visibility (#93)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _pyqtgraph_gl_skip_reason() -> str | None:
    """Probe for a usable pyqtgraph OpenGL context; return a skip reason
    (str) when this host cannot provide one, else ``None``.

    #1498: the ubuntu-latest runner image drifted to Mesa 25.2.8 and its
    GL version string (``3.3 (Compatibility Profile) Mesa 25.2.8-...``) is
    rejected by pyqtgraph's >= OpenGL 2.1 check inside
    ``GLViewWidget.initializeGL``. That check fires from the Qt event loop
    (pytest-qt reports it as "Exceptions caught in Qt event loop"), so it
    cannot be caught around the test's own widget — probe the same code
    path synchronously before the widget is built instead.
    """
    try:
        import pyqtgraph.opengl as gl
    except ImportError:
        return "pyqtgraph.opengl is not importable"

    view = gl.GLViewWidget()
    try:
        view.makeCurrent()
        ctx = view.context()
        if ctx is None or not ctx.isValid():
            return (
                "no usable OpenGL context on this host "
                "(see #1498 for the Mesa 25.2.8 runner-image drift)"
            )
        view.initializeGL()
        return None
    except RuntimeError as exc:
        return (
            f"pyqtgraph rejected this host's GL: {exc} "
            "(#1498: ubuntu-latest runner Mesa 25.2.8 version-string drift)"
        )
    finally:
        try:
            view.doneCurrent()
        except Exception:
            pass
        # ``view`` is parentless: it is destroyed when this function returns
        # (CPython refcounting), which discards any paint event queued by
        # context creation — a leftover failing paint would otherwise
        # resurface in pytest-qt's teardown event processing after the skip.
        view.close()


def test_set_layer_visibility_keeps_renderer_visible_when_volume_off():
    """Volume-off must not hide the whole Renderer3D (wells/fences live there)."""
    from geoviz_well_seismic_3d.joint_widget import WellSeismicJointWidget

    w = WellSeismicJointWidget.__new__(WellSeismicJointWidget)
    w._scene = None
    w._well_items = []
    w._curtain_items = []
    r = MagicMock()
    r.set_planes_visible = MagicMock()
    w._renderer = r
    w.set_well_trajectories = MagicMock()
    w.set_fence_curtains = MagicMock()

    WellSeismicJointWidget.set_layer_visibility(
        w, wells=True, fences=True, volume=False
    )
    r.setVisible.assert_called_with(True)
    r.set_planes_visible.assert_called_with(False)


def test_set_planes_visible_does_not_unhide_volume_in_planes_mode(qtbot):
    """Joint '地震预览体' toggles orthogonal planes, not DualGL volume fill."""
    reason = _pyqtgraph_gl_skip_reason()
    if reason is not None:
        pytest.skip(f"pyqtgraph GL unavailable: {reason}")

    from geoviz_seismic.renderer_3d import Renderer3D
    import numpy as np

    widget = Renderer3D()
    qtbot.addWidget(widget)
    widget.load_volume(np.random.randn(8, 9, 12).astype(np.float32))
    vol = widget._volume_visual
    assert vol is not None
    assert widget._mode == "planes"
    assert vol.visible() is False
    widget.set_planes_visible(True)
    assert vol.visible() is False
    widget.set_planes_visible(False)
    assert vol.visible() is False


def test_renderer_set_planes_visible_toggles_plane_attrs():
    from geoviz_seismic.renderer_3d import Renderer3D

    r = Renderer3D.__new__(Renderer3D)
    plane = MagicMock()
    r._img_il = plane
    r._img_xl = plane
    r._img_t = plane
    r._line_il = None
    r._line_xl = None
    r._line_t = None
    r._volume_visual = None
    r._img_arb = None
    r._line_arb = None
    Renderer3D.set_planes_visible(r, False)
    assert plane.setVisible.call_count >= 3


def test_renderer_tracks_multiple_time_planes_and_global_visibility():
    from geoviz_seismic.renderer_3d import Renderer3D

    r = Renderer3D.__new__(Renderer3D)
    r._loaded = False
    r._time_plane_items = {}
    r._time_slice_positions = []
    r._time_slice_visibility = {}
    r._active_time_pos = None
    r._time_slice_opacity = 0.8
    r._t_pos = 0

    Renderer3D.set_time_slices(
        r,
        [(8, True), (2, False), (8, True)],
        active=8,
        opacity=0.65,
    )

    assert r.get_time_slices() == ((2, False), (8, True))
    assert r._active_time_pos == 8
    assert r._t_pos == 8
    assert r._time_slice_opacity == 0.65

    first_image, first_line = MagicMock(), MagicMock()
    second_image, second_line = MagicMock(), MagicMock()
    r._time_plane_items = {
        2: (first_image, first_line),
        8: (second_image, second_line),
    }
    r._img_il = r._img_xl = None
    r._img_t = second_image
    r._line_il = r._line_xl = None
    r._line_t = second_line
    r._volume_visual = r._img_arb = r._line_arb = None

    Renderer3D.set_planes_visible(r, False)

    for item in (first_image, first_line, second_image, second_line):
        item.setVisible.assert_called_with(False)
