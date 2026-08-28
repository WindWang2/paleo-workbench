"""#1046 — paged lazy entity navigation (no hard truncation).

The tree hard-capped every entity group at ``MAX_ENTITY_CHILDREN = 500``:
beyond that, wells were invisible in the tree (geological entities without
even an overflow note) — 99.5% of a 50k-well survey unreachable by browsing.
These tests pin the paged population contract:

* groups materialize one page at a time (bounded allocation for 100k wells),
* every entity stays reachable — paging appends, never hides,
* ``highlight_well`` materializes the target page on demand (Map → Data),
* geological entities page identically (the previously silent branch).
"""

from __future__ import annotations

import time

import pytest

from paleo_workbench.project.models import ProjectDocument, ProjectMeta
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


class _Well:
    __slots__ = ("id", "name", "uwi", "coordinate_status")

    def __init__(self, wid: str, name: str) -> None:
        self.id = wid
        self.name = name
        self.uwi = ""
        self.coordinate_status = ""


class _GeoEntity:
    __slots__ = ("id", "name", "entity_kind")

    def __init__(self, eid: str, name: str) -> None:
        self.id = eid
        self.name = name
        self.entity_kind = "horizon"


class _Project:
    def __init__(self, wells, geo_entities=()) -> None:
        self.wells = wells
        self.seismic_surveys = []
        self.geological_entities = list(geo_entities)
        self.entity_asset_links = []


def _group_by_label(tree: NavigationTree, label: str):
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item.text(0).startswith(label):
            return item
    return None


def test_well_group_pages_instead_of_capping(qtbot):
    wells = [_Well(f"well-{i:05d}", f"井-{i:05d}") for i in range(5_000)]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project(wells))

    group = _group_by_label(tree, "🛢 井")
    assert group is not None
    # one materialized page + the show-more affordance — never 5000 items
    assert group.childCount() <= 501, group.childCount()
    # and nothing is lost: the pager tracks the full population
    assert tree.entity_population("well") == 5_000


def test_show_more_appends_pages_until_all_wells_reachable(qtbot):
    wells = [_Well(f"well-{i:05d}", f"井-{i:05d}") for i in range(1_200)]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project(wells))

    group = _group_by_label(tree, "🛢 井")
    guard = 0
    while tree._activate_next_entity_page("well") and guard < 10:
        guard += 1
    assert guard < 10
    # every well is now a browsable leaf — paging appended, never truncated
    names = {group.child(i).text(0) for i in range(group.childCount())}
    assert any("井-01199" in text for text in names)
    assert tree.entity_population("well") == 1_200


def test_highlight_well_materializes_the_target_page(qtbot):
    wells = [_Well(f"well-{i:05d}", f"井-{i:05d}") for i in range(4_000)]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project(wells))

    assert tree.highlight_well("well-03999") is True
    current = tree.currentItem()
    assert current is not None
    query = current.data(0, __import__("PySide6").QtCore.Qt.ItemDataRole.UserRole)
    assert query.node_value == "well-03999"


def test_geological_entities_page_equally(qtbot):
    entities = [_GeoEntity(f"geo-{i:05d}", f"层位{i:05d}") for i in range(900)]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project([], geo_entities=entities))

    group = _group_by_label(tree, "地质解释")
    assert group is not None
    assert group.childCount() <= 501
    assert tree.entity_population("geological_entity") == 900
    while tree._activate_next_entity_page("geological_entity"):
        pass
    texts = {group.child(i).text(0) for i in range(group.childCount())}
    assert any("层位00899" in text for text in texts)


def test_100k_well_project_builds_fast(qtbot):
    wells = [_Well(f"well-{i:06d}", f"井-{i:06d}") for i in range(100_000)]
    tree = NavigationTree()
    qtbot.addWidget(tree)

    start = time.perf_counter()
    tree.set_project(_Project(wells))
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, f"100k-well tree build took {elapsed:.1f}s"
    group = _group_by_label(tree, "🛢 井")
    assert group.childCount() <= 501
    assert tree.entity_population("well") == 100_000


# ---------------------------------------------------------------------------
# Review round-2 regression coverage (rebuild semantics)
# ---------------------------------------------------------------------------


def test_repeated_set_project_does_not_duplicate_children(qtbot):
    wells = [_Well(f"well-{i:04d}", f"井-{i:04d}") for i in range(30)]
    tree = NavigationTree()
    qtbot.addWidget(tree)

    tree.set_project(_Project(wells))
    tree.set_project(_Project(wells))
    tree.set_project(_Project(wells))

    group = _group_by_label(tree, "🛢 井")
    assert group.childCount() == 30, group.childCount()
    assert tree.entity_population("well") == 30


def test_set_project_with_new_population_replaces_children(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project([_Well(f"old-{i}", f"旧井{i}") for i in range(10)]))
    tree.set_project(_Project([_Well("new-1", "新井1")]))

    group = _group_by_label(tree, "🛢 井")
    texts = [group.child(i).text(0) for i in range(group.childCount())]
    assert len(texts) == 1
    assert "新井1" in texts[0]
    assert not any("旧井" in t for t in texts)


def test_set_project_none_clears_wells(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project([_Well(f"w-{i}", f"井{i}") for i in range(5)]))

    tree.set_project(_Project([]))

    group = _group_by_label(tree, "🛢 井")
    texts = [group.child(i).text(0) for i in range(group.childCount())]
    assert tree.entity_population("well") == 0
    assert any("暂无" in t for t in texts), texts


def test_selection_beyond_page_one_is_restored_without_later_refilter(qtbot):
    """The selected well beyond page 1 must be restored during the rebuild —
    and paging further must NOT re-emit a filter for the stale selection."""
    wells = [_Well(f"well-{i:05d}", f"井-{i:05d}") for i in range(1_500)]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(_Project(wells))
    tree.highlight_well("well-01499")  # selection deep in page 3
    assert tree.currentItem() is not None

    filter_events: list[object] = []
    tree.filter_query_changed.connect(lambda q: filter_events.append(q))
    # a domain refresh rebuilds with the selection preserved
    tree.set_project(_Project(wells))
    current = tree.currentItem()
    assert current is not None

    # paging further must not spontaneously re-select/refilter
    filter_events.clear()
    while tree._activate_next_entity_page("well"):
        pass
    stray = [q for q in filter_events if q.node_type == "entity" and q.node_value == "well-01499"]
    assert not stray, "paging re-fired the stale selection filter"
