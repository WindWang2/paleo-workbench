"""#619: catalog id maps publish as one snapshot so unlocked readers cannot see None."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.service import DataCatalogService


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str = "well.las", payload: bytes = b"las-bytes") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def test_list_versions_survives_invalidate_after_ensure(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path))
    real_ensure = service._ensure_maps

    def ensure_then_invalidate():
        result = real_ensure()
        service._invalidate_maps()
        return result

    service._ensure_maps = ensure_then_invalidate
    got = service.list_versions(version.asset_id)
    assert [item.id for item in got] == [version.id]


def test_adapter_asset_for_survives_invalidate_after_ensure(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path))
    adapter = CoreCatalogAdapter(service)
    real_ensure = service._ensure_maps

    def ensure_then_invalidate():
        result = real_ensure()
        service._invalidate_maps()
        return result

    service._ensure_maps = ensure_then_invalidate
    asset = adapter._asset_for(version)
    assert asset is not None
    assert asset.id == version.asset_id


def test_map_readers_survive_concurrent_invalidation(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path))
    adapter = CoreCatalogAdapter(service)
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        while not stop.is_set():
            service._invalidate_maps()
            try:
                with service.batch_save():
                    raise RuntimeError("forced batch rollback")
            except RuntimeError:
                pass

    def reader() -> None:
        try:
            for _ in range(1500):
                service.list_versions(version.asset_id)
                loaded = service.get_version(version.id)
                assert adapter._asset_for(loaded) is not None
        except BaseException as exc:
            errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()
    reader_thread.join(timeout=10)
    stop.set()
    writer_thread.join(timeout=10)
    assert errors == []
