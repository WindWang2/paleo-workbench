"""Session-local curve display and merge layout for the Legacy well-log canvas.

The GeoViz renderer accepts a ``CurveTrack`` containing one or more curves.
This module keeps the user-facing layout separate from raw LAS data: curve
identities are index-based (so duplicate mnemonics remain distinct), and every
group is capped at three curves for a readable header and scale readout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from geoviz import CurveTrack, WellLogData, build_qpainter_tracks

MAX_CURVES_PER_TRACK = 3


class CurveGroupLimitError(ValueError):
    """A merge would create a curve track with more than three curves."""


def curve_keys_for(curves: Iterable[object]) -> tuple[str, ...]:
    """Return stable, duplicate-safe identities for one loaded curve sequence."""
    return tuple(
        f"curve:{index}:{str(getattr(curve, 'name', '') or '未命名')}"
        for index, curve in enumerate(curves)
    )


@dataclass(frozen=True)
class CurveTrackLayout:
    """Which curves are visible and how visible curves are grouped."""

    curve_keys: tuple[str, ...]
    visible_curve_keys: frozenset[str]
    groups: tuple[tuple[str, ...], ...]

    def group_for(self, curve_key: str) -> tuple[str, ...]:
        for group in self.groups:
            if curve_key in group:
                return group
        raise KeyError(curve_key)

    def with_visible(self, curve_key: str, visible: bool) -> "CurveTrackLayout":
        if curve_key not in self.curve_keys:
            raise KeyError(curve_key)
        keys = set(self.visible_curve_keys)
        if visible:
            keys.add(curve_key)
        else:
            keys.discard(curve_key)
        return CurveTrackLayout(self.curve_keys, frozenset(keys), self.groups)

    def merge(self, curve_key: str, *, onto: str) -> "CurveTrackLayout":
        """Move *curve_key* into *onto*'s group, preserving group order."""
        if curve_key not in self.curve_keys or onto not in self.curve_keys:
            raise KeyError(curve_key if curve_key not in self.curve_keys else onto)
        if curve_key == onto:
            return self
        source_group = self.group_for(curve_key)
        target_group = self.group_for(onto)
        if source_group == target_group:
            return self
        if len(target_group) >= MAX_CURVES_PER_TRACK:
            raise CurveGroupLimitError(
                f"每个合并井道最多包含 {MAX_CURVES_PER_TRACK} 条曲线"
            )

        groups: list[tuple[str, ...]] = []
        for group in self.groups:
            if group == source_group:
                remainder = tuple(key for key in group if key != curve_key)
                if remainder:
                    groups.append(remainder)
            elif group == target_group:
                # The dragged curve is named first in the merged header, e.g.
                # dragging GR onto AC creates ``GR+AC``. This mirrors the
                # direct-manipulation action and keeps the settings tree
                # readable after expanding the group.
                groups.append((curve_key, *group))
            else:
                groups.append(group)
        return CurveTrackLayout(self.curve_keys, self.visible_curve_keys, tuple(groups))

    def unmerge(self, curve_key: str) -> "CurveTrackLayout":
        """Restore every curve in *curve_key*'s group to its own track."""
        target_group = self.group_for(curve_key)
        if len(target_group) <= 1:
            return self
        groups: list[tuple[str, ...]] = []
        for group in self.groups:
            if group == target_group:
                groups.extend((key,) for key in group)
            else:
                groups.append(group)
        return CurveTrackLayout(self.curve_keys, self.visible_curve_keys, tuple(groups))


def default_curve_track_layout(curves: Iterable[object]) -> CurveTrackLayout:
    """Create the six-curve default, guaranteeing GR when it is available."""
    curves = tuple(curves)
    keys = curve_keys_for(curves)
    shown = list(keys[:6])
    gr_key = next(
        (
            key
            for key, curve in zip(keys, curves)
            if str(getattr(curve, "name", "")).strip().upper() == "GR"
        ),
        None,
    )
    if gr_key is not None and gr_key not in shown:
        if shown:
            shown[-1] = gr_key
        else:
            shown.append(gr_key)
    return CurveTrackLayout(
        curve_keys=keys,
        visible_curve_keys=frozenset(shown),
        groups=tuple((key,) for key in keys),
    )


def reconcile_curve_track_layout(
    layout: CurveTrackLayout | None, curves: Iterable[object]
) -> CurveTrackLayout:
    """Keep a layout only while it describes the current well's curve schema."""
    keys = curve_keys_for(curves)
    if layout is None or layout.curve_keys != keys:
        return default_curve_track_layout(curves)
    return layout


def build_configured_well_log_tracks(
    data: WellLogData, layout: CurveTrackLayout
) -> list[object]:
    """Build legacy tracks from a user-selected, bounded curve grouping."""
    layout = reconcile_curve_track_layout(layout, data.curves)
    # Disable GeoViz's global mnemonic-based defaults: settings own every
    # merge and use index-based identities so duplicate curve names stay safe.
    base_tracks = build_qpainter_tracks(data, merge_groups=[])
    curve_positions = [
        index for index, track in enumerate(base_tracks) if isinstance(track, CurveTrack)
    ]
    if not curve_positions:
        return base_tracks

    source_tracks = [base_tracks[index] for index in curve_positions]
    curve_by_key = dict(zip(layout.curve_keys, source_tracks))
    grouped_tracks: list[CurveTrack] = []
    for group in layout.groups:
        members = [
            curve_by_key[key]
            for key in group
            if key in layout.visible_curve_keys and key in curve_by_key
        ]
        if not members:
            continue
        curves = [track.curves[0] for track in members]
        grouped = CurveTrack(
            curves=curves,
            label=" / ".join(str(curve.name) for curve in curves),
            width=140,
            log_scale=any(bool(getattr(track, "_log_scale", False)) for track in members),
        )
        grouped.set_depth_range(data.top_depth, data.bottom_depth)
        grouped_tracks.append(grouped)

    first = curve_positions[0]
    last = curve_positions[-1]
    return [*base_tracks[:first], *grouped_tracks, *base_tracks[last + 1 :]]
