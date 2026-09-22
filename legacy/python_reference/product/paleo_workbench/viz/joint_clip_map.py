"""Map modeling GPU clip UI → joint orthogonal slice indices (PRD #85 / #92).

One-way: modeling clip sliders drive joint IL/XL/Time focus. Does not require
a shared OpenGL context.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelingClipState:
    """UI clip card state (0–100 sliders, enable flags, keep-positive dirs)."""

    x_enabled: bool
    x_value: int  # 0..100
    x_keep_positive: bool  # True = keep x >= val side in modeling UI index 0
    y_enabled: bool
    y_value: int
    y_keep_positive: bool
    z_enabled: bool
    z_value: int
    z_keep_positive: bool


@dataclass(frozen=True)
class JointSliceFocus:
    """Preview-volume indices for joint Renderer3D / scene."""

    il_index: int
    xl_index: int
    t_index: int
    # Which axes were driven by an enabled clip plane
    il_from_clip: bool
    xl_from_clip: bool
    t_from_clip: bool


def clip_value_to_index(value_0_100: int, n: int) -> int:
    """Map 0–100 slider to discrete index in [0, n-1]."""
    if n <= 1:
        return 0
    v = max(0, min(100, int(value_0_100)))
    return int(round(v / 100.0 * (n - 1)))


def modeling_clip_to_joint_slices(
    clip: ModelingClipState,
    *,
    n_inline: int,
    n_crossline: int,
    n_sample: int,
    current_il: int = 0,
    current_xl: int = 0,
    current_t: int = 0,
) -> JointSliceFocus:
    """Translate modeling clip UI into joint orthogonal slice indices.

    Convention (aligned with modeling Local axes used in clip card):
    - X slider → inline index (volume axis 0)
    - Y slider → crossline index (volume axis 1)
    - Z slider → time/sample index (volume axis 2)

    Disabled axes keep ``current_*`` (clamped). Direction flags reserved for
    future half-space ROI; S2 maps position only.
    """
    ni = max(1, int(n_inline))
    nx = max(1, int(n_crossline))
    nt = max(1, int(n_sample))

    def _clamp(i: int, n: int) -> int:
        return max(0, min(n - 1, int(i)))

    if clip.x_enabled:
        il = clip_value_to_index(clip.x_value, ni)
        il_from = True
    else:
        il = _clamp(current_il, ni)
        il_from = False
    if clip.y_enabled:
        xl = clip_value_to_index(clip.y_value, nx)
        xl_from = True
    else:
        xl = _clamp(current_xl, nx)
        xl_from = False
    if clip.z_enabled:
        t = clip_value_to_index(clip.z_value, nt)
        t_from = True
    else:
        t = _clamp(current_t, nt)
        t_from = False
    return JointSliceFocus(
        il_index=il,
        xl_index=xl,
        t_index=t,
        il_from_clip=il_from,
        xl_from_clip=xl_from,
        t_from_clip=t_from,
    )
