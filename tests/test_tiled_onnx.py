"""Tiled ONNX inference (#1085) — REAL onnxruntime, REAL models.

The models are built in-test with the ``onnx`` package so their semantics
are fully known: a 2-class per-voxel classifier whose argmax depends on the
sign of (a smoothed version of) the amplitude. Tiled output must equal the
same model applied to the WHOLE volume in one shot — center-crop fusion
with receptive-field overlap leaves no seam and exactly one authoritative
prediction per voxel.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")
onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from geoviz_seismic import open_volume  # noqa: E402
from paleo_workbench.prediction.providers import get_provider  # noqa: E402
from paleo_workbench.prediction.tiled_onnx import (  # noqa: E402
    authoritative_range,
    run_tiled_inference,
    tile_starts,
)
from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeParams,
    transcode_segy_to_zarr,
)

NIL, NXL, NT = 26, 44, 40
PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(32, 32, 32), clevel=1)


def _cube(seed: int = 31) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.5).astype(np.float32)
    cube[5:9, 10:30, 15:25] += 1.5
    return cube


def _make_store(tmp: Path) -> tuple[Path, np.ndarray]:
    import segyio as _segyio

    cube = _cube()
    segy = tmp / "v.segy"
    spec = _segyio.spec()
    spec.ilines = list(range(1, NIL + 1))
    spec.xlines = list(range(1, NXL + 1))
    spec.samples = list(range(NT))
    spec.format = 5
    with _segyio.create(str(segy), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    _segyio.TraceField.INLINE_3D: il + 1,
                    _segyio.TraceField.CROSSLINE_3D: xl + 1,
                    _segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    store = tmp / "store"
    transcode_segy_to_zarr(segy, store, params=PARAMS)
    return store, cube


def _sign_model() -> onnx.ModelProto:
    """2-class classifier: logits = (x, -x); argmax == (x > 0).

    Receptive field 1 (identity) — pins the tiling/fusion machinery with a
    per-voxel decision.
    """
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, ["n", 1, "d", "h", "w"])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, ["n", 2, "d", "h", "w"])
    neg = helper.make_node("Neg", ["x"], ["xn"])
    out = helper.make_node("Concat", ["x", "xn"], ["y"], axis=1)
    graph = helper.make_graph([neg, out], "sign", [x], [y])
    return helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])


def _conv_model() -> onnx.ModelProto:
    """2-class classifier with receptive field 3: logits = (k*x, -k*x)
    where k is a 3x3x3 all-ones/27 average kernel — overlap-sensitive.

    With receptive field 3 the halo/center-crop protocol must matter: a
    naive no-overlap tiling would disagree with whole-volume inference at
    tile borders; center-crop fusion must not.
    """
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, ["n", 1, "d", "h", "w"])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, ["n", 2, "d", "h", "w"])
    k = numpy_helper.from_array(
        np.full((1, 1, 3, 3, 3), 1.0 / 27.0, dtype=np.float32), "k"
    )
    conv = helper.make_node(
        "Conv", ["x", "k"], ["c"], pads=[1, 1, 1, 1, 1, 1]
    )
    neg = helper.make_node("Neg", ["c"], ["cn"])
    out = helper.make_node("Concat", ["c", "cn"], ["y"], axis=1)
    graph = helper.make_graph([conv, neg, out], "convsign", [x], [y], [k])
    return helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])


def _save(model: onnx.ModelProto, path: Path) -> Path:
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


def _reference(model_path: Path, cube: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    batch = cube[None, None].astype(np.float32)
    logits = np.asarray(sess.run(["y"], {"x": batch})[0])
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = e / e.sum(axis=1, keepdims=True)
    return probs.argmax(axis=1)[0], probs.max(axis=1)[0]


# ---------------------------------------------------------------- tiling math


def test_tile_partition_covers_exactly_once():
    for n, tile, overlap in [(100, 30, 8), (26, 8, 4), (7, 8, 4), (128, 64, 8)]:
        starts = tile_starts(n, tile, overlap)
        stride = tile - overlap
        owned = []
        for i in range(len(starts)):
            lo, hi = authoritative_range(i, starts, stride, overlap, n)
            owned.append((lo, hi))
            assert 0 <= lo < hi <= n
            # tile window actually covers the owned region
            assert starts[i] <= lo and hi <= min(starts[i] + tile, max(n, tile))
        # exact partition: contiguous, no gap, no overlap
        assert owned[0][0] == 0
        assert owned[-1][1] == n
        for a, b in zip(owned, owned[1:]):
            assert a[1] == b[0]
        total = sum(hi - lo for lo, hi in owned)
        assert total == n


# ------------------------------------------------------------------- engine


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("onnx")
    return _make_store(tmp)


@pytest.mark.parametrize("model_fn,overlap", [(_sign_model, 0), (_conv_model, 4)])
def test_tiled_equals_whole_volume_inference(store, tmp_path, model_fn, overlap):
    dst, cube = store
    model_path = _save(model_fn(), tmp_path / (model_fn.__name__ + ".onnx"))
    reader = open_volume(dst)
    stats = run_tiled_inference(
        reader,
        model_path,
        classes=2,
        work_root=tmp_path / f"work_{model_fn.__name__}",
        overlap=overlap,
        batch=2,
        tile=(8, 16, 16),
        prefer_gpu=False,
    )
    assert stats["cancelled"] is False
    assert stats["mode"] == "cpu"  # honest device reporting
    ref_arg, ref_prob = _reference(model_path, cube)
    classmap = np.asarray(zarr.open(stats["class_map"], mode="r")[:, :, :])
    probmap = np.asarray(zarr.open(stats["prob_map"], mode="r")[:, :, :])
    assert classmap.shape == cube.shape
    np.testing.assert_array_equal(classmap, ref_arg)
    np.testing.assert_allclose(probmap, ref_prob.astype(np.float16), atol=1e-3)
    assert probmap.dtype == np.float16 and classmap.dtype == np.uint8


def test_resume_skips_completed_tiles(store, tmp_path):
    dst, cube = store
    model_path = _save(_sign_model(), tmp_path / "m.onnx")
    reader = open_volume(dst)
    work = tmp_path / "resume_work"

    # First pass: cancel after the first progress report.
    calls = {"n": 0}

    def cancel():
        return calls["n"] >= 1

    def progress(ratio, msg):
        calls["n"] += 1

    stats = run_tiled_inference(
        reader, model_path, classes=2, work_root=work, overlap=0, batch=1,
        tile=(8, 16, 16), prefer_gpu=False, progress=progress, cancel=cancel,
    )
    assert stats["cancelled"] is True
    done_markers = list((work / "tiles.done").iterdir())
    assert 0 < len(done_markers) < stats["tiles_total"]

    # Resume: completes and matches the whole-volume reference.
    stats2 = run_tiled_inference(
        reader, model_path, classes=2, work_root=work, overlap=0, batch=1,
        tile=(8, 16, 16), prefer_gpu=False,
    )
    assert stats2["cancelled"] is False
    ref_arg, _ = _reference(model_path, cube)
    classmap = np.asarray(zarr.open(stats2["class_map"], mode="r")[:, :, :])
    np.testing.assert_array_equal(classmap, ref_arg)


def test_provider_contract_and_cpu_mode_label(store, tmp_path):
    dst, cube = store
    model_path = _save(_sign_model(), tmp_path / "p.onnx")
    provider = get_provider("tiled_onnx")
    payload = provider.run(
        {("version-1"): {"path": str(dst), "name": "v", "asset_type": "seismic", "format": "zarr-v3"}},
        {
            "model_path": str(model_path),
            "classes": 2,
            "receptive_field": 0,
            "tile": (8, 16, 16),
            "work_root": str(tmp_path / "prov_work"),
        },
    )
    assert payload["device_mode"] == "cpu"
    assert "cpu_mode_note" in payload
    assert len(payload["volume_outputs"]) == 2
    kinds = {v["kind"]: v for v in payload["volume_outputs"]}
    assert set(kinds) == {"classmap", "probmap"}
    ref_arg, _ = _reference(model_path, cube)
    classmap = np.asarray(zarr.open(kinds["classmap"]["path"], mode="r")[:, :, :])
    np.testing.assert_array_equal(classmap, ref_arg)


def test_non_model_file_refused_before_native_loader(tmp_path):
    """#1176: devices/non-onnx files never reach ORT."""
    from paleo_workbench.prediction.tiled_onnx import (
        TiledInferenceError,
        _check_onnx_model_file,
    )

    fake = tmp_path / "evil.bin"
    fake.write_bytes(b"\x00" * 64)
    with pytest.raises(TiledInferenceError):
        _check_onnx_model_file(fake)
    with pytest.raises(TiledInferenceError):
        _check_onnx_model_file(tmp_path / "missing.onnx")
    with pytest.raises(TiledInferenceError):
        _check_onnx_model_file(Path("/dev/null"))


def test_model_binding_records_bytes_identity(tmp_path):
    """#1176: the loaded model's name/size/sha bind DERIVED to real bytes."""
    from paleo_workbench.catalog.checksum import sha256_file
    from paleo_workbench.prediction.tiled_onnx import _check_onnx_model_file

    model_path = _save(_sign_model(), tmp_path / "m.onnx")
    binding = _check_onnx_model_file(model_path)
    assert binding["model_file"] == "m.onnx"
    assert binding["model_bytes"] == model_path.stat().st_size > 0
    assert binding["model_sha256"] == sha256_file(model_path)
