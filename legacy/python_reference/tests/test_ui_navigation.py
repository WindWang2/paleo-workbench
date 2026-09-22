from __future__ import annotations

from paleo_workbench.ui import navigation


def test_hub_indices_defined():
    assert navigation.PAGE_INDEX_DATA == 0
    assert navigation.PAGE_INDEX_WELL == 1
    assert navigation.PAGE_INDEX_SEISMIC == 2
    assert navigation.PAGE_INDEX_MAPPING == 3
    assert navigation.PAGE_INDEX_VISUALIZATION == 4


def test_hub_names_cover_every_hub():
    assert len(navigation.HUB_NAMES) == 5
    assert set(navigation.SUBMODULES) == set(range(5))
    assert set(navigation.DEFAULT_SUBMODULE) == set(range(5))


def test_submodule_structure():
    for hub_index, entries in navigation.SUBMODULES.items():
        assert entries, f"hub {hub_index} must host at least one sub-module"
        keys = [key for key, _title in entries]
        assert len(keys) == len(set(keys)), f"hub {hub_index} has duplicate keys"
        for _key, title in entries:
            assert title, f"hub {hub_index} has an untitled sub-module"
        assert navigation.DEFAULT_SUBMODULE[hub_index] in keys


def test_submodule_keys_and_title():
    assert navigation.submodule_keys(navigation.PAGE_INDEX_WELL) == [
        "well_log", "sequence", "stratigraphy",
    ]
    assert navigation.submodule_title(navigation.PAGE_INDEX_WELL, "sequence") == "层序格架"
    assert navigation.submodule_title(navigation.PAGE_INDEX_WELL, "nope") == ""
    # 可视化 is a single-module hub (no in-page switcher).
    assert navigation.submodule_keys(navigation.PAGE_INDEX_VISUALIZATION) == ["viz"]


def test_legacy_page_map_covers_all_eleven_old_pages():
    assert sorted(navigation.LEGACY_PAGE_TO_HUB) == list(range(11))
    for hub_index, key in navigation.LEGACY_PAGE_TO_HUB.values():
        assert key in navigation.submodule_keys(hub_index)


def test_legacy_geomodel_lives_in_seismic_hub():
    """External contract (test_well_seismic_joint_page): the joint-analysis
    page is the 地震 hub's 井震联合 3D sub-module after the hub merge."""
    assert navigation.LEGACY_PAGE_TO_HUB[10] == (
        navigation.PAGE_INDEX_SEISMIC, "geomodel",
    )
