from __future__ import annotations

import pytest

from paleo_workbench.ui import navigation


def test_stage_indices_defined():
    assert hasattr(navigation, "STAGE_INDEX_DATA")
    assert hasattr(navigation, "STAGE_INDEX_INTERPRETATION")
    assert hasattr(navigation, "STAGE_INDEX_MAPPING")
    assert hasattr(navigation, "STAGE_INDEX_REVIEW")

    assert navigation.STAGE_INDEX_DATA == 0
    assert navigation.STAGE_INDEX_INTERPRETATION == 1
    assert navigation.STAGE_INDEX_MAPPING == 2
    assert navigation.STAGE_INDEX_REVIEW == 3


def test_stage_definitions_structure():
    stages = navigation.STAGE_DEFINITIONS
    assert len(stages) == 4
    for idx, s in enumerate(stages):
        assert "name" in s
        assert "badge" in s
        assert "pages" in s
        assert isinstance(s["pages"], list)
        assert len(s["pages"]) > 0


def test_get_stage_for_page():
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_DATA) == 0
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_PREPARATION) == 0

    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_WELL_LOG) == 1
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_SEISMIC) == 1
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_SEQUENCE) == 1
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_STRATIGRAPHY) == 1
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_WELL_SEISMIC_JOINT) == 1

    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_MAPPING) == 2
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_VISUALIZATION) == 2

    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_REVIEW) == 3
    assert navigation.get_stage_for_page(navigation.PAGE_INDEX_HOME) == 3


def test_get_subpages_for_stage():
    assert navigation.get_subpages_for_stage(0) == [
        navigation.PAGE_INDEX_DATA,
        navigation.PAGE_INDEX_PREPARATION,
    ]
    assert navigation.get_subpages_for_stage(1) == [
        navigation.PAGE_INDEX_WELL_LOG,
        navigation.PAGE_INDEX_SEISMIC,
        navigation.PAGE_INDEX_SEQUENCE,
        navigation.PAGE_INDEX_STRATIGRAPHY,
        navigation.PAGE_INDEX_WELL_SEISMIC_JOINT,
    ]
    assert navigation.get_subpages_for_stage(2) == [
        navigation.PAGE_INDEX_MAPPING,
        navigation.PAGE_INDEX_VISUALIZATION,
    ]
    assert navigation.get_subpages_for_stage(3) == [
        navigation.PAGE_INDEX_REVIEW,
        navigation.PAGE_INDEX_HOME,
        navigation.PAGE_INDEX_GEOMODEL,
    ]
