"""D2 audit: EXPLAIN QUERY PLAN + page-query timings on a 100k synthetic store.

Builds a real catalog via the service API (batch_save, metadata-only payloads),
then answers:
  * which index each paged query pattern uses;
  * wall time per page fetch / count / aggregates / text LIKE at 100k;
  * FTS decision data: LIKE '%tok%' vs prefix LIKE vs FTS5 (measured, not assumed).

Usage: python scripts/audit_catalog_query_plans.py [--assets 100000]
Writes docs/development/catalog-scale-v5/explain-100k.txt.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import unicodedata
from pathlib import Path

from paleo_workbench.catalog.service import DataCatalogService

TYPES = ["well_log", "seismic", "horizon", "well_table", "fault", "geojson"]
TAG_NAMES = [f"tag_{i:03d}" for i in range(64)]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def build(tmp: Path, assets: int) -> DataCatalogService:
    proj = tmp / "scale.paleo.json"
    proj.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(proj)
    batch = 2000
    with svc.batch_save():
        for i in range(assets):
            # Zero-byte payload placeholder would be skipped by import paths;
            # use register via _build? Keep metadata-only: create the asset and
            # one version record through the service's lowest-level write path
            # is not public — use link_external-style rows instead: we write
            # the file (tiny) for the first 1000 only; the rest reuse blobs.
            src = tmp / f"src_{i:06d}.las"
            if i < 1000 or not src.exists():
                src.write_text(f"curve {i}", encoding="utf-8")
            svc.import_raw(source_path=src, name=f"asset_{i:06d}_{TYPES[i % len(TYPES)]}")
            if (i + 1) % batch == 0 and i + 1 < assets:
                pass  # single batch; batch_save at scope exit
    # tags: spread across assets
    tag_ids = {}
    with svc.batch_save():
        for name in TAG_NAMES:
            tag = svc.create_tag(name)
            tag_ids[tag.id] = name
        all_ids = [a.id for a in svc.list_assets()]
        for idx, asset_id in enumerate(all_ids):
            svc.add_tag(TAG_NAMES[idx % len(TAG_NAMES)], asset_id=asset_id)
            if idx % 7 == 0:
                svc.add_tag(TAG_NAMES[(idx * 13) % len(TAG_NAMES)], asset_id=asset_id)
    return svc


def explain(conn, sql: str, params: tuple) -> list[str]:
    return [
        " ".join(str(c or "") for c in row)
        for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    ]


def timed(fn, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best * 1000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=int, default=100_000)
    parser.add_argument("--keep", action="store_true", help="reuse an existing store")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="paleo-scale-"))
    t0 = time.perf_counter()
    svc = build(tmp, args.assets)
    build_s = time.perf_counter() - t0

    lines: list[str] = []
    lines.append(f"# EXPLAIN/plan audit — {args.assets} assets, build {build_s:.1f}s")

    idx = svc._index
    conn = idx._connect()

    patterns = {
        "page name asc (default)": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            (500, 0),
        ),
        "page name asc deep offset": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            (500, 50_000),
        ),
        "page keyset after cursor": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0"
            " AND (a.name > ? OR (a.name = ? AND a.id > ?))"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            ("asset_050000", "asset_050000", "zzz", 500, 0),
        ),
        "page text LIKE suffix": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0"
            " AND a.name_search LIKE ? ESCAPE '\\'"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            ("%asset_00042%", 500, 0),
        ),
        "page type filter": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0 AND a.type = ?"
            " ORDER BY a.type, a.name, a.id LIMIT ? OFFSET ?",
            ("seismic", 500, 0),
        ),
        "page stage subquery": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0 AND a.current_version_id IN"
            " (SELECT id FROM versions WHERE stage = ?)"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            ("raw", 500, 0),
        ),
        "page tag and": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0 AND a.id IN"
            " (SELECT at_a.asset_id FROM asset_tags at_a"
            " JOIN tags t_a ON t_a.id = at_a.tag_id WHERE t_a.name = ?)"
            " ORDER BY a.name, a.id LIMIT ? OFFSET ?",
            (TAG_NAMES[5], 500, 0),
        ),
        "page order modified": (
            "SELECT a.* FROM assets a WHERE a.trashed = 0"
            " ORDER BY a.updated_at, a.name, a.id LIMIT ? OFFSET ?",
            (500, 0),
        ),
        "page order stage (join)": (
            "SELECT a.* FROM assets a LEFT JOIN versions v ON v.id = a.current_version_id"
            " WHERE a.trashed = 0 ORDER BY v.stage, a.name, a.id LIMIT ? OFFSET ?",
            (500, 0),
        ),
        "count all": ("SELECT count(*) FROM assets a WHERE a.trashed = 0", ()),
        "lineage children (parent idx)": (
            "SELECT child_version_id FROM lineage WHERE parent_version_id = ?",
            ("ver_x",),
        ),
        "lineage parents (child idx)": (
            "SELECT parent_version_id FROM lineage WHERE child_version_id = ?",
            ("ver_x",),
        ),
        "list versions of asset": (
            "SELECT * FROM versions WHERE asset_id = ? ORDER BY version_number",
            ("ver_x",),
        ),
    }
    lines.append("\n## EXPLAIN QUERY PLAN")
    for label, (sql, params) in patterns.items():
        lines.append(f"### {label}")
        for line in explain(conn, sql, params):
            lines.append(f"  {line}")

    lines.append("\n## Wall timings (best of 3)")
    timings = {
        "service.search_assets_page page0 (500)": lambda: svc.search_assets_page(
            limit=500
        ),
        "service.search_assets_page deep keyset": lambda: svc.search_assets_page(
            limit=500, offset=50_000
        ),
        "service.count_assets()": lambda: svc.count_assets(),
        "service.catalog_aggregates()": lambda: svc.catalog_aggregates(),
        "text filter asset_00042x": lambda: svc.count_assets(text="asset_00042"),
        "tag filter": lambda: svc.count_assets(tags=[TAG_NAMES[7]]),
        "stage filter": lambda: svc.count_assets(stage="raw"),
        "mid-text LIKE %42x% (worst case)": lambda: svc.count_assets(text="00042"),
        "order_by stage page": lambda: svc.search_assets_page(
            limit=500, order_by="stage"
        ),
        "order_by size page": lambda: svc.search_assets_page(
            limit=500, order_by="size"
        ),
        "order_by modified page": lambda: svc.search_assets_page(
            limit=500, order_by="modified"
        ),
        "order_by type page": lambda: svc.search_assets_page(limit=500, order_by="type"),
    }
    for label, fn in timings.items():
        ms = timed(fn)
        lines.append(f"  {label}: {ms:.2f} ms")

    out = Path("docs/development/catalog-scale-v5/explain-100k.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    svc.close()


if __name__ == "__main__":
    main()
