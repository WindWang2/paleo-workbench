"""Joint slice drive must rebuild planes via public apply API (#92 residual)."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_set_slice_indices_uses_apply_slice_positions():
    from geoviz_well_seismic_3d.joint_widget import WellSeismicJointWidget

    w = WellSeismicJointWidget.__new__(WellSeismicJointWidget)
    r = MagicMock()
    r.apply_slice_positions = MagicMock()
    w._renderer = r
    w._scene = None  # no scene → fall through to renderer apply path
    WellSeismicJointWidget.set_slice_indices(w, 10, 20, 30)
    r.apply_slice_positions.assert_called_once_with(10, 20, 30, rebuild=True)


def test_set_camera_pose_delegates_to_renderer():
    from geoviz_well_seismic_3d.joint_widget import WellSeismicJointWidget

    w = WellSeismicJointWidget.__new__(WellSeismicJointWidget)
    r = MagicMock()
    r.set_camera_pose = MagicMock()
    w._renderer = r
    WellSeismicJointWidget.set_camera_pose(w, distance=100, elevation=10, azimuth=20)
    r.set_camera_pose.assert_called_once()
