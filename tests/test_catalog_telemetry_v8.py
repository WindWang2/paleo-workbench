"""V8 M9 — catalog lifecycle telemetry (durable GC/recovery events) and
batch asset pre-warm."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.telemetry import (
    read_catalog_events,
    record_catalog_event,
)


@pytest.fixture()
def service(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


class TestTelemetry:
    def test_event_roundtrip(self, tmp_path):
        project_path = tmp_path / "p" / "x.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        assert record_catalog_event(project_path, "test.event", detail={"n": 1})
        events = read_catalog_events(project_path)
        assert len(events) == 1
        assert events[0]["event"] == "test.event"
        assert events[0]["detail"]["n"] == 1

    def test_filter_and_limit(self, tmp_path):
        project_path = tmp_path / "p" / "x.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        for i in range(5):
            record_catalog_event(project_path, "a.event", detail={"i": i})
        record_catalog_event(project_path, "b.event")
        assert len(read_catalog_events(project_path, event="a.event")) == 5
        tail = read_catalog_events(project_path, limit=2)
        assert len(tail) == 2
        assert tail[-1]["event"] == "b.event"

    def test_torn_line_skipped_not_fatal(self, tmp_path):
        from paleo_workbench.catalog.telemetry import _events_path

        project_path = tmp_path / "p" / "x.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        record_catalog_event(project_path, "good.event")
        path = _events_path(project_path)
        path.write_text(path.read_text(encoding="utf-8") + '{"torn": ', encoding="utf-8")
        events = read_catalog_events(project_path)
        assert [e["event"] for e in events] == ["good.event"]

    def test_gc_sweep_records_event(self, service, tmp_path):
        (tmp_path / "raw.dat").write_bytes(b"x")
        service.import_raw(tmp_path / "raw.dat", name="raw.dat", type="well_log")
        from paleo_workbench.catalog.gc import sweep_gc

        sweep_gc(service, dry_run=False, explicit=False)
        events = read_catalog_events(service.project_path, event="gc.sweep")
        assert events, "gc sweep must leave durable telemetry"
        assert "removed" in events[-1]["detail"]

    def test_recovery_records_event(self, service):
        statuses = service.recover_working_copies()
        assert isinstance(statuses, list)
        events = read_catalog_events(
            service.project_path, event="working_copy.recovery"
        )
        assert events
        detail = events[-1]["detail"]
        assert "committing_dropped" in detail
        assert "surviving" in detail


class TestBatchPreWarm:
    def test_resolve_asset_models_single_query(self, service, tmp_path, monkeypatch):
        # register 40 assets, lazy-open a fresh service over the same project
        for i in range(40):
            p = tmp_path / f"f{i}.dat"
            p.write_bytes(b"d")
            service.import_raw(p, name=f"f{i}.dat", type="well_log")
        service.close()
        lazy = DataCatalogService.open(service.project_path, lazy=True, sweep_temp=False)
        try:
            assert lazy._lazy_active()
            results = lazy.search_assets(text="")
            assert len(results) >= 40
            # resolve models for ALL result ids — must succeed (batch path)
            ids = [r.id for r in results]
            models = lazy.resolve_asset_models(ids)
            assert len(models) == len(ids)
            assert all(m is not None for m in models)
        finally:
            lazy.close()
