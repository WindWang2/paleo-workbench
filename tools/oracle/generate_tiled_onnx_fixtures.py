#!/usr/bin/env python3
"""Oracle fixture generator for the C++ tiled-inference kernel (CONV-13).

Imports the REAL ``paleo_workbench.prediction.tiled_onnx`` geometry
(tile_starts / authoritative_range / softmax budget / model-file gate) and
drives the REAL ``run_tiled_inference`` with:

- stub inference sessions standing in for the ONNX model (onnxruntime is not
  importable in this environment; the sessions are monkeypatched in via
  ``_make_session`` exactly at the seam production code defines), and
- an in-memory zarr stand-in (zarr is likewise not importable here).

Everything else — tile loop, resume markers, cancel protocol, zero padding,
center-crop fusion, softmax/sigmoid conversion, fp16 quantization — is the
production code under test. Outputs are frozen to JSON so the C++ port in
libs/prediction can be verified against them.

Stub operator (frozen contract, mirrored in C++ tiled_stub_test.cpp):
- "sign": per-voxel logits (x, -x) — receptive field 1.
- "conv2": separable binomial smoothing 0.25*L + 0.5*C + 0.25*R per axis
  (receptive field 3, overlap-sensitive), logits (c, -c).
- "conv3": same smoothing, logits (c, 2*c-1, 4*c-6) — 3-class ties at
  c = 1 (ch0/ch1), c = 2 (ch0/ch2), c = 2.5 (ch1/ch2).
- "sigmoid1": smoothed single channel; production code expands to
  [1-out, out] (tie at out = 0.5 → class 0).
- "oom_conv2": conv2 that fails with an OOM-looking error whenever the
  incoming batch has more than one item (exercises batch halving).
- "ndim4"/"ndim3": wrong-rank outputs for the honest-error paths.

All stub math is scalar-order-exact: elementwise IEEE float32 operations in a
fixed left-to-right order so the C++ mirror is bit-identical (verified below
against the vectorized formulation, ``equal_nan=True``).

Regenerate with (needs numpy + pydantic, e.g. the oracle venv):
    /tmp/pwb-oracle-venv/bin/python tools/oracle/generate_tiled_onnx_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.prediction import tiled_onnx as to  # noqa: E402

OUT = REPO_ROOT / "libs" / "prediction" / "prediction_tests" / "fixtures"

MODEL_BYTES = b"paleo-tiled-stub-model-v1\n"
MODEL_NAME = "stub-model.onnx"


# ---------------------------------------------------------------- stub zarr


class StubArray:
    """Minimal zarr-array stand-in: slice assignment over a numpy backing."""

    def __init__(self, path: Path, shape, dtype):
        self.path = path
        self.shape = tuple(int(x) for x in shape)
        self.dtype = np.dtype(dtype)
        self.data = np.zeros(self.shape, dtype=self.dtype)

    def __setitem__(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]


_ZARR_STORES: dict[str, StubArray] = {}


def _install_fake_zarr() -> None:
    zarr_mod = types.ModuleType("zarr")
    codecs_mod = types.ModuleType("zarr.codecs")

    class BloscCodec:  # pragma: no cover - config record only
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def create_array(path, *, shape, dtype, chunks=None, shards=None,
                     compressors=None, overwrite=False):
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        array = StubArray(target, shape, dtype)
        _ZARR_STORES[str(path)] = array
        (target / "zarr.json").write_text("{}", encoding="utf-8")
        return array

    def open(path, mode="a"):  # noqa: A001 - mirrors zarr.open
        return _ZARR_STORES[str(path)]

    zarr_mod.create_array = create_array
    zarr_mod.open = open
    codecs_mod.BloscCodec = BloscCodec
    zarr_mod.codecs = codecs_mod
    sys.modules["zarr"] = zarr_mod
    sys.modules["zarr.codecs"] = codecs_mod


# ------------------------------------------------------------- stub sessions


class _NS:
    def __init__(self, name):
        self.name = name


def stub_conv(block: np.ndarray) -> np.ndarray:
    """Separable binomial smoothing; scalar loop, fixed op order (see doc)."""
    out = block
    for axis in range(3):
        n = out.shape[axis]
        src = out
        o = np.empty_like(src)
        for i in range(n):
            sl_c = [slice(None)] * 3
            sl_c[axis] = i
            c = src[tuple(sl_c)]
            sl_l = list(sl_c)
            sl_l[axis] = i - 1 if i > 0 else None
            left = src[tuple(sl_l)] if i > 0 else np.float32(0)
            sl_r = list(sl_c)
            sl_r[axis] = i + 1 if i < n - 1 else None
            right = src[tuple(sl_r)] if i < n - 1 else np.float32(0)
            acc = np.float32(0.25) * left + np.float32(0.5) * c
            o[tuple(sl_c)] = acc + np.float32(0.25) * right
        out = o
    return out


def stub_logits(kind: str, block: np.ndarray) -> np.ndarray:
    if kind == "sign":
        return np.stack([block, -block])
    c = stub_conv(block)
    if kind in ("conv2", "oom_conv2"):
        return np.stack([c, -c])
    if kind == "conv3":
        ch1 = np.float32(2.0) * c - np.float32(1.0)
        ch2 = np.float32(4.0) * c - np.float32(6.0)
        return np.stack([c, ch1, ch2])
    if kind == "sigmoid1":
        return c[np.newaxis]
    raise AssertionError(f"unknown stub kind {kind}")


def stub_run(kind: str, batch: np.ndarray) -> np.ndarray:
    if kind == "oom_conv2" and batch.shape[0] > 1:
        raise RuntimeError("CUDA error: out of memory")
    if kind == "ndim4":
        return np.zeros((batch.shape[0], 2, batch.shape[2], batch.shape[3]),
                        dtype=np.float32)
    if kind == "ndim3":
        return np.zeros((batch.shape[0], 2, batch.shape[2]), dtype=np.float32)
    planes = [stub_logits(kind, batch[n, 0]) for n in range(batch.shape[0])]
    return np.stack(planes)


class StubSession:
    """Stands in for the ORT InferenceSession at the _make_session seam."""

    def __init__(self, kind: str):
        self.kind = kind

    def get_inputs(self):
        return [_NS("x")]

    def get_outputs(self):
        return [_NS("y")]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, output_names, feeds):
        assert output_names == ["y"]
        return [stub_run(self.kind, feeds["x"])]


class StubReader:
    def __init__(self, volume: np.ndarray):
        self.volume = volume
        self.shape = volume.shape

    def read_voxel_window(self, s0, e0, s1, e1, s2, e2):
        return self.volume[s0:e0, s1:e1, s2:e2]


def _stub_selfcheck() -> None:
    """Document: the scalar loop equals the vectorized formulation bitwise."""
    rng = np.random.default_rng(20260917)
    for _ in range(8):
        shape = tuple(int(x) for x in rng.integers(1, 8, 3))
        t = (rng.standard_normal(shape) * 2).astype(np.float32)

        def vec3(u):
            for axis in range(3):
                p = np.pad(u, 1)
                sl = [slice(1, -1)] * 3
                sl_l = list(sl)
                sl_l[axis] = slice(0, -2)
                sl_r = list(sl)
                sl_r[axis] = slice(2, None)
                u = (np.float32(0.25) * p[tuple(sl_l)]
                     + np.float32(0.5) * p[tuple(sl)]
                     + np.float32(0.25) * p[tuple(sl_r)]).astype(np.float32)
            return u

        assert np.array_equal(stub_conv(t), vec3(t), equal_nan=True)
    b = (rng.standard_normal((1, 1, 3, 4, 5)) * 2).astype(np.float32)
    probs = _softmax_ref(stub_run("sign", b))  # (1,2,3,4,5)
    x = b[0, 0]
    loop = np.empty_like(probs[0])
    for d in range(3):
        for h in range(4):
            for w in range(5):
                col = np.stack([x[d, h, w], -x[d, h, w]])
                m = col[0]
                if col[1] > m:
                    m = col[1]
                e0 = np.exp(col[0] - m)
                e1 = np.exp(col[1] - m)
                s = e0 + e1
                loop[0, d, h, w] = e0 / s
                loop[1, d, h, w] = e1 / s
    assert np.array_equal(probs[0], loop, equal_nan=True)


def _softmax_ref(logits: np.ndarray) -> np.ndarray:
    """Reference (N,C,D,H,W) softmax matching tiled_onnx._softmax exactly."""
    m = logits.max(axis=1, keepdims=True)
    e = np.exp(logits - m)
    return e / e.sum(axis=1, keepdims=True)


# ----------------------------------------------------------------- volumes


def volume(kind: str, shape, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    d0, d1, d2 = shape
    if kind == "ramp":
        i = np.arange(d0)[:, None, None]
        j = np.arange(d1)[None, :, None]
        k = np.arange(d2)[None, None, :]
        return ((i * 31 + j * 7 + k * 3) % 11 - 5).astype(np.float32)
    if kind == "rand":
        return (rng.standard_normal(shape) * 0.8).astype(np.float32)
    if kind == "const_half":
        return np.full(shape, 0.5, dtype=np.float32)
    if kind == "ties":
        v = (rng.standard_normal(shape) * 0.4).astype(np.float32)
        v[: d0 // 2, :, :] = np.float32(1.0)
        v[:, : d1 // 2, :] = np.float32(2.0)
        v[: d0 // 2, : d1 // 2, : d2 // 2] = np.float32(2.5)
        v[d0 - 1, d1 - 1, d2 - 1] = np.float32(0.5)
        return v
    if kind == "sig_mix":
        v = (rng.standard_normal(shape) * 0.3).astype(np.float32)
        v = np.clip(v, -0.2, 0.2) + np.float32(0.5)
        v[: d0 // 2, :, :] = np.float32(0.25)
        v[d0 // 2 :, :, d2 // 2 :] = np.float32(0.75)
        v[d0 // 2 :, :, : d2 // 2] = np.float32(0.5)
        return v
    if kind == "rand_nan":
        v = (rng.standard_normal(shape) * 0.8).astype(np.float32)
        flat = v.reshape(-1)
        flat[4 :: 37] = np.float32("nan")
        return flat.reshape(shape)
    raise AssertionError(f"unknown volume kind {kind}")


# -------------------------------------------------------------- json help


def f16_json(arr: np.ndarray) -> list:
    """float16 array → JSON values (non-finite as strings)."""
    out = []
    for x in np.asarray(arr).reshape(-1):
        v = float(x)
        if np.isnan(x):
            out.append("NaN")
        elif np.isposinf(x):
            out.append("Inf")
        elif np.isneginf(x):
            out.append("-Inf")
        else:
            out.append(v)
    return out


def f32_json(arr: np.ndarray) -> list:
    out = []
    for x in np.asarray(arr).reshape(-1):
        if np.isnan(x):
            out.append("NaN")
        elif np.isposinf(x):
            out.append("Inf")
        elif np.isneginf(x):
            out.append("-Inf")
        else:
            out.append(float(x))
    return out


# --------------------------------------------------------------- run cases


def run_case(case: dict, model_path: Path, root: Path, reuse: dict) -> dict:
    shape = tuple(case["volume"]["shape"])
    vol = volume(case["volume"]["kind"], shape, case["volume"]["seed"])
    reader = StubReader(vol)
    # A resumed run reopens the SAME work dir (the in-memory store stand-in
    # keeps data by path, mirroring zarr's on-disk persistence).
    work = root / (case["reuse_work_of"] or case["id"]) \
        if case.get("reuse_work_of") else root / case["id"]
    work.mkdir(parents=True, exist_ok=True)
    for name in case.get("predone", []):
        (work / "tiles.done").mkdir(parents=True, exist_ok=True)
        (work / "tiles.done" / name).write_text("ok")

    session_kind = case["stub"]
    original = to._make_session
    to._make_session = lambda mp, prefer_gpu: (StubSession(session_kind), "cpu")
    try:
        cancel = None
        if case.get("cancel") == "always":
            cancel = lambda: True  # noqa: E731
        elif case.get("cancel") == "after_progress":
            state = {"n": 0}

            def progress(_ratio, _msg):
                state["n"] += 1

            case["_progress"] = progress

            def cancel():
                return state["n"] >= case.get("cancel_after", 1)

        kwargs = {}
        if case.get("cancel") == "after_progress":
            kwargs["progress"] = case["_progress"]
        try:
            stats = to.run_tiled_inference(
                reader,
                model_path,
                classes=case["classes"],
                work_root=work,
                overlap=case["overlap"],
                batch=case["batch"],
                prefer_gpu=False,
                tile=tuple(case["tile"]),
                cancel=cancel,
                **kwargs,
            )
        except Exception as exc:  # frozen honest-error paths
            return {
                "id": case["id"],
                "error": scrub(str(exc), root),
                "error_type": type(exc).__name__,
            }
    finally:
        to._make_session = original

    class_store = _ZARR_STORES[str(work / "classmap")]
    prob_store = _ZARR_STORES[str(work / "probmap")]
    markers = sorted(p.name for p in (work / "tiles.done").iterdir())
    return {
        "id": case["id"],
        "stats": {
            "mode": stats["mode"],
            "tiles_total": stats["tiles_total"],
            "tiles_done": stats["tiles_done"],
            "cancelled": stats["cancelled"],
            "batch": stats["batch"],
            "shape": stats["shape"],
            "classes": stats["classes"],
            "overlap": stats["overlap"],
            "binding_present": "model_binding" in stats,
        },
        "classmap": [int(x) for x in class_store.data.reshape(-1)],
        "probmap": f16_json(prob_store.data),
        "markers": markers,
    }


# ------------------------------------------------------------------- main


def scrub(text: str, root: Path) -> str:
    """Mask the volatile temp root so frozen messages are path-portable."""
    return text.replace(str(root), "<WORK>")


def main() -> int:
    _install_fake_zarr()
    _stub_selfcheck()

    fixture: dict = {
        "meta": {
            "module": "paleo_workbench.prediction.tiled_onnx",
            "numpy": np.__version__,
            "softmax_budget_bytes": to.SOFTMAX_INTERMEDIATE_BUDGET_BYTES,
            "default_tile": list(to.TILE),
            "default_overlap": to.DEFAULT_RECEPTIVE_FIELD,
            "model_name": MODEL_NAME,
            "model_bytes": len(MODEL_BYTES),
            "model_content": MODEL_BYTES.decode("utf-8"),
            "model_sha256": hashlib.sha256(MODEL_BYTES).hexdigest(),
        }
    }

    # -- tile_starts -------------------------------------------------------
    ts_cases = []
    for n, t, ov in [(100, 30, 8), (26, 8, 4), (7, 8, 4), (128, 64, 8),
                     (5, 4, 1), (9, 4, 0), (1, 1, 0), (5, 4, 4)]:
        entry = {"n": n, "tile": t, "overlap": ov}
        try:
            entry["starts"] = to.tile_starts(n, t, ov)
        except to.TiledInferenceError as exc:
            entry["error"] = str(exc)
        ts_cases.append(entry)
    fixture["tile_starts"] = ts_cases

    # -- authoritative ranges (partition property checked here) ------------
    auth_cases = []
    for n, t, ov in [(100, 30, 8), (26, 8, 4), (7, 8, 4), (128, 64, 8),
                     (5, 4, 1), (9, 4, 0), (6, 5, 3)]:
        starts = to.tile_starts(n, t, ov)
        stride = t - ov
        ranges = [list(to.authoritative_range(i, starts, stride, ov, n))
                  for i in range(len(starts))]
        assert ranges[0][0] == 0 and ranges[-1][1] == n
        total = sum(hi - lo for lo, hi in ranges)
        assert total == n, (n, t, ov, ranges)
        for a, b in zip(ranges, ranges[1:]):
            assert a[1] == b[0]
        auth_cases.append(
            {"n": n, "tile": t, "overlap": ov, "stride": stride,
             "starts": starts, "ranges": ranges})
    fixture["authoritative"] = auth_cases

    # -- softmax budget ----------------------------------------------------
    budget_cases = []
    for batch, classes, tile in [
        (1, 4, (64, 128, 128)),
        (32, 4, (64, 128, 128)),      # planned == budget → ok
        (33, 4, (64, 128, 128)),      # planned > budget → reduce to <= 32
        (1, 65536, (8, 16, 16)),      # classes_bytes == budget → ok
        (1, 65537, (8, 16, 16)),      # classes_bytes > budget → refuse
        (2, 65537, (8, 16, 16)),      # classes refusal wins (checked first)
    ]:
        entry = {"batch": batch, "classes": classes, "tile": list(tile)}
        try:
            to._validate_softmax_budget(batch, classes, tile)
            entry["ok"] = True
        except to.TiledInferenceError as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
        budget_cases.append(entry)
    fixture["softmax_budget"] = budget_cases

    # -- model file gate ---------------------------------------------------
    model_cases = []
    root_tmp = Path(tempfile.mkdtemp(prefix="conv13_oracle_"))
    try:
        model_path = root_tmp / MODEL_NAME
        model_path.write_bytes(MODEL_BYTES)

        binding = to._check_onnx_model_file(model_path)
        model_cases.append({
            "kind": "ok",
            "binding": {
                "model_file": binding["model_file"],
                "model_bytes": binding["model_bytes"],
                "model_sha256": binding["model_sha256"],
            },
        })

        bad = root_tmp / "stub.txt"
        bad.write_bytes(MODEL_BYTES)
        try:
            to._check_onnx_model_file(bad)
        except to.TiledInferenceError as exc:
            model_cases.append({"kind": "suffix", "error": scrub(str(exc), root_tmp)})

        try:
            to._check_onnx_model_file(root_tmp)  # a directory
        except to.TiledInferenceError as exc:
            model_cases.append({"kind": "dir", "error": scrub(str(exc), root_tmp)})

        empty = root_tmp / "empty.onnx"
        empty.write_bytes(b"")
        try:
            to._check_onnx_model_file(empty)
        except to.TiledInferenceError as exc:
            model_cases.append({"kind": "empty", "error": scrub(str(exc), root_tmp)})

        capped = root_tmp / "big.onnx"
        capped.write_bytes(b"x" * 16)
        old = dict(__import__("os").environ)
        __import__("os").environ["PALEO_ONNX_MAX_MODEL_BYTES"] = "8"
        try:
            try:
                to._check_onnx_model_file(capped)
            except to.TiledInferenceError as exc:
                model_cases.append(
                    {"kind": "cap", "error": scrub(str(exc), root_tmp)})
        finally:
            __import__("os").environ.clear()
            __import__("os").environ.update(old)
        fixture["model_file"] = model_cases

        # -- full runs -----------------------------------------------------
        run_specs = [
            # multi-tile every axis, no halo, batch 3 (grouping crosses axes)
            {"id": "sign_small_ov0", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 3},
            # same geometry, batch 1 — grouping must not change fusion
            {"id": "sign_ov0_batch1", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 1},
            # receptive field 3 + halo 4: overlap-sensitive model
            {"id": "conv2_ov4", "stub": "conv2", "classes": 2,
             "volume": {"kind": "rand", "shape": [10, 12, 9], "seed": 11},
             "tile": [8, 8, 8], "overlap": 4, "batch": 2},
            # odd overlap (//2 = 1): asymmetric center crop
            {"id": "conv2_ov3_odd", "stub": "conv2", "classes": 2,
             "volume": {"kind": "rand", "shape": [9, 6, 20], "seed": 12},
             "tile": [4, 6, 8], "overlap": 3, "batch": 5},
            # 3-class ties at conv == 1 / 2 / 2.5 (first max wins)
            {"id": "conv3_ties", "stub": "conv3", "classes": 3,
             "volume": {"kind": "ties", "shape": [6, 6, 6], "seed": 13},
             "tile": [4, 4, 4], "overlap": 2, "batch": 4},
            # NaN voxels: argmax falls to first NaN channel, prob stays NaN
            {"id": "conv3_nan", "stub": "conv3", "classes": 3,
             "volume": {"kind": "rand_nan", "shape": [5, 7, 6], "seed": 14},
             "tile": [4, 8, 6], "overlap": 2, "batch": 2},
            # single tile, exact 0.5 everywhere → sigmoid tie → class 0
            {"id": "sigmoid1_half", "stub": "sigmoid1", "classes": 1,
             "volume": {"kind": "const_half", "shape": [4, 4, 4], "seed": 15},
             "tile": [4, 4, 4], "overlap": 0, "batch": 1},
            # 1-class path with 0.25/0.5/0.75 regions
            {"id": "sigmoid1_mix", "stub": "sigmoid1", "classes": 1,
             "volume": {"kind": "sig_mix", "shape": [7, 5, 9], "seed": 16},
             "tile": [4, 4, 4], "overlap": 2, "batch": 2},
            # OOM at batch > 1: 4 → 2 → 1 halving with backoff, then success
            {"id": "oom_halving", "stub": "oom_conv2", "classes": 2,
             "volume": {"kind": "rand", "shape": [8, 8, 8], "seed": 17},
             "tile": [4, 4, 4], "overlap": 2, "batch": 4},
            # cancel before the first group
            {"id": "cancel_immediate", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 2,
             "cancel": "always"},
            # one tile lands, then cancel; a resumed run finishes the volume
            {"id": "cancel_then_resume", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 1,
             "cancel": "after_progress", "cancel_after": 1},
            {"id": "resume_after_cancel", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 1,
             "reuse_work_of": "cancel_then_resume"},
            # markers pre-seeded for every inline-start == i == 0 slice set
            {"id": "resume_predone", "stub": "conv2", "classes": 2,
             "volume": {"kind": "rand", "shape": [10, 12, 9], "seed": 11},
             "tile": [8, 8, 8], "overlap": 4, "batch": 2,
             "predone": [f"t_{0:05d}_{j:05d}_{k:05d}"
                         for j in range(3) for k in range(3)]},
            # everything already done: nothing written, tiles_done == 0
            {"id": "resume_all_done", "stub": "sign", "classes": 2,
             "volume": {"kind": "ramp", "shape": [5, 9, 7], "seed": 1},
             "tile": [4, 8, 6], "overlap": 0, "batch": 2,
             "predone": "all"},
        ]

        run_results = []
        for spec in run_specs:
            if spec.get("predone") == "all":
                starts = [to.tile_starts(n, t, spec["overlap"])
                          for n, t in zip(spec["volume"]["shape"], spec["tile"])]
                spec["predone"] = [
                    f"t_{i:05d}_{j:05d}_{k:05d}"
                    for i in range(len(starts[0]))
                    for j in range(len(starts[1]))
                    for k in range(len(starts[2]))]
            result = run_case(spec, model_path, root_tmp, {})
            spec.pop("_progress", None)
            # Freeze the actual volume values (C-order float32) so the C++
            # side reads the exact bytes the Python run consumed.
            spec["volume"]["data"] = f32_json(
                volume(spec["volume"]["kind"],
                       tuple(spec["volume"]["shape"]),
                       spec["volume"]["seed"]))
            result["input"] = spec
            run_results.append(result)

        # Parity with test_resume_skips_completed_tiles: the resumed final
        # state equals the uninterrupted run of the same geometry.
        fresh = next(r for r in run_results if r["id"] == "sign_ov0_batch1")
        resumed = next(r for r in run_results if r["id"] == "resume_after_cancel")
        assert fresh["classmap"] == resumed["classmap"]
        assert fresh["probmap"] == resumed["probmap"]
        assert len(resumed["markers"]) == len(fresh["markers"])
        fixture["runs"] = run_results

        # -- run-level honest errors ---------------------------------------
        def run_error(case_id, reader, *, model_path_override=None,
                      session_kind=None, **kwargs):
            work = root_tmp / f"w_{case_id}"
            work.mkdir(parents=True, exist_ok=True)
            original = to._make_session
            if session_kind is not None:
                to._make_session = lambda mp, prefer_gpu, _k=session_kind: (
                    StubSession(_k), "cpu")
            try:
                try:
                    to.run_tiled_inference(
                        reader,
                        model_path_override or model_path,
                        classes=kwargs.get("classes", 2),
                        work_root=work,
                        overlap=kwargs.get("overlap", 0),
                        batch=kwargs.get("batch", 1),
                        prefer_gpu=False,
                        tile=kwargs.get("tile", (4, 4, 4)),
                    )
                except Exception as exc:
                    return {
                        "id": case_id,
                        "error": scrub(str(exc), root_tmp),
                        "error_type": type(exc).__name__,
                        "input": {
                            "model": (
                                "missing" if model_path_override is not None
                                and "nope" in str(model_path_override)
                                else "suffix" if model_path_override is not None
                                else "ok"
                            ),
                            "stub": session_kind,
                            "tile": list(kwargs.get("tile", (4, 4, 4))),
                            "classes": kwargs.get("classes", 2),
                            "batch": kwargs.get("batch", 1),
                            "overlap": kwargs.get("overlap", 0),
                        },
                    }
                raise AssertionError(f"{case_id}: expected an error")
            finally:
                to._make_session = original

        tiny = StubReader(volume("ramp", (4, 4, 4), 1))
        err_runs = [
            run_error("err_model_missing",
                      StubReader(volume("ramp", (4, 4, 4), 1)),
                      model_path_override=root_tmp / "nope" / "absent.onnx"),
            run_error("err_model_suffix", tiny,
                      model_path_override=root_tmp / "stub.txt"),
            run_error("err_tile_zero", tiny, tile=(0, 4, 4)),
            run_error("err_classes_zero", tiny, classes=0),
            run_error("err_batch_zero", tiny, batch=0),
            run_error("err_ndim4", tiny, session_kind="ndim4"),
            run_error("err_ndim3", tiny, session_kind="ndim3"),
        ]
        fixture["run_errors"] = err_runs

    finally:
        shutil.rmtree(root_tmp, ignore_errors=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tiled_stub_oracle.json").write_text(
        json.dumps(fixture, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    n_runs = sum(1 for r in fixture["runs"] if "stats" in r)
    n_err_runs = sum(1 for r in fixture["runs"] if "error" in r)
    print(f"frozen: {len(fixture['tile_starts'])} tile_starts, "
          f"{len(fixture['authoritative'])} authoritative, "
          f"{len(fixture['softmax_budget'])} budget, "
          f"{len(fixture['model_file'])} model-file, "
          f"{len(fixture['runs'])} runs ({n_runs} ok / {n_err_runs} err), "
          f"{len(fixture['run_errors'])} run-errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
