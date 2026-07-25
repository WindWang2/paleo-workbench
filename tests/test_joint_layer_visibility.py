"""Independent joint layer visibility (#93)."""

from __future__ import annotations

from unittest.mock import MagicMock


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
