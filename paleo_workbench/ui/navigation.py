"""Stable page indices and workflow stage definitions for AppShell navigation (avoid magic numbers).

Stage model (M2 redesign): the workflow opens on the 首页 overview, so the
home page belongs to stage ❶ and the stepper highlights stage 1 on launch
(it used to highlight the *last* stage because home was filed under
成图与审核). 井震联合 stays OUT of the interpretation stage by external
contract (test_well_seismic_joint_page) — it is a map-verification surface.
"""

from __future__ import annotations

# Individual page indices (0 ~ 10)
PAGE_INDEX_HOME = 0
PAGE_INDEX_DATA = 1
PAGE_INDEX_WELL_LOG = 2
PAGE_INDEX_SEISMIC = 3
PAGE_INDEX_SEQUENCE = 4
PAGE_INDEX_STRATIGRAPHY = 5
PAGE_INDEX_VISUALIZATION = 6
PAGE_INDEX_PREPARATION = 7
PAGE_INDEX_MAPPING = 8
PAGE_INDEX_REVIEW = 9
PAGE_INDEX_GEOMODEL = 10
# 井位地图 absorbed into the Data page as a collapsible panel (§18).
# Joint analysis absorbed into PAGE_INDEX_GEOMODEL (PRD #85 / #91)

# Stage indices (0 ~ 3)
STAGE_INDEX_DATA = 0
STAGE_INDEX_INTERPRETATION = 1
STAGE_INDEX_MAPPING = 2
STAGE_INDEX_REVIEW = 3

# Workflow Stage definitions (4-Stage Pipeline)
STAGE_DEFINITIONS: list[dict] = [
    {
        "index": STAGE_INDEX_DATA,
        "name": "数据与预处理",
        "badge": "❶",
        "pages": [PAGE_INDEX_HOME, PAGE_INDEX_DATA, PAGE_INDEX_PREPARATION],
    },
    {
        "index": STAGE_INDEX_INTERPRETATION,
        "name": "综合解释",
        "badge": "❷",
        "pages": [
            PAGE_INDEX_WELL_LOG,
            PAGE_INDEX_SEISMIC,
            PAGE_INDEX_SEQUENCE,
            PAGE_INDEX_STRATIGRAPHY,
        ],
    },
    {
        "index": STAGE_INDEX_MAPPING,
        "name": "古地理编图",
        "badge": "❸",
        "pages": [PAGE_INDEX_MAPPING, PAGE_INDEX_VISUALIZATION],
    },
    {
        "index": STAGE_INDEX_REVIEW,
        "name": "成图与审核",
        "badge": "❹",
        "pages": [PAGE_INDEX_REVIEW, PAGE_INDEX_GEOMODEL],
    },
]


def get_stage_for_page(page_index: int) -> int:
    """Return the stage index (0~3) containing the given page index."""
    for stage in STAGE_DEFINITIONS:
        if page_index in stage["pages"]:
            return stage["index"]
    return STAGE_INDEX_DATA


def get_subpages_for_stage(stage_index: int) -> list[int]:
    """Return the list of page indices belonging to the specified stage index."""
    if 0 <= stage_index < len(STAGE_DEFINITIONS):
        return list(STAGE_DEFINITIONS[stage_index]["pages"])
    return []
