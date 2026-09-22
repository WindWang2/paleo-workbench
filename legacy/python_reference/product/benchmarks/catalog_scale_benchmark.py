#!/usr/bin/env python3
"""Catalog scale benchmark: single-operation budgets at 10k/50k/100k assets.

Issue #1027 acceptance: ordinary metadata/tag mutations at 100k assets must
be interactive (<20 ms target), with no O(N) JSON rewrite per mutation.

Every operation goes through the production DataCatalogService API (no test
doubles). Run:

    python benchmarks/catalog_scale_benchmark.py [--sizes 10000,50000,100000]

Results are printed as a markdown table; tag each number [measured] when
copied into docs/development/production-convergence/04-benchmarks.md.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paleo_workbench.catalog.models import DataStage  # noqa: E402
from paleo_workbench.catalog.service import DataCatalogService  # noqa: E402


def seed(tmp: Path, n: int) -> DataCatalogService:
    project = tmp / f"proj{n}" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    incoming = tmp / "incoming"
    incoming.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    service = DataCatalogService.open(project)
    with service.batch_save():
        for i in range(n):
            src = incoming / f"w{i}.las"
            src.write_bytes(b"x" * 16)
            service.import_raw(src, name=f"well-{i:06d}", type="raw")
    seed_s = time.perf_counter() - t0
    print(f"  seeded {n} assets in {seed_s:.1f}s", flush=True)
    return service


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t0


def bench_ops(service: DataCatalogService) -> dict[str, float]:
    doc = service.document
    asset = doc.assets[len(doc.assets) // 2]
    other = doc.assets[10]
    tag_name = f"batch-{asset.id[-6:]}"
    results: dict[str, float] = {}

    _, s = timed(lambda: service.update_asset_metadata(asset.id, {"quality": "qc-1"}))
    results["metadata_update_ms"] = s
    _, s = timed(lambda: service.add_tag(tag_name, asset_id=asset.id))
    results["add_tag_new_ms"] = s
    _, s = timed(lambda: service.add_tag(tag_name, asset_id=other.id))
    results["add_tag_second_asset_ms"] = s
    _, s = timed(lambda: service.remove_tag(tag_name, asset_id=other.id))
    results["remove_tag_ms"] = s
    _, s = timed(lambda: service.rename_tag(tag_name, f"r-{asset.id[-6:]}"))
    results["rename_tag_ms"] = s
    tag_name = f"r-{asset.id[-6:]}"

    src = service.project_path.parent / "bench_version.bin"
    src.write_bytes(b"v" * 32)
    v1, s = timed(lambda: service.register_version(asset.id, src, DataStage.RAW))
    results["register_version_ms"] = s
    src2 = service.project_path.parent / "bench_version2.bin"
    src2.write_bytes(b"w" * 32)
    _, s = timed(lambda: service.register_version(asset.id, src2, DataStage.RAW))
    results["register_version_2nd_ms"] = s
    _, s = timed(lambda: service.trash_version(v1.id, reason="bench"))
    results["trash_version_ms"] = s
    _, s = timed(lambda: service.restore_version(v1.id))
    results["restore_version_ms"] = s
    _, s = timed(lambda: service.trash_asset(other.id, reason="bench"))
    results["trash_asset_ms"] = s
    _, s = timed(lambda: service.restore_asset(other.id))
    results["restore_asset_ms"] = s

    # Path lookup through the #1043 partial index (production query path).
    ext = next((v for v in service.list_versions(asset.id) if not v.managed), None)
    if ext is not None:
        _, s = timed(lambda: service._index.find_external_by_path(ext.path))
        results["path_lookup_ms"] = s
    _, s = timed(lambda: service.search_assets(text="well-050"))
    results["search_hit_ms"] = s
    _, s = timed(lambda: service.search_assets(text="zzz-no-such"))
    results["search_miss_ms"] = s
    _, s = timed(lambda: service.search_assets(tag=tag_name))
    results["filter_by_tag_ms"] = s
    _, s = timed(lambda: service.search_assets(type="raw"))
    results["filter_by_type_ms"] = s
    return {k: v * 1000.0 for k, v in results.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10000,50000,100000")
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    all_results: dict[int, dict[str, float]] = {}
    with tempfile.TemporaryDirectory(prefix="paleo-cat-bench-", dir="/tmp") as td:
        tmp = Path(td)
        for n in sizes:
            service = seed(tmp, n)
            # warm one mutation so lazy index paths are not charged to op #1
            service.update_asset_metadata(service.document.assets[0].id, {"warm": True})
            all_results[n] = bench_ops(service)
            service.close()

    keys = sorted({k for r in all_results.values() for k in r})
    print("\n| operation | " + " | ".join(f"{n:,} ms" for n in sizes) + " |")
    print("|---" * (len(sizes) + 1) + "|")
    for k in keys:
        print(f"| {k} | " + " | ".join(f"{all_results[n].get(k, float('nan')):.1f}" for n in sizes) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
