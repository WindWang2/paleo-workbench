"""Issue #849 — catalog concurrency / search-consistency / bulk-import batch.

1. ``promote_version`` allocates version numbers outside the service lock →
   concurrent promotes of the same asset commit duplicates ([1,2,2]).
2. ``search_assets`` SQLite index path vs canonical scan path disagree on
   LIKE wildcards (%/_ literal vs wildcard) and boolean metadata serialization
   ("1" vs "True") — same query, different rows depending on index freshness.
3. Folder import registers per-file with full-document write + fsync (O(N²)
   bytes); the #397 ``batch_save`` exists but the import loop never used it.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    get_catalog,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.service import place_managed_file
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.data_lifecycle_controller import DataLifecycleController


def _make_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture()
def project_path(tmp_path: Path) -> Path:
    return _make_project_path(tmp_path)


@pytest.fixture()
def service(project_path: Path):
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


@pytest.fixture()
def catalog(project_path: Path):
    svc = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(svc)
    set_catalog(adapter)
    yield adapter
    reset_catalog()
    svc.close()


def _make_source(tmp_path: Path, name: str = "well.las", payload: bytes = b"log data") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# ------------------------------------------------------------- 1. promote race


def test_promote_version_concurrent_promotes_get_unique_numbers(
    service, tmp_path, monkeypatch
):
    """Concurrent promotes of the same asset must commit unique version numbers.

    Regression (audit #849-1): ``promote_version`` numbered the version inside
    ``_build_version`` — OUTSIDE the service lock — so racing promotes both
    computed ``max+1`` and committed duplicates like [1,2,2].
    """
    src = _make_source(tmp_path, payload=b"raw")
    raw = service.import_raw(src)
    service.register_intermediate(
        raw.asset_id,
        _make_source(tmp_path, name="grid.npz", payload=b"grid"),
        parent_version_ids=[raw.id],
    )
    intermediate = service.list_versions(raw.asset_id)[-1]
    assert intermediate.stage is DataStage.INTERMEDIATE

    n_threads = 6
    barrier = threading.Barrier(n_threads)
    numbers: list[int] = []
    errors: list[Exception] = []

    real_place = place_managed_file

    def slow_place(*args, **kwargs):
        # Widen the outside-lock build window so every thread computes its
        # version number before any of them commits (deterministic repro of
        # the race that produced duplicated numbers).
        time.sleep(0.05)
        return real_place(*args, **kwargs)

    monkeypatch.setattr(
        "paleo_workbench.catalog.service.place_managed_file", slow_place
    )

    def worker():
        try:
            barrier.wait()
            promoted = service.promote_version(
                intermediate.id, reviewed_by="qc", note="race"
            )
            numbers.append(promoted.version_number)
        except Exception as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(numbers) == n_threads
    assert len(set(numbers)) == n_threads, (
        f"duplicate version numbers from concurrent promotes: {sorted(numbers)}"
    )
    # The promote run rows carry unique, ordered numbers too.
    numbers.sort()
    assert numbers == list(range(intermediate.version_number + 1, numbers[-1] + 1))


# ------------------------------------------------- 2. index/scan search parity


def test_search_wildcard_text_index_and_scan_agree(service, tmp_path):
    """% / _ in a search term are literal on BOTH paths."""
    for name, payload in [
        ("well 100% done.las", b"a"),
        ("well A_B.las", b"b"),
        ("well AXB.las", b"b2"),  # would match A_B as a WILDCARD, not literally
        ("plain well.las", b"c"),
    ]:
        service.import_raw(_make_source(tmp_path, name=name, payload=payload))

    # Fresh index path.
    index_rows = service.search_assets(text="100%")
    # Force the canonical scan by corrupting index freshness.
    service._index.reset()
    scan_rows = service.search_assets(text="100%")

    assert [a.name for a in index_rows] == [a.name for a in scan_rows]
    assert [a.name for a in scan_rows] == ["well 100% done.las"]

    service.ensure_index_ready()
    index_underscore = service.search_assets(text="A_B")
    service._index.reset()
    scan_underscore = service.search_assets(text="A_B")
    assert [a.name for a in index_underscore] == [a.name for a in scan_underscore]
    # Literal matching: only the real A_B name, never the wildcard-expanded AXB.
    assert [a.name for a in scan_underscore] == ["well A_B.las"]


def test_search_boolean_metadata_index_and_scan_agree(service, tmp_path):
    """Boolean metadata matches by its JSON serialization on BOTH paths."""
    a = service.import_raw(_make_source(tmp_path, name="governed.las", payload=b"d"))
    b = service.import_raw(_make_source(tmp_path, name="plain.las", payload=b"e"))
    service.update_asset_metadata(a.asset_id, {"reviewed": True, "score": 3})
    service.update_asset_metadata(b.asset_id, {"reviewed": "True", "score": 3})

    index_rows = service.search_assets(metadata={"reviewed": "1"})
    service._index.reset()
    scan_rows = service.search_assets(metadata={"reviewed": "1"})

    assert [x.id for x in index_rows] == [x.id for x in scan_rows]
    # Boolean true serializes to "1"; the string "True" stays "True" — the two
    # assets are DISTINCT values and must not be conflated on either path.
    assert [x.id for x in scan_rows] == [a.asset_id]

    service.ensure_index_ready()
    index_true = service.search_assets(metadata={"reviewed": "True"})
    service._index.reset()
    scan_true = service.search_assets(metadata={"reviewed": "True"})
    assert [x.id for x in index_true] == [x.id for x in scan_true] == [b.asset_id]

    service.ensure_index_ready()
    index_score = service.search_assets(metadata={"score": "3"})
    service._index.reset()
    scan_score = service.search_assets(metadata={"score": "3"})
    assert [x.id for x in index_score] == [x.id for x in scan_score]
    assert len(scan_score) == 2


# ----------------------------------------------- 3. folder import batch_save


def test_folder_import_registration_uses_single_canonical_write(
    catalog, tmp_path, monkeypatch
):
    """Registering a folder of resources must produce ONE canonical write.

    Regression (audit #849-3): each ``register_resource_input`` call triggered
    a full-document serialize + fsync (O(N²) bytes on 100s of files); the
    ``batch_save`` context from #397 was wired for bootstrap imports but not
    for the UI folder-import loop.
    """
    service = catalog.service
    calls = 0
    real_save = service._store.save

    def counted(document):
        nonlocal calls
        calls += 1
        return real_save(document)

    monkeypatch.setattr(service._store, "save", counted)

    controller = DataLifecycleController(None)
    resources = []
    for i in range(30):
        src = _make_source(tmp_path, name=f"w{i:02d}.las", payload=f"data-{i}".encode())
        resources.append(
            ResourceItem(
                id=f"res_{i}",
                name=src.name,
                path=str(src),
                type="well_log",
                format="las",
                status="parsed",
                checksum=None,
            )
        )

    controller.register_imported_resources(resources)

    assert controller.last_registration_failures == []
    assert calls == 1, f"expected 1 canonical write, got {calls}"
    assert len(service.document.assets) == 30
    assert all(
        any(v.asset_id == a.id for v in service.document.versions)
        for a in service.document.assets
    )
    assert get_catalog() is not None


def test_folder_import_registration_survives_a_bad_file(catalog, tmp_path, monkeypatch):
    """One failing resource inside the batch must not discard the others."""
    service = catalog.service
    controller = DataLifecycleController(None)

    resources = []
    for i in range(5):
        src = _make_source(tmp_path, name=f"ok{i}.las", payload=b"ok")
        resources.append(
            ResourceItem(
                id=f"res_{i}",
                name=src.name,
                path=str(src),
                type="well_log",
                format="las",
                status="parsed",
                checksum=None,
            )
        )
    broken = ResourceItem(
        id="res_broken",
        name="missing.las",
        path=str(tmp_path / "missing.las"),
        type="well_log",
        format="las",
        status="parsed",
        checksum=None,
    )
    resources.insert(2, broken)

    controller.register_imported_resources(resources)

    assert len(controller.last_registration_failures) == 1
    # The five good files persisted despite the bad one.
    assert len(service.document.assets) == 5