"""Tag-governance scale behavior (D7) — journal rollback + O(selection) bulk.

Pins:

* ``bulk_add_tag`` / ``bulk_remove_tag`` cost O(selection), not
  O(total associations) — a 4x catalog growth must not inflate a
  fixed-size bulk tag operation beyond the generous linear ceiling;
* ``add_tags`` journal rollback restores the EXACT pre-call state on a
  failed canonical save (the invariant the old full-map deep copy
  guaranteed, now paid as O(names) journal bookkeeping instead).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataStage,
    DataVersion,
)
from paleo_workbench.catalog.service import DataCatalogService

BASE_N = int(os.environ.get("CATALOG_SCALE_N", "64"))
LEVELS = [BASE_N, BASE_N * 2, BASE_N * 4]
REPS = 3
LINEAR_CEILING = 5.0
FLOOR_MS = 20.0
SELECTION = 10


def _measure(fn, reps: int = REPS) -> float:
    best: float | None = None
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    assert best is not None
    return best


def _service_with(n: int, tmp_path: Path) -> DataCatalogService:
    """A service with *n* assets/versions, direct document construction."""
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    document = CatalogDocument()
    for i in range(n):
        asset = DataAsset(name=f"asset_{i:06d}", type="well_log")
        version = DataVersion(
            asset_id=asset.id,
            version_number=1,
            stage=DataStage.RAW,
            path=f"raw/{asset.id}/v1/f.las",
            size_bytes=100,
        )
        asset.current_version_id = version.id
        document.assets.append(asset)
        document.versions.append(version)
    svc.document = document
    svc.rebuild_index()
    return svc


@pytest.mark.parametrize("level", LEVELS)
def test_bulk_tag_budget(level: int, tmp_path: Path):
    """Selection fixed, catalog grows 4x: bulk ops stay bounded. The ratio
    gate below pins the scaling; this one pins correctness at every level."""
    service = _service_with(level, tmp_path)
    try:
        ids = [asset.id for asset in service.list_assets()[:SELECTION]]
        tag = service.bulk_add_tag("scale_probe", asset_ids=ids)
        assert tag is not None
        assert len(service.find_assets_by_tag("scale_probe")) == SELECTION
        service.bulk_remove_tag("scale_probe", asset_ids=ids)
        assert service.find_assets_by_tag("scale_probe") == []
    finally:
        service.close()


def test_bulk_tag_ratio_across_levels(tmp_path: Path):
    """4x catalog growth with a FIXED selection: quadratic association-map
    costs would show up as ~16x; linear-in-selection stays ~flat."""
    baselines: list[float] = []
    for level in (LEVELS[0], LEVELS[-1]):
        service = _service_with(level, tmp_path)
        try:
            ids = [asset.id for asset in service.list_assets()[:SELECTION]]
            elapsed = _measure(
                lambda: service.bulk_add_tag("ratio_probe", asset_ids=ids)
            )
            elapsed += _measure(
                lambda: service.bulk_remove_tag("ratio_probe", asset_ids=ids)
            )
            baselines.append(elapsed)
        finally:
            service.close()
    small, big = baselines
    if big < FLOOR_MS:
        pytest.skip("absolute times below the noise floor")
    assert big <= small * LINEAR_CEILING + FLOOR_MS, baselines


def test_add_tags_journal_rollback_restores_exact_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = _service_with(6, tmp_path)
    try:
        service.add_tag("keep", asset_id=service.list_assets()[0].id)
        before = (
            list(service.document.tags),
            {k: list(v) for k, v in service.document.asset_tags.items()},
            {k: list(v) for k, v in service.document.version_tags.items()},
        )
        real_save = type(service)._flush_canonical_locked

        def boom(_service, _dirty, **_kw):
            raise OSError("disk full")

        monkeypatch.setattr(type(service), "_flush_canonical_locked", boom)
        with pytest.raises(OSError):
            service.add_tags(
                ["fresh_a", "fresh_b"], asset_id=service.list_assets()[1].id
            )
        monkeypatch.setattr(type(service), "_flush_canonical_locked", real_save)

        assert list(service.document.tags) == before[0]
        assert service.document.asset_tags == before[1]
        assert service.document.version_tags == before[2]
        # and the happy path still works afterwards
        tags = service.add_tags(
            ["fresh_a", "keep"], asset_id=service.list_assets()[1].id
        )
        assert len(tags) == 2
        assert service.find_assets_by_tag("fresh_a") == [
            service.list_assets()[1].id
        ]
    finally:
        service.close()
