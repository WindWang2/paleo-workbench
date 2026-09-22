"""Modeling clip → joint slice mapping (#92)."""

from __future__ import annotations

from paleo_workbench.viz.joint_clip_map import (
    ModelingClipState,
    clip_value_to_index,
    modeling_clip_to_joint_slices,
)


def test_clip_value_to_index_endpoints():
    assert clip_value_to_index(0, 100) == 0
    assert clip_value_to_index(100, 100) == 99
    assert clip_value_to_index(50, 11) == 5


def test_modeling_clip_drives_enabled_axes_only():
    clip = ModelingClipState(
        x_enabled=True,
        x_value=50,
        x_keep_positive=True,
        y_enabled=False,
        y_value=0,
        y_keep_positive=True,
        z_enabled=True,
        z_value=100,
        z_keep_positive=True,
    )
    focus = modeling_clip_to_joint_slices(
        clip,
        n_inline=101,
        n_crossline=41,
        n_sample=51,
        current_il=3,
        current_xl=7,
        current_t=1,
    )
    assert focus.il_index == 50
    assert focus.xl_index == 7  # kept current
    assert focus.t_index == 50
    assert focus.il_from_clip and not focus.xl_from_clip and focus.t_from_clip
