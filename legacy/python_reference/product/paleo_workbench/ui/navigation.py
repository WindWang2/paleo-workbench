"""Hub page model for the UI-v2 Ribbon shell (4+1 pages).

The old 11-page flat stack is gone. Pages are now five hubs, each hosting
one or more sub-modules (the former pages) behind an in-page switcher:

- 数据 (hub 0): 项目概述 (the old 首页) · 数据管理 (the old 数据页)
- 井 (hub 1): 测井预测 · 层序格架 · 地层对比
- 地震 (hub 2): 地震预测 · 井震联合 3D
- 编图 (hub 3): 编图画布 · 数据制备 · 成图审核
- 可视化 (hub 4): the old 可视化 page, kept as a temporary validation surface
"""

from __future__ import annotations

# Hub page indices (0 ~ 4)
PAGE_INDEX_DATA = 0
PAGE_INDEX_WELL = 1
PAGE_INDEX_SEISMIC = 2
PAGE_INDEX_MAPPING = 3
PAGE_INDEX_VISUALIZATION = 4

HUB_NAMES: list[str] = ["数据", "井", "地震", "编图", "可视化"]

# Sub-module registry: hub index -> [(key, title), ...] in switcher order.
# Hubs with a single entry render no switcher (可视化 is a direct page).
SUBMODULES: dict[int, list[tuple[str, str]]] = {
    PAGE_INDEX_DATA: [("overview", "项目概述"), ("management", "数据管理")],
    PAGE_INDEX_WELL: [
        ("well_log", "测井预测"),
        ("sequence", "层序格架"),
        ("stratigraphy", "地层对比"),
    ],
    PAGE_INDEX_SEISMIC: [("seismic", "地震预测"), ("geomodel", "井震联合 3D")],
    PAGE_INDEX_MAPPING: [
        ("canvas", "编图画布"),
        ("preparation", "数据制备"),
        ("review", "成图审核"),
    ],
    PAGE_INDEX_VISUALIZATION: [("viz", "可视化")],
}

# Default sub-module per hub (数据 opens on the 项目概述 home surface).
DEFAULT_SUBMODULE: dict[int, str] = {
    PAGE_INDEX_DATA: "overview",
    PAGE_INDEX_WELL: "well_log",
    PAGE_INDEX_SEISMIC: "seismic",
    PAGE_INDEX_MAPPING: "canvas",
    PAGE_INDEX_VISUALIZATION: "viz",
}


def submodule_keys(hub_index: int) -> list[str]:
    """Return the sub-module keys of a hub in switcher order."""
    return [key for key, _title in SUBMODULES.get(hub_index, [])]


def submodule_title(hub_index: int, key: str) -> str:
    """Return the display title of a sub-module (empty string when unknown)."""
    for k, title in SUBMODULES.get(hub_index, []):
        if k == key:
            return title
    return ""


# Pre-v2 flat page index (0~10) -> (hub index, sub-module key). The home
# page's module-relationship cards still emit the legacy ordinals.
LEGACY_PAGE_TO_HUB: dict[int, tuple[int, str]] = {
    0: (PAGE_INDEX_DATA, "overview"),
    1: (PAGE_INDEX_DATA, "management"),
    2: (PAGE_INDEX_WELL, "well_log"),
    3: (PAGE_INDEX_SEISMIC, "seismic"),
    4: (PAGE_INDEX_WELL, "sequence"),
    5: (PAGE_INDEX_WELL, "stratigraphy"),
    6: (PAGE_INDEX_VISUALIZATION, "viz"),
    7: (PAGE_INDEX_MAPPING, "preparation"),
    8: (PAGE_INDEX_MAPPING, "canvas"),
    9: (PAGE_INDEX_MAPPING, "review"),
    10: (PAGE_INDEX_SEISMIC, "geomodel"),
}
