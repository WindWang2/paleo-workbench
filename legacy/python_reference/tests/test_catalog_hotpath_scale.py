"""#1138/#1139: catalog hot paths stay flat as the directory grows.

- #1138: single-output registration / lineage attach must not pay a full
  reconcile (O(N) row build + run-edge cartesian) per call.
- #1139: batch import dedup must stay near-linear: inside batch_save the
  (index ∪ overlay) absence proof replaces the O(N) document scan.

Style follows tests/test_catalog_scale.py: min-of-reps timing with a ratio
ceiling + floor (old quadratic behavior trips the ceiling by construction).
"""
from __future__ import annotations

import time
from pathlib import Path

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.models import DataAsset, DataStage, DataVersion
from paleo_workbench.catalog.service import DataCatalogService

SMALL_N = 400
BIG_N = 1600
CEILING = 2.5
FLOOR_MS = 20.0
REPS = 3


def _open(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


def _seed(service: DataCatalogService, n: int) -> None:
    """N managed RAW versions + one reconcile so the index starts fresh."""
    for i in range(n):
        asset_id = f"a-{i:05d}"
        asset = DataAsset.model_construct(
            id=asset_id, name=f"asset-{asset_id}", type="well_log",
            created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
        )
        service._add_asset(asset)
        service._add_version(DataVersion.model_construct(
            id=f"v-{i:05d}", asset_id=asset_id, version_number=1,
            stage=DataStage.RAW, managed=True,
            path=f"demo.artifacts/raw/{asset_id}/f.bin",
            source_uri=f"file:///data/{asset_id}.las",
            sha256=f"{i:064x}",
            created_at="2026-01-01T00:00:00",
        ))
    service._save()  # one reconcile: index fresh at revision N
    service._ensure_maps()


def _measure(fn, reps: int = REPS) -> float:
    best: float | None = None
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    assert best is not None
    return best


def _lineage_time(n: int, tmp_path: Path) -> float:
    service = _open(tmp_path / str(n))
    try:
        _seed(service, n)
        adapter = CoreCatalogAdapter(service)
        pairs = [(f"v-{i:05d}", f"v-{i + 1:05d}") for i in range(0, 6, 2)]

        def _run() -> None:
            for src, dst in pairs:
                adapter.attach_lineage(source_version_id=src, target_version_id=dst)

        # Fresh edges per rep: re-seed the pairs (cheap, not measured).
        def _rep() -> None:
            for src, dst in pairs:
                target = service.get_version(dst)
                if src in target.parent_version_ids:
                    target.parent_version_ids.remove(src)
            service._save()
            _run()

        _rep()  # warm-up
        return _measure(_rep)
    finally:
        service.close()


def test_attach_lineage_write_flat_in_catalog_size(tmp_path: Path) -> None:
    """#1138: one lineage edge must cost ~constant rows, not a reconcile."""
    t_small = _lineage_time(SMALL_N, tmp_path)
    t_big = _lineage_time(BIG_N, tmp_path)
    assert t_big < CEILING * t_small + FLOOR_MS, (t_small, t_big)


def _batch_import_time(n: int, tmp_path: Path, m: int = 24) -> float:
    """End-to-end batch register_input cost with the batch lifetime held
    outside the measurement (exit sync is O(N) once by design). Each rep
    imports a fresh file slice so every rep exercises the miss path."""
    service = _open(tmp_path / str(n))
    try:
        _seed(service, n)
        adapter = CoreCatalogAdapter(service)
        slices: list[list[Path]] = []
        for r in range(REPS + 1):
            files = []
            for j in range(m):
                p = tmp_path / str(n) / f"new-{r}-{j:03d}.las"
                p.write_text(f"payload-{r}-{j}", encoding="utf-8")
                files.append(p)
            slices.append(files)

        ctx = service.batch_save()
        ctx.__enter__()
        try:
            def _import_slice(files: list[Path]) -> None:
                for p in files:
                    adapter.register_input(
                        name=p.name, path=str(p), checksum=None,
                        kind="well_log", format="las",
                    )

            _import_slice(slices[0])  # warm-up
            pending = list(slices[1:])

            def _rep() -> None:
                _import_slice(pending.pop(0))

            return _measure(_rep)
        finally:
            ctx.__exit__(None, None, None)
    finally:
        service.close()


def test_batch_import_dedup_near_linear(tmp_path: Path) -> None:
    """#1139: M batch imports must not each scan all N versions."""
    t_small = _batch_import_time(SMALL_N, tmp_path)
    t_big = _batch_import_time(BIG_N, tmp_path)
    assert t_big < CEILING * t_small + FLOOR_MS, (t_small, t_big)


def _finder_miss_time(n: int, tmp_path: Path, m: int = 200) -> float:
    """Pure dedup-miss cost inside one batch (no file IO/hashing noise).

    The batch lifetime is held OUTSIDE the measurement: batch exit pays
    one O(N) store sync by design, which would otherwise drown the
    per-miss cost this tripwire guards.
    """
    service = _open(tmp_path / f"finder-{n}")
    try:
        _seed(service, n)
        adapter = CoreCatalogAdapter(service)
        probes = [(f"file:///absent/{j}.las", f"{j:064x}") for j in range(m)]
        ctx = service.batch_save()
        ctx.__enter__()
        try:
            def _run() -> None:
                for uri, sha in probes:
                    assert adapter._find_managed_raw(uri, sha) is None

            _run()  # warm-up
            return _measure(_run)
        finally:
            ctx.__exit__(None, None, None)
    finally:
        service.close()


def test_batch_dedup_miss_cost_flat_in_catalog_size(tmp_path: Path) -> None:
    """#1139 tripwire: miss proofs come from (index ∪ overlay), not scans."""
    t_small = _finder_miss_time(400, tmp_path)
    t_big = _finder_miss_time(3200, tmp_path)
    assert t_big < CEILING * t_small + FLOOR_MS, (t_small, t_big)


def test_batch_dedup_finds_in_batch_duplicates(tmp_path: Path) -> None:
    """Overlay hits: re-importing a file inside the same batch resolves to
    the just-registered version instead of creating a duplicate."""
    service = _open(tmp_path)
    try:
        _seed(service, 50)
        adapter = CoreCatalogAdapter(service)
        p = tmp_path / "dup.las"
        p.write_text("dup-payload", encoding="utf-8")
        with service.batch_save():
            first = adapter.register_input(
                name=p.name, path=str(p), checksum=None,
                kind="well_log", format="las",
            )
            second = adapter.register_input(
                name=p.name, path=str(p), checksum=None,
                kind="well_log", format="las",
            )
        assert first.version_id == second.version_id
    finally:
        service.close()


def test_batch_dedup_never_resolves_trashed(tmp_path: Path) -> None:
    """I2 holds inside batches: a trashed version is not a dedup target."""
    service = _open(tmp_path)
    try:
        _seed(service, 50)
        adapter = CoreCatalogAdapter(service)
        p = tmp_path / "trash.las"
        p.write_text("trash-payload", encoding="utf-8")
        with service.batch_save():
            first = adapter.register_input(
                name=p.name, path=str(p), checksum=None,
                kind="well_log", format="las",
            )
        service.trash_version(first.version_id)
        with service.batch_save():
            second = adapter.register_input(
                name=p.name, path=str(p), checksum=None,
                kind="well_log", format="las",
            )
        assert second.version_id != first.version_id
    finally:
        service.close()
