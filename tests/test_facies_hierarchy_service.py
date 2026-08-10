"""T-MULTISCALE: geo-viz-engine facies hierarchy (相/亚相/微相) native integration.

Covers the headless hierarchy service (detection / building / level metadata)
and the PaleoMapHost branching: hierarchical payloads switch the canvas to
``load_hierarchy`` (zoom-driven level display); flat payloads keep the existing
``load_features`` path (backward compatible).
"""

from __future__ import annotations

import pytest

from paleo_workbench.viz.facies_hierarchy_service import (
    AUTO_LEVEL,
    FACIES_LEVELS,
    LEVEL_DISPLAY,
    build_facies_hierarchy,
    hierarchy_levels_present,
    is_hierarchical_feature_set,
    level_choices,
)


def _facies(fid: str, name: str, level: str, parent_id: str | None = None) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": fid,
            # geo-viz-engine reads the name from `facies` (then `name`).
            "facies": name,
            "level": level,
            "parent_id": parent_id,
        },
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    }


def _flat(fid: str, name: str) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": fid, "facies_name": name},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    }


HIERARCHY_FEATURES = [
    _facies("f1", "三角洲", "facies"),
    _facies("s1", "三角洲前缘", "sub_facies", parent_id="f1"),
    _facies("m1", "水下分流河道", "micro_facies", parent_id="s1"),
]


# --------------------------------------------------------------------------- #
# Service: detection + level metadata
# --------------------------------------------------------------------------- #


def test_flat_features_are_not_hierarchical():
    assert is_hierarchical_feature_set([_flat("a", "x"), _flat("b", "y")]) is False


def test_hierarchical_features_detected():
    assert is_hierarchical_feature_set(HIERARCHY_FEATURES) is True


def test_unrecognized_level_is_treated_as_flat():
    # An unknown level value must not opt into the hierarchy path.
    feat = _flat("a", "x")
    feat["properties"]["level"] = "epoch"  # not a facies level
    assert is_hierarchical_feature_set([feat]) is False


def test_levels_present_ordered_coarse_to_fine():
    assert hierarchy_levels_present(HIERARCHY_FEATURES) == list(FACIES_LEVELS)


def test_levels_present_subset_and_dedup():
    feats = [_facies("f1", "A", "facies"), _facies("f2", "B", "facies"),
             _facies("s1", "C", "sub_facies")]
    assert hierarchy_levels_present(feats) == ["facies", "sub_facies"]


def test_level_choices_lead_with_auto_then_present_levels():
    choices = level_choices(HIERARCHY_FEATURES)
    assert choices[0] == (AUTO_LEVEL, "自动（按比例尺切换）")
    values = [v for v, _ in choices[1:]]
    assert values == list(FACIES_LEVELS)
    assert all(LEVEL_DISPLAY[v] for v in values)


def test_level_choices_empty_for_flat():
    assert level_choices([_flat("a", "x")]) == []


# --------------------------------------------------------------------------- #
# Service: hierarchy build (geo-viz-engine FaciesHierarchy)
# --------------------------------------------------------------------------- #


def test_build_hierarchy_resolves_levels_and_ancestors():
    h = build_facies_hierarchy(HIERARCHY_FEATURES)
    facies = h.get_features_at_level("facies")
    subs = h.get_features_at_level("sub_facies")
    micros = h.get_features_at_level("micro_facies")
    assert len(facies) == 1 and len(subs) == 1 and len(micros) == 1
    assert facies[0].facies_name == "三角洲"
    # Ancestor chain of the micro-facies climbs sub_facies → facies.
    ancestors = h.get_ancestors("m1")
    ancestor_names = {a.facies_name for a in ancestors}
    assert {"三角洲前缘", "三角洲"}.issubset(ancestor_names)


def test_build_hierarchy_rejects_flat_features():
    with pytest.raises(ValueError):
        build_facies_hierarchy([_flat("a", "x")])


# --------------------------------------------------------------------------- #
# PaleoMapHost branching (uses the real canvas under offscreen Qt)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _payload(kind: str, features):
    from paleo_workbench.viz.models import VizPayload

    return VizPayload(kind=kind, label="t", map_features=features)


def test_host_flat_payload_keeps_load_features_path(_qapp):
    from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost

    host = PaleoMapHost()
    assert host.apply(_payload("map", [_flat("a", "x"), _flat("b", "y")])) is True
    assert host.hierarchy_active is False
    assert host.available_levels() == []
    # set_level is a no-op when not hierarchical.
    assert host.set_level("facies") is False


def test_host_hierarchical_payload_switches_to_load_hierarchy(_qapp):
    from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost

    host = PaleoMapHost()
    assert host.apply(_payload("map", HIERARCHY_FEATURES)) is True
    assert host.hierarchy_active is True
    assert host.available_levels() == list(FACIES_LEVELS)


def test_host_set_level_locks_and_releases(_qapp):
    from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost

    host = PaleoMapHost()
    host.apply(_payload("map", HIERARCHY_FEATURES))
    assert host.set_level("micro_facies") is True
    assert host.set_level(AUTO_LEVEL) is True          # release → scale-driven
    assert host.set_level(None) is True                # None also releases
    assert host.set_level("nonexistent") is False      # unknown level rejected


def test_host_clear_resets_hierarchy_state(_qapp):
    from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost

    host = PaleoMapHost()
    host.apply(_payload("map", HIERARCHY_FEATURES))
    assert host.hierarchy_active is True
    host.clear()
    assert host.hierarchy_active is False
    assert host.available_levels() == []
