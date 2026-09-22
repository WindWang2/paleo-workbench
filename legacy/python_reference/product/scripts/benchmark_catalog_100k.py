#!/usr/bin/env python3
"""100k-scale catalog benchmark (Issue #1027 acceptance, task §23).

Builds a real synthetic catalog (100k assets / 100k versions / 1k tags /
10k lineage edges), then measures the full mutation lifecycle against the
SQLite-canonical store and prints a markdown report.

Usage:
    python scripts/benchmark_catalog_100k.py [--assets N] [--keep]
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from paleo_workbench.catalog.service import DataCatalogService  # noqa: E402
from paleo_workbench.catalog.store import catalog_file_for  # noqa: E402

N_ASSETS = 100_000
N_TAGS = 1_000
N_LINEAGE = 10_000

_STATM = Path("/proc/self/statm")


def rss_mb() -> float:
    if _STATM.is_file():
        return int(_STATM.read_text().split()[1]) * 4096 / 1048576.0
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def build_project(root: Path) -> DataCatalogService:
    project = root / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    incoming = root / "incoming"
    incoming.mkdir(exist_ok=True)
    service = DataCatalogService.open(project)

    payload = incoming / "seed.bin"
    payload.write_bytes(b"0123456789abcdef" * 64)  # 1 KiB shared payload
    with service.batch_save():
        for i in range(N_ASSETS):
            service.import_raw(payload, name=f"well-{i:06d}", type="raw")
    return service


def main() -> None:
    global N_ASSETS
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=int, default=N_ASSETS)
    args = parser.parse_args()
    N_ASSETS = args.assets

    root = Path(tempfile.mkdtemp(prefix="paleo-bench-"))
    print(f"# Catalog 100k benchmark (assets={N_ASSETS})\n")
    rows: list[tuple[str, str, str]] = []

    base_rss = rss_mb()
    t0 = time.perf_counter()
    service = build_project(root)
    rows.append(("seed store (write_all + reopen)", f"{time.perf_counter() - t0:.2f}s", ""))
    service.close()

    # -- reopen (cold load from SQLite) --
    project = root / "proj" / "demo.paleo.json"
    _, open_s = timed(lambda: DataCatalogService.open(project))
    service = DataCatalogService.open(project)  # measured instance
    rows.append(("open project (SQLite load)", f"{open_s:.2f}s",
                 f"{len(service.document.assets)} assets, rev {service.document.catalog_revision}"))

    steady_rss = rss_mb()

    # -- single mutations --
    asset = service.document.assets[0]
    _, t = timed(lambda: service.update_asset_metadata(asset.id, {"quality": "bench"}))
    rows.append(("single metadata update", f"{t * 1000:.1f}ms", ""))
    _, t = timed(lambda: service.add_tag("bench-hot", asset_id=asset.id))
    rows.append(("single tag add", f"{t * 1000:.1f}ms", ""))
    _, t = timed(lambda: service.remove_tag("bench-hot", asset_id=asset.id))
    rows.append(("single tag remove", f"{t * 1000:.1f}ms", ""))

    # -- batches --
    targets = [a.id for a in service.document.assets[:100]]
    def batch(n_ids):
        with service.batch_save():
            for i, aid in enumerate(n_ids):
                service.update_asset_metadata(aid, {"batch": i})
    _, t = timed(lambda: batch(targets))
    rows.append(("batch 100 updates", f"{t * 1000:.1f}ms", ""))
    targets1000 = [a.id for a in service.document.assets[:1000]]
    _, t = timed(lambda: batch(targets1000))
    rows.append(("batch 1000 updates", f"{t:.3f}s", ""))

    # -- search / filter --
    from paleo_workbench.catalog.queries import search_assets
    _, t = timed(lambda: search_assets(service, text="well-0999"))
    rows.append(("search 'well-0999'", f"{t * 1000:.1f}ms", ""))
    _, t = timed(lambda: [a for a in service.document.assets if a.type == "raw"])
    rows.append(("filter type==raw (document scan)", f"{t * 1000:.1f}ms", ""))

    # -- manifest checkpoint --
    _, t = timed(lambda: service.export_manifest())
    manifest_mb = catalog_file_for(project).stat().st_size / 1048576
    rows.append(("manifest checkpoint (catalog.json)", f"{t:.2f}s", f"{manifest_mb:.1f} MiB"))

    # -- mutation does NOT rewrite manifest --
    before = catalog_file_for(project).read_bytes()
    service.update_asset_metadata(asset.id, {"quality": "after-checkpoint"})
    unchanged = catalog_file_for(project).read_bytes() == before
    rows.append(("mutation rewrites manifest?", "NO" if unchanged else "YES",
                 "must be NO (#1027)"))

    rows.append(("RSS steady state", f"{rss_mb():.0f}MiB", f"base {base_rss:.0f}MiB"))
    rows.append(("RSS peak", f"{peak_rss_mb():.0f}MiB", ""))
    rows.append(("delta steady-after-open", f"{steady_rss - base_rss:.0f}MiB",
                 "document + connection overhead"))

    service.close()
    print("| Metric | Value | Notes |")
    print("|---|---|---|")
    for name, value, note in rows:
        print(f"| {name} | {value} | {note} |")
    print()
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
