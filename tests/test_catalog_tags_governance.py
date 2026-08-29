"""Tag governance API tests: bulk add/remove, usage stats, search, delete,
merge, rename-collision policy, and multi-tag (AND/OR) asset search.

These pin the goal requirements: consistent normalization, collision-safe
rename, no dangling associations, catalog/SQLite consistency, and single
canonical writes for bulk operations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import CatalogError, DataStage, Tag
from paleo_workbench.catalog.service import DataCatalogService


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str, payload: bytes = b"data") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _seed(service, tmp_path, count=3):
    versions = [
        service.import_raw(_make_source(tmp_path, f"f{i}.las", f"bytes-{i}".encode()))
        for i in range(count)
    ]
    return versions


# --- bulk add / remove -----------------------------------------------------


def test_bulk_add_tag_single_write_and_associations(service, tmp_path):
    versions = _seed(service, tmp_path, 3)
    revision_before = service.document.catalog_revision

    tag = service.bulk_add_tag(
        "研究区", asset_ids=[v.asset_id for v in versions[:2]],
        version_ids=[versions[2].id],
    )

    assert service.document.catalog_revision == revision_before + 1
    assert len(service.find_assets_by_tag("研究区")) == 2
    assert service.find_versions_by_tag("研究区") == [versions[2].id]
    assert tag.name == "研究区"


def test_bulk_add_tag_is_idempotent(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("qc", asset_ids=ids)
    revision = service.document.catalog_revision

    service.bulk_add_tag("QC", asset_ids=ids)  # normalized duplicate

    assert service.document.catalog_revision == revision  # no-op: no save


def test_bulk_add_tag_rejects_unknown_target(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    with pytest.raises(CatalogError):
        service.bulk_add_tag("x", asset_ids=[versions[0].asset_id, "asset-none"])
    # Nothing was written.
    assert service.find_assets_by_tag("x") == []


def test_bulk_remove_tag_single_write(service, tmp_path):
    versions = _seed(service, tmp_path, 3)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("重点井", asset_ids=ids)
    revision = service.document.catalog_revision

    service.bulk_remove_tag("重点井", asset_ids=ids[:2])

    assert service.document.catalog_revision == revision + 1
    assert service.find_assets_by_tag("重点井") == [ids[2]]


def test_bulk_remove_unknown_tag_is_noop(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    revision = service.document.catalog_revision
    service.bulk_remove_tag("missing", asset_ids=[versions[0].asset_id])
    assert service.document.catalog_revision == revision


# --- usage / search / delete ----------------------------------------------


def test_tag_usage_counts_assets_and_versions_apart(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    service.add_tag("正式数据", asset_id=versions[0].asset_id)
    service.add_tag("正式数据", asset_id=versions[1].asset_id)
    service.add_tag("最终版", version_id=versions[0].id)

    usage = service.tag_usage()
    formal = next(u for u in usage.values() if u["name"] == "正式数据")
    assert formal["assets"] == 2 and formal["versions"] == 0
    final = next(u for u in usage.values() if u["name"] == "最终版")
    assert final["assets"] == 0 and final["versions"] == 1


def test_search_tags_matches_normalized_substring(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    service.add_tag("Seismic 2026", asset_id=versions[0].asset_id)
    service.add_tag("重点井", asset_id=versions[0].asset_id)

    assert [t.name for t in service.search_tags("seismic")] == ["seismic 2026"]
    assert {t.name for t in service.search_tags("井")} == {"重点井"}
    assert service.search_tags("nomatch") == []
    assert len(service.search_tags("")) == 2
    assert len(service.search_tags("", limit=1)) == 1


def test_delete_unused_tag_and_prune(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    service.add_tag("孤儿", asset_id=versions[0].asset_id)
    service.remove_tag("孤儿", asset_id=versions[0].asset_id)

    removed = service.delete_unused_tag("孤儿")
    assert removed.name == "孤儿"
    assert "孤儿" not in [t.name for t in service.list_tags()]


def test_delete_unused_tag_refuses_in_use(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    service.add_tag("在用", asset_id=versions[0].asset_id)
    with pytest.raises(CatalogError, match="still in use"):
        service.delete_unused_tag("在用")


def test_prune_unused_tags_leaves_used_alone(service, tmp_path):
    versions = _seed(service, tmp_path, 1)
    service.add_tag("在用", asset_id=versions[0].asset_id)
    service.document.tags.append(Tag(name="unused-a"))

    removed = service.prune_unused_tags()

    names = {t.name for t in service.list_tags()}
    assert "在用" in names
    assert "unused-a" not in names
    assert [t.name for t in removed] == ["unused-a"]


# --- rename collision / merge ---------------------------------------------


def test_rename_collision_error_policy(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    service.add_tag("a-tag", asset_id=versions[0].asset_id)
    service.add_tag("b-tag", asset_id=versions[1].asset_id)

    with pytest.raises(CatalogError, match="merge"):
        service.rename_tag("a-tag", "B-Tag", on_collision="error")

    # State untouched: both tags keep their associations.
    assert service.find_assets_by_tag("a-tag") == [versions[0].asset_id]
    assert service.find_assets_by_tag("b-tag") == [versions[1].asset_id]


def test_rename_collision_default_still_merges(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    service.add_tag("a-tag", asset_id=versions[0].asset_id)
    service.add_tag("b-tag", asset_id=versions[1].asset_id)

    service.rename_tag("a-tag", "b-tag")

    assert len(service.list_tags()) == 1
    assert sorted(service.find_assets_by_tag("b-tag")) == sorted(
        [versions[0].asset_id, versions[1].asset_id]
    )


def test_merge_tags_repoints_associations(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    service.add_tag("2026-08", version_id=versions[0].id)
    service.add_tag("08-2026", version_id=versions[1].id)

    service.merge_tags("08-2026", "2026-08")

    assert sorted(service.find_versions_by_tag("2026-08")) == sorted(
        [versions[0].id, versions[1].id]
    )
    # No dangling association: the source tag entity is gone entirely.
    dangling = [
        tid
        for ids in service.document.version_tags.values()
        for tid in ids
        if tid not in {t.id for t in service.document.tags}
    ]
    assert dangling == []


def test_merge_tags_requires_both_tags(service, tmp_path):
    with pytest.raises(CatalogError):
        service.merge_tags("missing", "also-missing")


# --- transactional safety (review round) -----------------------------------


def test_failed_merge_rolls_back_in_memory_state(service, tmp_path, monkeypatch):
    """A failed canonical save must not leave the merge half-applied in
    memory (which a later successful write would silently persist)."""
    versions = _seed(service, tmp_path, 2)
    service.add_tag("源", asset_id=versions[0].asset_id)
    service.add_tag("目标", asset_id=versions[1].asset_id)
    before = service.document.model_dump()

    def _boom(*_a, **_k):
        raise OSError("injected disk failure")

    monkeypatch.setattr(type(service), "_flush_canonical_locked", _boom)
    with pytest.raises(OSError):
        service.merge_tags("源", "目标")
    monkeypatch.undo()

    assert service.document.model_dump() == before
    # A later write persists the ROLLED-BACK state, not the failed merge.
    service.add_tag("后续", asset_id=versions[0].asset_id)
    assert {t.name for t in service.list_tags()} == {"源", "目标", "后续"}


def test_failed_rename_rolls_back_name(service, tmp_path, monkeypatch):
    versions = _seed(service, tmp_path, 1)
    service.add_tag("原名", asset_id=versions[0].asset_id)

    def _boom(*_a, **_k):
        raise OSError("injected disk failure")

    monkeypatch.setattr(type(service), "_flush_canonical_locked", _boom)
    with pytest.raises(OSError):
        service.rename_tag("原名", "新名")
    monkeypatch.undo()

    assert [t.name for t in service.list_tags()] == ["原名"]
    assert service.find_assets_by_tag("原名") == [versions[0].asset_id]


def test_create_tag_entity_without_association(service, tmp_path):
    """Tag Manager '新建' uses this single-transaction create — no anchor
    asset, no add-then-remove partial states."""
    versions = _seed(service, tmp_path, 1)
    service.add_tag("在用", asset_id=versions[0].asset_id)

    tag = service.create_tag("Final Report")

    assert tag.name == "final report"
    usage = service.tag_usage()
    assert usage[tag.id]["assets"] == 0 and usage[tag.id]["versions"] == 0
    assert service.find_assets_by_tag("final report") == []
    # Idempotent on the normalized name.
    again = service.create_tag("FINAL   report")
    assert again.id == tag.id
    assert len([t for t in service.list_tags() if t.name == "final report"]) == 1
    # And it is deletable as unused right away.
    service.delete_unused_tag("final report")
    assert "final report" not in [t.name for t in service.list_tags()]


# --- multi-tag search -------------------------------------------------------


def test_search_assets_multi_tag_and(service, tmp_path):
    versions = _seed(service, tmp_path, 3)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("地震", asset_ids=ids[:2])
    service.bulk_add_tag("重点井", asset_ids=ids)

    found = service.search_assets(tags=["地震", "重点井"], tag_op="and")
    assert sorted(a.id for a in found) == sorted(ids[:2])


def test_search_assets_multi_tag_or(service, tmp_path):
    versions = _seed(service, tmp_path, 3)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("甲", asset_ids=[ids[0]])
    service.bulk_add_tag("乙", asset_ids=[ids[2]])

    found = service.search_assets(tags=["甲", "乙"], tag_op="or")
    assert sorted(a.id for a in found) == sorted([ids[0], ids[2]])


def test_search_assets_multi_tag_combines_with_stage_and_text(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("qc", asset_ids=ids)
    service.register_version(
        ids[0],
        _make_source(tmp_path, "out.bin", b"out"),
        DataStage.OUTPUT,
        parent_version_ids=[versions[0].id],
    )

    found = service.search_assets(
        text="f0", tags=["qc"], stage=DataStage.OUTPUT, tag_op="and"
    )
    assert [a.id for a in found] == [ids[0]]


def test_search_assets_rejects_bad_tag_op(service, tmp_path):
    with pytest.raises(ValueError):
        service.search_assets(tags=["a"], tag_op="xor")


def test_multi_tag_search_works_without_index(service, tmp_path):
    """The in-memory fallback path must agree with the index path."""
    versions = _seed(service, tmp_path, 3)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("t1", asset_ids=ids[:2])
    service.bulk_add_tag("t2", asset_ids=ids[1:])

    via_index = sorted(
        a.id for a in service.search_assets(tags=["t1", "t2"], tag_op="and")
    )
    service._index.close()  # force the document-scan fallback
    via_scan = sorted(
        a.id for a in service.search_assets(tags=["t1", "t2"], tag_op="and")
    )
    assert via_index == via_scan == [ids[1]]


# --- persistence / index consistency ---------------------------------------


def test_bulk_and_governance_ops_survive_reopen(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    ids = [v.asset_id for v in versions]
    service.bulk_add_tag("持久", asset_ids=ids, version_ids=[versions[0].id])
    project_path = service.project_path
    service.close()

    reopened = DataCatalogService.open(project_path)
    try:
        assert sorted(reopened.find_assets_by_tag("持久")) == sorted(ids)
        usage = reopened.tag_usage()
        assert next(u for u in usage.values() if u["name"] == "持久")["versions"] == 1
    finally:
        reopened.close()


def test_governance_ops_keep_sqlite_index_fresh(service, tmp_path):
    versions = _seed(service, tmp_path, 2)
    service.bulk_add_tag("同步", asset_ids=[v.asset_id for v in versions])
    service.prune_unused_tags()

    # Index freshness guard: revision must match and the index must answer.
    assert service.index_revision() == service.document.catalog_revision
    assert len(service._index.search_assets(tags=["同步"], tag_op="and")) == 2
    assert service._index.search_assets(tags=["同步"], tag_op="and")
