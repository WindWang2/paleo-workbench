"""Tiled ONNX seismic inference (#1085).

Production provider behind the existing ``ModelProvider`` / ``DataRun``
contract: a registered ONNX model runs over a seismic volume in
``64 × 128 × 128`` tiles with ``receptive_field`` overlap, fusing by
CENTER-CROP — every voxel gets exactly ONE authoritative prediction (no
border blending/averaging), so tiles never mix classes at seams.

Outputs (dual persist):
- ``classmap`` — uint8 argmax zarr store (``<work>.classmap``)
- ``probmap``  — float16 max-probability zarr store (``<work>.probmap``)

Robustness:
- **resume**: per-tile ``.done`` markers (fsynced after the tile lands);
  a cancelled/crashed run re-scans and skips completed tiles;
- **GPU OOM**: batch size halves with exponential backoff on CUDA OOM;
- **CPU fallback**: no CUDA provider → CPU execution, and the result
  reports ``"mode": "cpu"`` — never claims GPU;
- inference runs through onnxruntime, which releases the GIL during
  ``session.run`` (scheduler-friendly).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from paleo_workbench.prediction.providers import ModelProvider

logger = logging.getLogger(__name__)

PROVIDER_TILED_ONNX = "tiled_onnx"
TILE = (64, 128, 128)  # (inline, xline, time)
DEFAULT_RECEPTIVE_FIELD = 8


class TiledInferenceError(RuntimeError):
    """Honest failure (bad model I/O contract, unusable input, OOM at batch 1)."""


def tile_starts(n: int, tile: int, overlap: int) -> list[int]:
    """Tile start positions covering [0, n) with stride = tile - overlap."""
    if tile <= overlap:
        raise TiledInferenceError(f"tile {tile} must exceed overlap {overlap}")
    stride = tile - overlap
    if n <= tile:
        return [0]
    return list(range(0, n - overlap, stride))


def authoritative_range(i: int, starts: list[int], stride: int, overlap: int, n: int):
    """Center-crop fusion: the ONE region tile *i* owns. First tile owns
    from 0, last tile owns to n; interiors are [start+overlap//2,
    next_start+overlap//2)."""
    lo = 0 if i == 0 else starts[i] + overlap // 2
    hi = n if i == len(starts) - 1 else starts[i + 1] + overlap // 2
    return lo, hi


def _make_session(model_path: str | Path, prefer_gpu: bool):
    import onnxruntime as ort

    providers = []
    if prefer_gpu:
        providers.append("CUDAExecutionProvider")
    providers.append("CPUExecutionProvider")
    try:
        sess = ort.InferenceSession(str(model_path), providers=providers)
    except Exception:
        if not prefer_gpu:
            raise
        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        return sess, "cpu"
    active = sess.get_providers()
    mode = "cuda" if any("CUDA" in p for p in active) else "cpu"
    return sess, mode


def _softmax(x: np.ndarray) -> np.ndarray:
    m = x.max(axis=1, keepdims=True)
    e = np.exp(x - m)
    return e / e.sum(axis=1, keepdims=True)


def run_tiled_inference(
    reader: Any,
    model_path: str | Path,
    *,
    classes: int,
    work_root: str | Path,
    overlap: int = DEFAULT_RECEPTIVE_FIELD,
    batch: int = 1,
    prefer_gpu: bool = True,
    tile: tuple[int, int, int] = TILE,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Stream tiles through the ONNX model; returns stats + store paths.

    ``tile`` overridable for tests/small volumes; production default is
    :data:`TILE` (64 × 128 × 128).
    """
    import zarr
    from zarr.codecs import BloscCodec

    model_path = Path(model_path)
    if not model_path.is_file():
        raise TiledInferenceError(f"ONNX model not found: {model_path}")
    sess, mode = _make_session(model_path, prefer_gpu=prefer_gpu)
    input_name = sess.get_inputs()[0].name
    output_name = sess.get_outputs()[0].name

    shape = tuple(int(x) for x in reader.shape)
    tile = tuple(int(t) for t in tile)
    if len(tile) != 3 or any(t <= 0 for t in tile):
        raise TiledInferenceError(f"tile must be a positive (il, xl, t) triple: {tile}")
    work = Path(work_root)
    work.mkdir(parents=True, exist_ok=True)
    class_dst = work / "classmap"
    prob_dst = work / "probmap"

    def open_or_create(path: Path, dtype: str):
        if (path / "zarr.json").exists():
            return zarr.open(str(path), mode="a")
        return zarr.create_array(
            str(path),
            shape=shape,
            dtype=dtype,
            chunks=(64, 128, 128),
            shards=(128, 512, 512),
            compressors=[BloscCodec(cname="zstd", clevel=3, shuffle="shuffle")],
            overwrite=False,
        )

    class_out = open_or_create(class_dst, "uint8")
    prob_out = open_or_create(prob_dst, "float16")

    starts = [tile_starts(n, t, overlap) for n, t in zip(shape, tile)]
    stride = [t - overlap for t in tile]
    done_dir = work / "tiles.done"
    done_dir.mkdir(parents=True, exist_ok=True)
    tiles = [
        (i, j, k)
        for i in range(len(starts[0]))
        for j in range(len(starts[1]))
        for k in range(len(starts[2]))
    ]
    completed = {p.name for p in done_dir.iterdir() if p.name.startswith("t_")}
    total = len(tiles)
    done_count = 0
    t0 = time.perf_counter()
    current_batch = max(1, int(batch))

    def tile_key(t):
        return f"t_{t[0]:05d}_{t[1]:05d}_{t[2]:05d}"

    idx = 0
    while idx < len(tiles):
        if cancel is not None and cancel():
            return {
                "mode": mode, "tiles_total": total, "tiles_done": done_count,
                "cancelled": True, "elapsed_s": time.perf_counter() - t0,
                "class_map": str(class_dst), "prob_map": str(prob_dst),
            }
        group = [t for t in tiles[idx : idx + current_batch]]
        group = [t for t in group if tile_key(t) not in completed]
        if not group:
            done_count += 0
            idx += current_batch
            continue
        try:
            _run_tile_group(
                reader, sess, input_name, output_name, classes,
                class_out, prob_out, starts, stride, overlap, shape, group, tile,
            )
        except Exception as exc:  # noqa: BLE001 - classify OOM vs contract error
            if current_batch > 1 and _looks_like_oom(exc):
                current_batch = max(1, current_batch // 2)
                time.sleep(0.5 / current_batch)  # exponential-ish backoff
                continue
            raise
        for t in group:
            marker = done_dir / tile_key(t)
            marker.write_text("ok")
        try:
            fd = os.open(done_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        done_count += len(group)
        idx += current_batch
        if progress is not None:
            progress(done_count / max(total, 1), f"{done_count}/{total} tiles")
    return {
        "mode": mode,
        "tiles_total": total,
        "tiles_done": done_count,
        "cancelled": False,
        "elapsed_s": time.perf_counter() - t0,
        "class_map": str(class_dst),
        "prob_map": str(prob_dst),
        "shape": list(shape),
        "classes": classes,
        "overlap": overlap,
    }


def _looks_like_oom(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "out of memory" in text or "oom" in text or "alloc" in text and "fail" in text


def _run_tile_group(
    reader, sess, input_name, output_name, classes,
    class_out, prob_out, starts, stride, overlap, shape, group, tile,
) -> None:
    """Read tiles (halo-expanded), infer once per group, center-crop fuse."""
    batch_tiles = []
    crops = []
    for (i, j, k) in group:
        s0, s1, s2 = starts[0][i], starts[1][j], starts[2][k]
        e0 = min(s0 + tile[0], shape[0])
        e1 = min(s1 + tile[1], shape[1])
        e2 = min(s2 + tile[2], shape[2])
        block = reader.read_voxel_window(s0, e0, s1, e1, s2, e2)
        # Pad edge tiles up to the tile shape with ZEROS: a 'same'-padding
        # conv model zero-pads at the VOLUME boundary, so edge tiles must
        # present exactly that beyond-edge geometry (reflect would invent
        # structure the whole-volume run never sees). Interior cut planes
        # never pad — the overlap halo carries real data there.
        pads = [(0, tile[a] - block.shape[a]) for a in range(3)]
        if any(p for p in pads):
            block = np.pad(block, pads, mode="constant", constant_values=0.0)
        batch_tiles.append(block)
        auth = [
            authoritative_range(i, starts[0], stride[0], overlap, shape[0]),
            authoritative_range(j, starts[1], stride[1], overlap, shape[1]),
            authoritative_range(k, starts[2], stride[2], overlap, shape[2]),
        ]
        # offset of the authoritative window inside the tile
        off = [
            (auth[0][0] - s0, auth[0][1] - s0),
            (auth[1][0] - s1, auth[1][1] - s1),
            (auth[2][0] - s2, auth[2][1] - s2),
        ]
        crops.append((auth, off))
    batch_np = np.stack(batch_tiles)[:, None].astype(np.float32)  # (N,1,D,H,W)
    out = sess.run([output_name], {input_name: batch_np})[0]
    out = np.asarray(out)
    if out.ndim == 5:  # (N,C,D,H,W)
        pass
    elif out.ndim == 4:  # (N,C,H,W) — 2-D model over (xl,t)? treat (D=C? no) — honest error
        raise TiledInferenceError(
            f"model output ndim={out.ndim}; tiled seismic expects (N,C,64,128,128)"
        )
    else:
        raise TiledInferenceError(f"model output ndim={out.ndim} unsupported")
    n_cls = out.shape[1]
    probs = _softmax(out.astype(np.float32)) if n_cls > 1 else np.concatenate(
        [1.0 - out, out], axis=1
    ).astype(np.float32)
    for bi, ((i, j, k), (auth, off)) in enumerate(zip(group, crops)):
        seg = probs[bi][
            :,
            off[0][0] : off[0][1],
            off[1][0] : off[1][1],
            off[2][0] : off[2][1],
        ]
        am = seg.argmax(axis=0).astype(np.uint8)
        mp = seg.max(axis=0).astype(np.float16)
        class_out[auth[0][0] : auth[0][1], auth[1][0] : auth[1][1], auth[2][0] : auth[2][1]] = am
        prob_out[auth[0][0] : auth[0][1], auth[1][0] : auth[1][1], auth[2][0] : auth[2][1]] = mp


class TiledOnnxProvider:
    """ModelProvider over a registered ONNX file (tiled, resumable, honest)."""

    model_id = "tiled-onnx-seismic"
    model_version = "tiled-onnx-v1"
    demo_only = False

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        from geoviz_seismic import open_volume

        if not inputs:
            raise TiledInferenceError("tiled inference needs a seismic input version")
        info = next(iter(inputs.values()))
        path = Path(str(info.get("path", "")))
        if not path.exists():
            raise TiledInferenceError(f"input volume not found: {path}")
        model_path = parameters.get("model_path")
        classes = int(parameters.get("classes", 0) or 0)
        if not model_path or classes <= 0:
            raise TiledInferenceError(
                "parameters must include model_path and classes (> 0)"
            )
        overlap = int(parameters.get("receptive_field", DEFAULT_RECEPTIVE_FIELD) or 0)
        batch = int(parameters.get("batch", 1) or 1)
        tile_param = parameters.get("tile")
        tile = (
            tuple(int(t) for t in tile_param)
            if tile_param
            else TILE
        )
        work_root = parameters.get("work_root")
        if not work_root:
            work_root = path.parent / f"{path.name}.inference"

        reader = open_volume(path)
        stats = run_tiled_inference(
            reader,
            model_path,
            classes=classes,
            work_root=work_root,
            overlap=overlap,
            batch=batch,
            prefer_gpu=bool(parameters.get("prefer_gpu", True)),
            tile=tile,
        )
        payload = {
            "source": PROVIDER_TILED_ONNX,
            "generator_version": self.model_version,
            "device_mode": stats["mode"],
            "tiles": stats["tiles_done"],
            "cancelled": stats["cancelled"],
            "elapsed_s": stats["elapsed_s"],
            "class_map": stats["class_map"],
            "prob_map": stats["prob_map"],
            "shape": stats["shape"],
            "volume_outputs": [
                {
                    "name": "facies class map",
                    "path": stats["class_map"],
                    "kind": "classmap",
                    "dtype": "uint8",
                },
                {
                    "name": "facies probability map",
                    "path": stats["prob_map"],
                    "kind": "probmap",
                    "dtype": "float16",
                },
            ],
        }
        if stats["mode"] == "cpu":
            payload["cpu_mode_note"] = "CUDAExecutionProvider unavailable — ran on CPU"
        return payload
