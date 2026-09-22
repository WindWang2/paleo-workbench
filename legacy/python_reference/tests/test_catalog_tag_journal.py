"""Issue #1182 — tag mutators no longer pay the up-front usage snapshot.

Every tag mutation used to deep-copy the whole tag list AND both association
maps BEFORE doing anything, charging O(tags + associations) on the success
path. The mutators now keep a lazy journal of only the entries they actually
touch; rollback replays it to restore the exact pre-call state.

Success-path tests prove no bulk copy runs (the snapshot helpers are gone
and journaling touches only the affected keys); failure tests make ``_save``
raise and assert the document is restored exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import paleo_workbench.catalog.tags as tags_module
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(f"payload-{name}".encode())
    return src


@pytest.fixture
def service(tmp_path: Path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


@pytest.fixture
def populated(service: DataCatalogService, tmp_path: Path):
    """One asset with two versions and a couple of associated tags."""
    v1 = service.import_raw(_make_source(tmp_path, "a.las"))
    v2 = service.register_version(
        v1.asset_id, _make_source(tmp_path, "a2.las"), DataStage.RAW
    )
    service.add_tags(["alpha", "beta"], version_id=v1.id)
    service.add_tags(["beta"], version_id=v2.id)
    return v1, v2


def _document_state(service) -> tuple:
    """Comparable full snapshot of the tag-bearing document state."""
    doc = service.document
    return (
        [(t.id, t.name, t.display_name) for t in doc.tags],
        {k: list(v) for k, v in doc.asset_tags.items()},
        {k: list(v) for k, v in doc.version_tags.items()},
    )


# --------------------------------------------------------------- success path


def test_snapshot_helpers_are_gone_and_mutations_succeed(service, populated):
    """No tag mutation builds an O(tags+associations) snapshot anymore."""
    v1, _v2 = populated
    # The bulk-copy helpers no longer exist on the collaborator module.
    assert not hasattr(tags_module, "_usage_snapshot")
    assert not hasattr(tags_module, "_restore_snapshot")

    # Every mutating entry point still works end to end:
    service.remove_tag("beta", version_id=v1.id)
    service.rename_tag("alpha", "alpha-renamed")
    service.merge_tags("beta", "alpha-renamed")
    service.create_tag("solo")
    service.bulk_add_tag("bulk", version_ids=[v1.id])
    service.bulk_remove_tag("bulk", version_ids=[v1.id])
    service.delete_unused_tag("solo")
    service.add_tag("fresh", version_id=v1.id)
    removed = service.prune_unused_tags()
    assert isinstance(removed, list)


def test_remove_tag_journals_only_the_touched_key(
    service, populated, monkeypatch
):
    """The journal captures the one association key being mutated."""
    v1, _v2 = populated
    journaled: list[tuple[str, str]] = []
    real_record = tags_module._TagJournal.record_list

    def counting_record(self, attr, key):
        journaled.append((attr, key))
        return real_record(self, attr, key)

    monkeypatch.setattr(tags_module._TagJournal, "record_list", counting_record)
    service.remove_tag("beta", version_id=v1.id)
    assert journaled == [("version_tags", v1.id)]


# --------------------------------------------------------------- failure path


def failing_save(monkeypatch):
    """Patch ``DataCatalogService._save`` to fail while the context is active."""
    from contextlib import contextmanager

    @contextmanager
    def _failing():
        def _fail(self, dirty=None):
            raise RuntimeError("canonical save failed")

        with monkeypatch.context() as patcher:
            patcher.setattr(DataCatalogService, "_save", _fail)
            yield

    return _failing()


def test_remove_tag_rollback_restores_exact_state(
    service, populated, monkeypatch
):
    v1, _v2 = populated
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.remove_tag("beta", version_id=v1.id)
    assert _document_state(service) == before


def test_rename_tag_rollback_restores_exact_state(service, populated, monkeypatch):
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.rename_tag("alpha", "totally-new")
    assert _document_state(service) == before
    assert service._tag_by_name("alpha") is not None
    assert service._tag_by_name("totally-new") is None


def test_merge_tags_rollback_restores_exact_state(service, populated, monkeypatch):
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.merge_tags("beta", "alpha")
    assert _document_state(service) == before
    assert service._tag_by_name("beta") is not None
    assert service._tag_by_name("alpha") is not None


def test_bulk_add_tag_rollback_restores_exact_state(
    service, populated, monkeypatch
):
    v1, _v2 = populated
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.bulk_add_tag("newbulk", version_ids=[v1.id])
    assert _document_state(service) == before
    assert service._tag_by_name("newbulk") is None


def test_bulk_remove_tag_rollback_restores_exact_state(
    service, populated, monkeypatch
):
    v1, v2 = populated
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.bulk_remove_tag("beta", version_ids=[v1.id, v2.id])
    assert _document_state(service) == before


def test_delete_unused_tag_rollback_restores_exact_state(
    service, populated, monkeypatch
):
    service.create_tag("loner")
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.delete_unused_tag("loner")
    assert _document_state(service) == before


def test_prune_unused_tags_rollback_restores_exact_state_and_order(
    service, populated, monkeypatch
):
    service.create_tag("loner1")
    service.create_tag("loner2")
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.prune_unused_tags()
    assert _document_state(service) == before
    # Exact list ORDER survived the failed multi-removal (positions are
    # journaled, not just membership).
    assert [t.name for t in service.document.tags] == [
        "alpha",
        "beta",
        "loner1",
        "loner2",
    ]


def test_failed_bulk_add_cleans_up_created_tag_and_created_keys(
    service, populated, monkeypatch
):
    """A tag CREATED inside the failed batch disappears again, including
    association keys that did not exist before the call."""
    v1, _v2 = populated
    asset_id = v1.asset_id
    assert asset_id not in service.document.asset_tags  # key will be created
    before = _document_state(service)
    with failing_save(monkeypatch):
        with pytest.raises(RuntimeError):
            service.bulk_add_tag("brand-new", asset_ids=[asset_id])
    assert _document_state(service) == before
    assert service._tag_by_name("brand-new") is None
    assert asset_id not in service.document.asset_tags
