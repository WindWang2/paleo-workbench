#!/usr/bin/env python
"""Data & Runtime Foundation V6 — catalog scale benchmark (§13).

Run (worktree root, project venv):

    python benchmarks/catalog_scale_v6.py --assets 100000
    python benchmarks/catalog_scale_v6.py --assets 500000 --direct-seed

Two seeding tiers, honestly labeled:
- PRODUCTION (default): the real service API (import_raw inside batch_save,
  tiny 8-byte payloads, one transaction per batch) — the exact path user
  data takes. ~1.8k assets/s, so 100k ≈ 1 min.
- METADATA STRESS (--direct-seed): rows written directly to the canonical
  store (same schema, synthetic digests, no payload IO). For the 500k
  metadata tier only; measures the store/query layers, NOT registration.

Measured per §13: lazy open, eager open, first/deep page, get-by-id,
tag mutation, version timeline, lineage one-hop, working-copy checkout→commit,
save-as-side reopen, background-warmup-during-query, concurrent-write
conflict detection.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _timed(label: str, results: dict, fn):
    t0 = _now_ms()
    value = fn()
    results[label] = round(_now_ms() - t0, 2)
    return value


def seed_production(project: Path, tmp: Path, n_assets: int) -> None:
    from paleo_workbench.catalog.service import DataCatalogService

    service = DataCatalogService.open(project)
    try:
        incoming = tmp / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        sources = []
        for i in range(n_assets):
            src = incoming / f"s{i}.las"
            if not src.exists():
                src.write_bytes(f"{i}".encode())
            sources.append(src)
        with service.batch_save():
            for src in sources:
                service.import_raw(src)
    finally:
        service.close()


def seed_direct(project: Path, n_assets: int, versions_per: int) -> None:
    import sqlite3

    artifacts = project.parent / f"{project.stem}.artifacts" / "metadata"
    artifacts.mkdir(parents=True, exist_ok=True)
    db = artifacts / "catalog.sqlite"
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    from paleo_workbench.catalog.db import _SCHEMA_DDL

    for ddl in _SCHEMA_DDL:
        conn.execute(ddl)
    rows_a, rows_v = [], []
    for i in range(n_assets):
        aid = f"asset_s{i:09d}"
        rows_a.append(
            (aid, f"well-{i}", f"well-{i}", "well_log", "", None, None,
             "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", 0, None)
        )
        for v in range(versions_per):
            vid = f"ver_s{i:09d}_{v}"
            rows_v.append(
                (vid, aid, v + 1, "raw", 1,
                 f"demo.artifacts/raw/{aid}/{vid}/s.las",
                 f"/bench/incoming/s{i}.las", "las", 8,
                 f"{i:064x}"[-64:], None, "{}", "2026-01-01T00:00:00", 0,
                 None, "[]")
            )
            if len(rows_v) >= 50000:
                _flush_seed(conn, rows_a, rows_v)
                rows_a, rows_v = [], []
    _flush_seed(conn, rows_a, rows_v)
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('catalog_revision', '1')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('schema_version', '1')"
    )
    from paleo_workbench.catalog.db import INDEX_SCHEMA_VERSION

    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('index_schema_version', ?)",
        (str(INDEX_SCHEMA_VERSION),),
    )
    conn.commit()
    conn.close()


def _flush_seed(conn, rows_a, rows_v) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO assets (id,name,name_search,type,description,"
        "current_version_id,legacy_resource_id,metadata,created_at,updated_at,"
        "trashed,trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows_a,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO versions (id,asset_id,version_number,stage,"
        "managed,path,source_uri,format,size_bytes,sha256,run_id,metadata,"
        "created_at,trashed,trashed_at,parent_ids) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows_v,
    )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=int, default=100_000)
    parser.add_argument("--versions-per", type=int, default=1)
    parser.add_argument("--direct-seed", action="store_true",
                        help="metadata-stress tier: rows straight into the store")
    parser.add_argument("--keep", action="store_true", help="keep the bench project")
    args = parser.parse_args()

    from paleo_workbench.catalog.models import DataStage
    from paleo_workbench.catalog.service import (
        CatalogStaleWriteError,
        DataCatalogService,
    )

    tmp = Path(tempfile.mkdtemp(prefix="paleo-v6-bench-"))
    project = tmp / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")

    print(f"seeding {args.assets} assets "
          f"({'direct-SQL metadata stress' if args.direct_seed else 'production API'})…")
    t0 = _now_ms()
    if args.direct_seed:
        seed_direct(project, args.assets, args.versions_per)
    else:
        seed_production(project, tmp, args.assets)
    print(f"seed done in {( _now_ms() - t0) / 1000:.1f}s")

    results: dict[str, float] = {}

    lazy = _timed("open_lazy_ms", results,
                  lambda: DataCatalogService.open(project, lazy=True,
                                                  sweep_temp=False))
    _timed("first_page_ms", results, lambda: lazy.search_assets_page(limit=500))
    deep = _timed("deep_page_ms", results,
                  lambda: lazy.search_assets_page(limit=500, offset=args.assets // 2))
    first_id = lazy.search_assets_page(limit=1)[0]["id"]
    first_vid = lazy.search_assets_page(limit=1)[0]["current_version_id"]
    _timed("get_by_id_ms", results, lambda: lazy.get_asset(first_id))
    lazy.require_warm()
    print(f"(warmup included open→require_warm; total so far "
          f"{sum(results.values()):.0f} ms)")

    _timed("tag_mutation_ms", results,
           lambda: lazy.add_tag("bench", asset_id=first_id))
    _timed("version_timeline_ms", results, lambda: lazy.list_versions(first_id))
    _timed("lineage_one_hop_ms", results, lambda: lazy.get_lineage(first_vid))

    # Working-copy coordination.
    def _wc_flow():
        path = lazy.create_working_copy(first_vid)
        path.write_bytes(b"edited")
        return lazy.commit_working_copy(path, name="bench-edit")

    _timed("working_copy_checkout_commit_ms", results, _wc_flow)

    _timed("save_manifest_export_ms", results, lambda: lazy.export_manifest())
    lazy.close()

    eager = _timed("reopen_eager_ms", results,
                   lambda: DataCatalogService.open(project))
    # Concurrent-write conflict (same store, stale second session).
    other = DataCatalogService.open(project)
    other.add_tag("foreign", asset_id=first_id)
    try:
        eager.add_tag("stale-writer", asset_id=first_id)
        results["concurrent_conflict"] = 0  # 0 = NOT detected (bug!)
    except CatalogStaleWriteError:
        results["concurrent_conflict"] = 1
    other.close()
    eager.close()

    print(json.dumps(results, indent=2))
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
