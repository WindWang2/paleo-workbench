#!/usr/bin/env python3
"""100G seismic workflow acceptance benchmark (#1086).

Runs the REAL production chain over a synthetic SEG-Y (default: quick2g,
1024x1024x512 ≈ 2.4 GB) and reports per-stage wall times:

    transcode → first view → slice drag (lod0/1/2) → arbitrary line
    → LOD build → ROI attribute → subset full-attribute + extrapolation
    → subset tiled ONNX inference + extrapolation
    → catalog lineage registration → project reopen

Every number is [measured] on this machine; the report marks which rows are
extrapolations to the full100g (5000x5000x1000 ≈ 106 GB) shape. No stage is
skipped or mocked: production transcoder, production readers, production
attribute kernel, production tiled inference.

    python benchmarks/acceptance_100g.py --segy /path/quick2g.segy --work /tmp/acc
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RESULT: dict[str, dict] = {}


def stage(name: str):
    def deco(fn):
        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            out = fn(*a, **kw)
            dt = time.perf_counter() - t0
            RESULT[name] = {"seconds": round(dt, 3), **(out if isinstance(out, dict) else {})}
            print(f"[{name}] {dt:.2f}s {RESULT[name] if not isinstance(out, dict) else ''}", flush=True)
            return out

        return wrapper

    return deco


def fmt_gb(b: float) -> float:
    return round(b / 1024**3, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segy", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--attr-inlines", type=int, default=256,
                    help="inline subset for the full-attribute stage")
    ap.add_argument("--infer-inlines", type=int, default=64,
                    help="inline subset for the tiled-inference stage")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    segy = Path(args.segy)
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    store = work / "store"

    import numpy as np

    from geoviz_seismic import open_volume
    from paleo_workbench.seismic_attributes import VolumeAttributeJob, roi_attribute
    from paleo_workbench.seismic_transcode import (
        TranscodeParams,
        transcode_segy_to_zarr,
        default_workers,
    )

    # ------------------------------------------------------------ transcode
    @stage("transcode")
    def do_transcode():
        res = transcode_segy_to_zarr(segy, store, workers=default_workers())
        return {
            "shape": list(res.shape),
            "shards": res.stats.shards_total,
            "throughput_mb_s": round(res.stats.throughput_mb_s, 1),
        }

    do_transcode()

    # -------------------------------------------------------- first view
    reader = open_volume(store)
    g = reader.geometry

    @stage("first_view_inline")
    def first_view():
        arr = reader.read_inline(g.iline_start + 5, lod=0)
        return {"shape": list(arr.shape)}

    first_view()

    # -------------------------------------------------------- slice drag
    def drag(lod: int, n: int = 20) -> float:
        t0 = time.perf_counter()
        base = g.iline_start + 100
        for i in range(n):
            reader.read_inline(base + i * 7, lod=lod)
        return (time.perf_counter() - t0) / n

    RESULT["slice_drag"] = {
        "lod0_ms": round(drag(0) * 1000, 1),
        "lod1_ms": round(drag(1) * 1000, 1),
        "lod2_ms": round(drag(2) * 1000, 1),
    }
    print(f"[slice_drag] {RESULT['slice_drag']}", flush=True)

    # ---------------------------------------------------- arbitrary line
    @stage("arbitrary_line_100pts")
    def arbitrary():
        import numpy as np

        rng = np.random.default_rng(4)
        il_lo, il_hi = g.iline_start + 10, g.iline_start + 300
        xl_lo, xl_hi = g.xline_start + 10, g.xline_start + 300
        pts = list(
            zip(
                rng.uniform(il_lo, il_hi, 100).round().astype(int),
                rng.uniform(xl_lo, xl_hi, 100).round().astype(int),
            )
        )
        out = reader.read_arbitrary_line(pts, lod=0, interpolate=True)
        return {"out_shape": list(out.shape)}

    arbitrary()

    # -------------------------------------------------------- LOD build
    for lod in (1, 2):
        @stage(f"lod_build_l{lod}")
        def build_lod(lod=lod):
            secs = reader.build_lod(lod)
            return {"seconds": round(secs, 3)}

        build_lod()

    # ----------------------------------------------------- ROI attribute
    n_il, n_xl, n_t = reader.shape

    @stage("roi_attribute_64il_band")
    def roi():
        mid = n_il // 2
        out = roi_attribute(reader, (mid, mid + 64, 0, n_xl, 0, n_t), "c3")
        return {"out_shape": list(out.shape), "voxels": int(out.size)}

    roi()

    # --------------------------------------------- full attribute subset
    subset_store = work / "attr_subset"
    sub_reader = _SubsetReader(reader, args.attr_inlines)
    job = VolumeAttributeJob(sub_reader, subset_store, "c3", band_inlines=64)
    from paleo_workbench.runtime import TaskContext

    @stage("full_attribute_subset")
    def attr_subset():
        stats = job.run(TaskContext(task_id="acc"))
        return {**stats, "inlines": args.attr_inlines}

    attr_subset()
    sub_secs = RESULT["full_attribute_subset"]["seconds"]
    per_il = sub_secs / args.attr_inlines
    RESULT["full_attribute_extrapolated"] = {
        "note": f"measured {per_il * 1000:.1f} ms/inline x N inlines (linear in bands; halo fraction shrinks on the real volume)",
        "quick2g_full_s": round(per_il * n_il, 1),
        "full100g_s_extrapolated": round(per_il * 5000, 1),
    }

    # ---------------------------------------------- tiled ONNX subset
    model = _write_sign_model(work / "sign.onnx")
    from paleo_workbench.prediction.tiled_onnx import run_tiled_inference

    class _SubsetReaderWrap(_SubsetReader):
        pass

    sub2 = _SubsetReader(reader, args.infer_inlines)
    sub2_store = work / "infer_subset_input"
    _materialize_subset(sub2, sub2_store)

    @stage("tiled_onnx_subset")
    def infer_subset():
        r2 = open_volume(sub2_store)
        stats = run_tiled_inference(
            r2, model, classes=2, work_root=work / "infer_out",
            overlap=4, batch=4, prefer_gpu=False,
        )
        return {
            "tiles": stats["tiles_done"],
            "inlines": args.infer_inlines,
            "elapsed_s": round(stats["elapsed_s"], 3),
            "mode": stats["mode"],
        }

    infer_subset()
    inf = RESULT["tiled_onnx_subset"]
    per_tile = inf["elapsed_s"] / max(inf["tiles"], 1)
    # full100g tile count at production 64x128x128 with overlap 8
    tiles_100g = (
        (5000 // (64 - 8) + 1) * (5000 // (128 - 8) + 1) * (1000 // (128 - 8) + 1)
    )
    RESULT["tiled_onnx_extrapolated"] = {
        "note": "measured ms/tile x tile count (CPU EP, toy model; real models are heavier)",
        "ms_per_tile": round(per_tile * 1000, 2),
        "full100g_s_extrapolated": round(per_tile * tiles_100g, 1),
    }

    # ------------------------------------------------ catalog lineage
    import tempfile

    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.seismic_lifecycle import start_attribute_job, start_transcode  # noqa: F401

    with tempfile.TemporaryDirectory(dir=work) as td:
        proj = Path(td) / "p" / "demo.paleo.json"
        proj.parent.mkdir(parents=True)
        proj.write_text("{}", encoding="utf-8")

        @stage("catalog_lineage")
        def lineage():
            from paleo_workbench.runtime import TaskScheduler

            svc = DataCatalogService.open(proj)
            raw = svc.link_external(segy, name="acc", type="seismic")
            run = svc.register_run("segy-to-zarr", input_version_ids=[raw.id])
            # register the ALREADY transcoded store (no re-transcode for the
            # benchmark; the transcode stage above measured the real one)
            derived = svc.register_derived_store(
                name="acc store", store_path=store, run_id=run.id,
                parent_version_ids=[raw.id], type="seismic", format="zarr-v3",
            )
            svc.update_run_status(run.id, "complete")
            from paleo_workbench.catalog.lineage_graph import build_lineage_chain

            chain = build_lineage_chain(svc, derived.id, direction="ancestors")
            # project reopen
            t0 = time.perf_counter()
            reopened = DataCatalogService.open(proj)
            reopen_s = time.perf_counter() - t0
            reopened.close()
            svc.close()
            return {
                "chain_nodes": chain.node_count,
                "reopen_seconds": round(reopen_s, 3),
            }

        lineage()

    RESULT["environment"] = {
        "segy_gb": fmt_gb(segy.stat().st_size),
        "store_gb": fmt_gb(sum(f.stat().st_size for f in store.rglob("*") if f.is_file())),
    }
    print(json.dumps(RESULT, indent=2))
    out_json = work / "acceptance_result.json"
    out_json.write_text(json.dumps(RESULT, indent=2))
    return 0


class _SubsetReader:
    """Read-only view over the first N inlines (for subset stages)."""

    def __init__(self, reader, n_il: int):
        self._r = reader
        self.shape = (min(n_il, reader.shape[0]), reader.shape[1], reader.shape[2])
        self.geometry = reader.geometry

    def read_voxel_window(self, il0, il1, xl0, xl1, t0, t1, *, lod=0):
        return self._r.read_voxel_window(il0, il1, xl0, xl1, t0, t1, lod=lod)


def _materialize_subset(sub, dst: Path) -> None:
    import numpy as np
    import zarr
    from zarr.codecs import BloscCodec

    sub_n = sub.shape
    arr = zarr.create_array(
        str(dst), shape=sub_n, dtype="float32",
        chunks=(64, 128, 128), shards=(128, 512, 512),
        compressors=[BloscCodec(cname="zstd", clevel=3, shuffle="shuffle")],
    )
    step = 64
    for i0 in range(0, sub_n[0], step):
        i1 = min(i0 + step, sub_n[0])
        arr[i0:i1, :, :] = sub.read_voxel_window(i0, i1, 0, sub_n[1], 0, sub_n[2])


def _write_sign_model(path: Path) -> Path:
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, ["n", 1, "d", "h", "w"])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, ["n", 2, "d", "h", "w"])
    neg = helper.make_node("Neg", ["x"], ["xn"])
    out = helper.make_node("Concat", ["x", "xn"], ["y"], axis=1)
    graph = helper.make_graph([neg, out], "sign", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    import onnx

    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


if __name__ == "__main__":
    raise SystemExit(main())
