"""Prediction runtime oracle generator.

Builds the synthetic ONNX models + seismic volumes + model packages the
native prediction runtime test replays, and freezes the EXPECTED outputs by
running the production Python tiled inference (paleo_workbench.prediction.
tiled_onnx.run_tiled_inference) through the real onnxruntime CPU session.

Run with the repository venv (onnx + onnxruntime + numpy + zarr):

    .venv/Scripts/python.exe tools/oracle/generate_prediction_runtime_fixtures.py

Outputs (all committed):
    libs/prediction/prediction_tests/fixtures/prediction_runtime/
        models/*.onnx, volumes/*.raw
        packages/*/manifest.json (+ model.onnx)
    libs/prediction/prediction_tests/fixtures/prediction_runtime_oracle.json

The C++ test never calls Python: this generator is the oracle.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = (
    REPO_ROOT
    / "libs"
    / "prediction"
    / "prediction_tests"
    / "fixtures"
    / "prediction_runtime"
)
ORACLE_PATH = (
    REPO_ROOT
    / "libs"
    / "prediction"
    / "prediction_tests"
    / "fixtures"
    / "prediction_runtime_oracle.json"
)

VOLUME_SHAPE = (10, 12, 9)  # (inline, xline, time) — odd dims on purpose
TILE = (6, 8, 5)
OVERLAP = 2
CLASSES = 3
CLASS_NAMES = ["sand", "mud", "shale"]
CRS = "EPSG:32650"
GEOTRANSFORM = [500000.0, 25.0, 0.0, 4200000.0, 0.0, -25.0]
NODATA_DECLARED = -999.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def synthetic_volume() -> np.ndarray:
    values = np.empty(VOLUME_SHAPE, dtype=np.float32)
    for i in range(VOLUME_SHAPE[0]):
        for j in range(VOLUME_SHAPE[1]):
            for k in range(VOLUME_SHAPE[2]):
                values[i, j, k] = float(((i * 13 + j * 7 + k * 3) % 29)) / 8.0 - 1.5
    return values


def make_conv3d_c3(path: Path) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    weight = (
        np.arange(81, dtype=np.float32).reshape(3, 1, 3, 3, 3) / 81.0 - 0.5
    )
    bias = np.array([0.5, -0.25, 0.125], dtype=np.float32)
    inputs = [
        helper.make_tensor_value_info(
            "input", TensorProto.FLOAT, [None, 1, None, None, None]
        )
    ]
    outputs = [
        helper.make_tensor_value_info(
            "logits", TensorProto.FLOAT, [None, 3, None, None, None]
        )
    ]
    nodes = [
        helper.make_node(
            "Conv",
            ["input", "weight", "bias"],
            ["logits"],
            kernel_shape=[3, 3, 3],
            pads=[1, 1, 1, 1, 1, 1],
        )
    ]
    graph = helper.make_graph(
        nodes,
        "conv3d_c3",
        inputs,
        outputs,
        initializer=[
            numpy_helper.from_array(weight, "weight"),
            numpy_helper.from_array(bias, "bias"),
        ],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_conv3d_c2(path: Path) -> None:
    """Same conv but 2 output classes: package declares 3 -> mismatch."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    weight = np.arange(54, dtype=np.float32).reshape(2, 1, 3, 3, 3) / 54.0 - 0.5
    bias = np.array([0.25, -0.125], dtype=np.float32)
    inputs = [
        helper.make_tensor_value_info(
            "input", TensorProto.FLOAT, [None, 1, None, None, None]
        )
    ]
    outputs = [
        helper.make_tensor_value_info(
            "logits", TensorProto.FLOAT, [None, 2, None, None, None]
        )
    ]
    nodes = [
        helper.make_node(
            "Conv",
            ["input", "weight", "bias"],
            ["logits"],
            kernel_shape=[3, 3, 3],
            pads=[1, 1, 1, 1, 1, 1],
        )
    ]
    graph = helper.make_graph(
        nodes,
        "conv3d_c2",
        inputs,
        outputs,
        initializer=[
            numpy_helper.from_array(weight, "weight"),
            numpy_helper.from_array(bias, "bias"),
        ],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_conv3d_c3_in2(path: Path) -> None:
    """2-channel input, 3-class output: package declares 1 band -> the
    native input/band contract must fail early."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    weight = (
        np.arange(162, dtype=np.float32).reshape(3, 2, 3, 3, 3) / 162.0 - 0.5
    )
    bias = np.array([0.25, -0.5, 0.125], dtype=np.float32)
    graph = helper.make_graph(
        [
            helper.make_node(
                "Conv",
                ["input", "weight", "bias"],
                ["logits"],
                kernel_shape=[3, 3, 3],
                pads=[1, 1, 1, 1, 1, 1],
            )
        ],
        "conv3d_c3_in2",
        [
            helper.make_tensor_value_info(
                "input", TensorProto.FLOAT, [None, 2, None, None, None]
            )
        ],
        [
            helper.make_tensor_value_info(
                "logits", TensorProto.FLOAT, [None, 3, None, None, None]
            )
        ],
        initializer=[
            numpy_helper.from_array(weight, "weight"),
            numpy_helper.from_array(bias, "bias"),
        ],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_identity_c1(path: Path) -> None:
    import onnx
    from onnx import TensorProto, helper

    value = [None, 1, None, None, None]
    graph = helper.make_graph(
        [helper.make_node("Identity", ["input"], ["logits"])],
        "identity_c1",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, value)],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, value)],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_tie_c1(path: Path) -> None:
    """logits == 0.5 everywhere: the sigmoid pair is a (0.5, 0.5) tie."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    value = [None, 1, None, None, None]
    zero = np.array([0.0], dtype=np.float32)
    half = np.array([0.5], dtype=np.float32)
    nodes = [
        helper.make_node("Mul", ["input", "zero"], ["scaled"]),
        helper.make_node("Add", ["scaled", "half"], ["logits"]),
    ]
    graph = helper.make_graph(
        nodes,
        "tie_c1",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, value)],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, value)],
        initializer=[
            numpy_helper.from_array(zero, "zero"),
            numpy_helper.from_array(half, "half"),
        ],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_identity_dtype(path: Path, element_type) -> None:
    """Identity model with a float16/float64 input port (conversion seam)."""
    import onnx
    from onnx import TensorProto, helper

    value = [None, 1, None, None, None]
    graph = helper.make_graph(
        [helper.make_node("Identity", ["input"], ["logits"])],
        "identity_dtype",
        [helper.make_tensor_value_info("input", element_type, value)],
        [helper.make_tensor_value_info("logits", element_type, value)],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def make_bad_rank(path: Path) -> None:
    """Squeeze channel axis -> rank-4 output (the honest ndim error)."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    value = [None, 1, None, None, None]
    axes = np.array([1], dtype=np.int64)
    graph = helper.make_graph(
        [helper.make_node("Squeeze", ["input", "axes"], ["logits"])],
        "bad_rank",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, value)],
        [
            helper.make_tensor_value_info(
                "logits", TensorProto.FLOAT, [None, None, None, None]
            )
        ],
        initializer=[numpy_helper.from_array(axes, "axes")],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


class ArrayReader:
    """Reader seam implementation matching VolumeReader in Python."""

    def __init__(self, array: np.ndarray):
        self.array = array

    @property
    def shape(self):
        return self.array.shape

    def read_voxel_window(self, s0, e0, s1, e1, s2, e2):
        return np.array(self.array[s0:e0, s1:e1, s2:e2], copy=True)


class PreprocessedReader:
    """nodata sentinel -> 0.0, then (v - mean) / std, then mask."""

    def __init__(self, base, mean=None, std=None, nodata=None, mask=None):
        self.base = base
        self.mean = mean
        self.std = std
        self.nodata = nodata
        self.mask = mask
        self.nodata_voxels = 0
        self.seen = np.zeros(base.shape, dtype=bool)

    @property
    def shape(self):
        return self.base.shape

    def read_voxel_window(self, s0, e0, s1, e1, s2, e2):
        block = self.base.read_voxel_window(s0, e0, s1, e1, s2, e2)
        if self.mask is not None or self.nodata is not None:
            mask = (
                self.mask[s0:e0, s1:e1, s2:e2]
                if self.mask is not None
                else None
            )
            invalid = np.zeros(block.shape, dtype=bool)
            if mask is not None:
                invalid |= mask == 0
            if self.nodata is not None:
                invalid |= block == np.float32(self.nodata)
            block = np.where(invalid, np.float32(0.0), block)
        if self.mean is not None:
            block = (block - np.float32(self.mean)) / np.float32(self.std)
        return np.ascontiguousarray(block, dtype=np.float32)


def reference_summary(classmap, probmap, classes, class_names, nodata_voxels,
                      probmap_stored, bins=10):
    """Must match C++ compute_prediction_summary exactly (except mean fp)."""
    counts = [int(np.count_nonzero(classmap == i)) for i in range(classes)]
    out_of_range = int(np.count_nonzero(classmap >= classes))
    conf = probmap.astype(np.float64)
    valid = conf[~np.isnan(conf)]
    histogram = [0] * bins
    for value in valid:
        if value >= 1.0:
            index = bins - 1
        elif value > 0.0:
            index = min(int(value * bins), bins - 1)
        else:
            index = 0
        histogram[index] += 1
    return {
        "summary_version": "pwb-prediction-summary-v1",
        "classes": classes,
        "class_names": list(class_names),
        "voxels_total": int(classmap.size),
        "voxels_nodata": int(nodata_voxels),
        "class_counts": counts,
        "out_of_range_class_count": out_of_range,
        "probmap_stored": bool(probmap_stored),
        "voxels_scored": int(valid.size),
        "nan_confidence_count": int(np.count_nonzero(np.isnan(conf))),
        "mean_confidence": (float(np.mean(valid)) if valid.size else None),
        "min_confidence": (float(np.min(valid)) if valid.size else None),
        "max_confidence": (float(np.max(valid)) if valid.size else None),
        "confidence_histogram": histogram,
        "confidence_histogram_bins": bins,
    }


def run_production(volume, model_path, work_root, classes=CLASSES,
                   tile=TILE, overlap=OVERLAP, batch=1):
    """Calls the REAL production Python tiled inference (real ORT)."""
    import _legacy_reference
    _legacy_reference.ensure_legacy_reference()  # archived-reference shim
    from paleo_workbench.prediction.tiled_onnx import run_tiled_inference
    import zarr

    stats = run_tiled_inference(
        ArrayReader(volume),
        model_path,
        classes=classes,
        work_root=work_root,
        overlap=overlap,
        batch=batch,
        prefer_gpu=False,
        tile=tile,
    )
    classmap = np.array(
        zarr.open(str(stats["class_map"]), mode="r")[:], dtype=np.uint8
    )
    probmap = np.array(
        zarr.open(str(stats["prob_map"]), mode="r")[:], dtype=np.float16
    )
    return stats, classmap, probmap


def run_production_with_reader(reader, model_path, work_root, classes=CLASSES,
                               tile=TILE, overlap=OVERLAP, batch=1):
    from paleo_workbench.prediction.tiled_onnx import run_tiled_inference
    import zarr

    stats = run_tiled_inference(
        reader,
        model_path,
        classes=classes,
        work_root=work_root,
        overlap=overlap,
        batch=batch,
        prefer_gpu=False,
        tile=tile,
    )
    classmap = np.array(
        zarr.open(str(stats["class_map"]), mode="r")[:], dtype=np.uint8
    )
    probmap = np.array(
        zarr.open(str(stats["prob_map"]), mode="r")[:], dtype=np.float16
    )
    return stats, classmap, probmap


def probmap_bits(probmap: np.ndarray) -> list[int]:
    return [int(v) for v in probmap.view(np.uint16).ravel(order="C")]


def rel(path: Path) -> str:
    return path.relative_to(FIXTURE_ROOT).as_posix()


def write_package(
    package_dir: Path,
    model_src: Path,
    manifest_extra: dict,
    metadata: dict,
    *,
    checksum_override: str | None = None,
    artifact_name: str = "model.onnx",
    artifact_relative: str | None = None,
    model_id: str = "test-model",
    provider: str = "onnx_native",
    output_class_names=None,
) -> dict:
    package_dir.mkdir(parents=True, exist_ok=True)
    artifact = package_dir / artifact_name
    if artifact_relative is None:
        shutil.copyfile(model_src, artifact)
        artifact_value = artifact_name
    else:
        artifact_value = artifact_relative
    checksum = checksum_override or sha256_file(model_src)
    manifest = {
        "model_id": model_id,
        "model_version": "1.0.0",
        "model_name": f"{model_id} fixture",
        "capability": "seismic_facies",
        "provider": provider,
        "artifact": artifact_value,
        "checksum": checksum,
        "runtime": "onnxruntime",
        "preprocessing_version": "prediction-runtime-fixture-v1",
        "input_schema": {"bands": metadata.get("input_bands", [])},
        "output_schema": {
            "spatial_output_type": "CLASSIFIED_RASTER",
            "class_names": output_class_names or CLASS_NAMES,
        },
        "metadata": metadata,
        "provenance": {"source": "generate_prediction_runtime_fixtures.py"},
        "deterministic": True,
        "scientific": True,
    }
    manifest.update(manifest_extra)
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    import onnxruntime  # noqa: F401  (fail early when the oracle env is off)

    for directory in (FIXTURE_ROOT / "models", FIXTURE_ROOT / "volumes",
                      FIXTURE_ROOT / "packages"):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True, exist_ok=True)

    models = FIXTURE_ROOT / "models"
    make_conv3d_c3(models / "conv3d_c3.onnx")
    make_conv3d_c2(models / "conv3d_c2.onnx")
    make_conv3d_c3_in2(models / "conv3d_c3_in2.onnx")
    make_identity_c1(models / "identity_c1.onnx")
    make_tie_c1(models / "tie_c1.onnx")
    make_identity_dtype(models / "identity_f16in.onnx",
                        __import__("onnx").TensorProto.FLOAT16)
    make_identity_dtype(models / "identity_f64in.onnx",
                        __import__("onnx").TensorProto.DOUBLE)
    make_bad_rank(models / "bad_rank.onnx")
    (models / "corrupt.onnx").write_bytes(
        (models / "conv3d_c3.onnx").read_bytes()[:64]
    )

    volume = synthetic_volume()
    volume_path = FIXTURE_ROOT / "volumes" / "block_f32.raw"
    volume.tofile(volume_path)
    volume_f16 = volume.astype(np.float16)
    volume_f16_path = FIXTURE_ROOT / "volumes" / "block_f16.raw"
    volume_f16.tofile(volume_f16_path)

    mask = np.ones(VOLUME_SHAPE, dtype=np.uint8)
    mask[0, :, :] = 0
    mask[5, 5, :] = 0
    mask_path = FIXTURE_ROOT / "volumes" / "valid_mask_u8.raw"
    mask.tofile(mask_path)
    nodata_volume = volume.copy()
    nodata_volume[3, 4, 2] = np.float32(NODATA_DECLARED)
    nodata_volume[9, 11, 8] = np.float32(NODATA_DECLARED)
    nodata_volume_path = FIXTURE_ROOT / "volumes" / "block_nodata_f32.raw"
    nodata_volume.tofile(nodata_volume_path)
    # A sentinel that is NOT exactly representable in float32: the comparison
    # must happen in the source dtype, not in double.
    odd_sentinel = -999.1
    odd_volume = volume.copy()
    odd_volume[1, 2, 3] = np.float32(odd_sentinel)
    odd_volume[8, 7, 6] = np.float32(odd_sentinel)
    odd_volume_path = FIXTURE_ROOT / "volumes" / "block_nodata_odd_f32.raw"
    odd_volume.tofile(odd_volume_path)

    baseline_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "tile": list(TILE),
            "overlap": OVERLAP,
            "batch": 2,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "conv3d",
        models / "conv3d_c3.onnx",
        {},
        baseline_metadata,
        model_id="conv3d-c3",
    )
    identity_metadata = {
        "prediction_runtime": {
            "classes": 2,
            "class_names": ["background", "facies"],
            "tile": list(TILE),
            "overlap": 0,
            "batch": 1,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "identity",
        models / "identity_c1.onnx",
        {},
        identity_metadata,
        model_id="identity-c1",
        output_class_names=["background", "facies"],
    )
    tie_metadata = {
        "prediction_runtime": {
            "classes": 2,
            "class_names": ["background", "facies"],
            "tile": list(TILE),
            "overlap": 0,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "tie",
        models / "tie_c1.onnx",
        {},
        tie_metadata,
        model_id="tie-c1",
        output_class_names=["background", "facies"],
    )
    norm_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "normalization": {"mean": 0.5, "std": 2.0},
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "conv3d_norm",
        models / "conv3d_c3.onnx",
        {},
        norm_metadata,
        model_id="conv3d-c3-norm",
    )
    nodata_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "nodata": NODATA_DECLARED,
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "conv3d_nodata",
        models / "conv3d_c3.onnx",
        {},
        nodata_metadata,
        model_id="conv3d-c3-nodata",
    )
    nodata_norm_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "normalization": {"mean": 0.5, "std": 2.0},
            "nodata": NODATA_DECLARED,
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "conv3d_nodata_norm",
        models / "conv3d_c3.onnx",
        {},
        nodata_norm_metadata,
        model_id="conv3d-c3-nodata-norm",
    )
    odd_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "nodata": -999.1,
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "conv3d_nodata_odd",
        models / "conv3d_c3.onnx",
        {},
        odd_metadata,
        model_id="conv3d-c3-nodata-odd",
    )
    # Multi-band declaration: the native single-volume pipeline must refuse.
    multiband_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude", "phase"],
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "multiband",
        models / "conv3d_c3.onnx",
        {},
        multiband_metadata,
        model_id="conv3d-c3-multiband",
    )
    # Missing band: package declares 1 input band, model wants 2 channels.
    missing_band_metadata = {
        "prediction_runtime": {
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "input_bands": ["amplitude"],
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "missing_band",
        models / "conv3d_c3_in2.onnx",
        {},
        missing_band_metadata,
        model_id="conv3d-c3-in2",
    )
    # Class-count mismatch: package declares 3, model outputs 2.
    mismatch_metadata = {
        "prediction_runtime": {
            "classes": 3,
            "class_names": CLASS_NAMES,
            "tile": list(TILE),
            "overlap": OVERLAP,
        }
    }
    write_package(
        FIXTURE_ROOT / "packages" / "class_mismatch",
        models / "conv3d_c2.onnx",
        {},
        mismatch_metadata,
        model_id="conv3d-c2-mismatch",
    )
    # Checksum mismatch.
    write_package(
        FIXTURE_ROOT / "packages" / "bad_checksum",
        models / "conv3d_c3.onnx",
        {},
        baseline_metadata,
        model_id="conv3d-c3-bad-checksum",
        checksum_override="0" * 64,
    )
    # Artifact path escape.
    escape_dir = FIXTURE_ROOT / "packages" / "path_escape"
    write_package(
        escape_dir,
        models / "conv3d_c3.onnx",
        {},
        baseline_metadata,
        model_id="conv3d-c3-escape",
        artifact_relative="../conv3d/model.onnx",
    )
    # Missing artifact.
    write_package(
        FIXTURE_ROOT / "packages" / "missing_artifact",
        models / "conv3d_c3.onnx",
        {"artifact": "does_not_exist.onnx"},
        baseline_metadata,
        model_id="conv3d-c3-missing",
    )
    # Malformed manifest JSON.
    malformed_dir = FIXTURE_ROOT / "packages" / "malformed"
    malformed_dir.mkdir(parents=True, exist_ok=True)
    (malformed_dir / "manifest.json").write_text("{ not json", encoding="utf-8")
    # Corrupt ONNX package.
    write_package(
        FIXTURE_ROOT / "packages" / "corrupt",
        models / "corrupt.onnx",
        {},
        baseline_metadata,
        model_id="corrupt-onnx",
    )
    # Bad-rank model package.
    write_package(
        FIXTURE_ROOT / "packages" / "bad_rank",
        models / "bad_rank.onnx",
        {},
        baseline_metadata,
        model_id="bad-rank",
    )

    input_descriptor = {
        "name": "amplitude",
        "uri": rel(volume_path),
        "shape": list(VOLUME_SHAPE),
        "dtype": "float32",
        "crs": CRS,
        "geotransform": GEOTRANSFORM,
    }

    cases = []

    # 1. Baseline conv3d run (batch 2, overlap 2).
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production(
            volume, FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx",
            Path(tmp) / "work", batch=2,
        )
    cases.append(
        {
            "id": "run_conv3d_baseline",
            "package": "packages/conv3d/manifest.json",
            "input": input_descriptor,
            "options": {
                "classes": CLASSES,
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 2,
                "keep_probmap": True,
                "write_mask": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": int(stats["batch"]),
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, 0, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
            },
        }
    )

    # 2. Identity (single-channel sigmoid expansion, overlap 0).
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production(
            volume, FIXTURE_ROOT / "packages" / "identity" / "model.onnx",
            Path(tmp) / "work", classes=2, overlap=0, batch=1,
            tile=TILE,
        )
    cases.append(
        {
            "id": "run_identity_sigmoid",
            "package": "packages/identity/manifest.json",
            "input": input_descriptor,
            "options": {
                "tile": list(TILE),
                "overlap": 0,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": 2,
                    "overlap": 0,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "identity" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, 2, ["background", "facies"], 0, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
            },
        }
    )

    # 3. Class ties (constant 0.5 -> class 0, prob 0.5).
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production(
            volume, FIXTURE_ROOT / "packages" / "tie" / "model.onnx",
            Path(tmp) / "work", classes=2, overlap=0,
        )
    cases.append(
        {
            "id": "run_class_ties",
            "package": "packages/tie/manifest.json",
            "input": input_descriptor,
            "options": {
                "tile": list(TILE),
                "overlap": 0,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": 2,
                    "overlap": 0,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "tie" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, 2, ["background", "facies"], 0, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "all_class_zero": True,
                "all_probability_half": True,
            },
        }
    )

    # 4. Normalization declared by the package.
    reader = PreprocessedReader(
        ArrayReader(volume), mean=0.5, std=2.0
    )
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production_with_reader(
            reader, FIXTURE_ROOT / "packages" / "conv3d_norm" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    cases.append(
        {
            "id": "run_normalization",
            "package": "packages/conv3d_norm/manifest.json",
            "input": input_descriptor,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d_norm" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, 0, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
            },
        }
    )

    # 5. Nodata + quality mask.
    nodata_mask = mask.copy()
    reader = PreprocessedReader(
        ArrayReader(nodata_volume),
        nodata=NODATA_DECLARED,
        mask=nodata_mask,
    )
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production_with_reader(
            reader,
            FIXTURE_ROOT / "packages" / "conv3d_nodata" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    invalid_count = int(
        np.count_nonzero(nodata_mask == 0)
        + np.count_nonzero(
            (nodata_mask != 0) & (nodata_volume == np.float32(NODATA_DECLARED))
        )
    )
    nodata_input = dict(input_descriptor)
    nodata_input["uri"] = rel(nodata_volume_path)
    nodata_input["nodata"] = NODATA_DECLARED
    nodata_input["quality_mask_uri"] = rel(mask_path)
    cases.append(
        {
            "id": "run_nodata_mask",
            "package": "packages/conv3d_nodata/manifest.json",
            "input": nodata_input,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_mask": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d_nodata" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, invalid_count, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "invalid_voxels": invalid_count,
            },
        }
    )

    # 5a. Nodata declared by the package only (the descriptor omits the
    # sentinel): the runtime must fall back to the package declaration.
    nodata_fallback_input = dict(input_descriptor)
    nodata_fallback_input["uri"] = rel(nodata_volume_path)
    nodata_fallback_reader = PreprocessedReader(
        ArrayReader(nodata_volume), nodata=NODATA_DECLARED
    )
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production_with_reader(
            nodata_fallback_reader,
            FIXTURE_ROOT / "packages" / "conv3d_nodata" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    nodata_fallback_invalid = int(
        np.count_nonzero(nodata_volume == np.float32(NODATA_DECLARED))
    )
    cases.append(
        {
            "id": "run_nodata_package_fallback",
            "package": "packages/conv3d_nodata/manifest.json",
            "input": nodata_fallback_input,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d_nodata" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES,
                    nodata_fallback_invalid, True,
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "invalid_voxels": nodata_fallback_invalid,
            },
        }
    )

    # 5b. Nodata + package normalization: replacement happens first, then the
    # transform (the ordering the native reader implements).
    nodata_norm_input = dict(input_descriptor)
    nodata_norm_input["uri"] = rel(nodata_volume_path)
    nodata_norm_input["nodata"] = NODATA_DECLARED
    nodata_norm_reader = PreprocessedReader(
        ArrayReader(nodata_volume), mean=0.5, std=2.0,
        nodata=NODATA_DECLARED,
    )
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production_with_reader(
            nodata_norm_reader,
            FIXTURE_ROOT / "packages" / "conv3d_nodata_norm" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    nodata_norm_invalid = int(
        np.count_nonzero(nodata_volume == np.float32(NODATA_DECLARED))
    )
    cases.append(
        {
            "id": "run_nodata_normalization",
            "package": "packages/conv3d_nodata_norm/manifest.json",
            "input": nodata_norm_input,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT
                    / "packages"
                    / "conv3d_nodata_norm"
                    / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES,
                    nodata_norm_invalid, True,
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "invalid_voxels": nodata_norm_invalid,
            },
        }
    )

    # 5c. A nodata sentinel that is not exactly representable in float32.
    odd_input = dict(input_descriptor)
    odd_input["uri"] = rel(odd_volume_path)
    odd_input["nodata"] = -999.1
    odd_reader = PreprocessedReader(ArrayReader(odd_volume), nodata=-999.1)
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production_with_reader(
            odd_reader,
            FIXTURE_ROOT / "packages" / "conv3d_nodata_odd" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    odd_invalid = int(
        np.count_nonzero(odd_volume == np.float32(-999.1))
    )
    cases.append(
        {
            "id": "run_nodata_odd_sentinel",
            "package": "packages/conv3d_nodata_odd/manifest.json",
            "input": odd_input,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT
                    / "packages"
                    / "conv3d_nodata_odd"
                    / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, odd_invalid, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "invalid_voxels": odd_invalid,
            },
        }
    )

    # 5d. keep_probmap=false: the probability map is still fused for the
    # summary but is not persisted (probmap_stored=false, no artifact).
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production(
            volume, FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    cases.append(
        {
            "id": "run_keep_probmap_false",
            "package": "packages/conv3d/manifest.json",
            "input": input_descriptor,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": False,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, 0, False
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
                "probmap_absent": True,
            },
        }
    )

    # 6. Float16 source conversion.
    with tempfile.TemporaryDirectory() as tmp:
        stats, classmap, probmap = run_production(
            volume_f16.astype(np.float32),
            FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx",
            Path(tmp) / "work", batch=1,
        )
    f16_input = dict(input_descriptor)
    f16_input["uri"] = rel(volume_f16_path)
    f16_input["dtype"] = "float16"
    cases.append(
        {
            "id": "run_float16_source",
            "package": "packages/conv3d/manifest.json",
            "input": f16_input,
            "options": {
                "tile": list(TILE),
                "overlap": OVERLAP,
                "batch": 1,
                "keep_probmap": True,
                "write_outputs": True,
            },
            "expect": {
                "stats": {
                    "tiles_total": int(stats["tiles_total"]),
                    "tiles_done": int(stats["tiles_done"]),
                    "cancelled": False,
                    "classes": CLASSES,
                    "overlap": OVERLAP,
                    "batch": 1,
                    "device_mode": "cpu",
                },
                "model_sha256": sha256_file(
                    FIXTURE_ROOT / "packages" / "conv3d" / "model.onnx"
                ),
                "summary": reference_summary(
                    classmap, probmap, CLASSES, CLASS_NAMES, 0, True
                ),
                "classmap": [int(v) for v in classmap.ravel(order="C")],
                "probmap_bits": probmap_bits(probmap),
                "spatial_type": "CLASSIFIED_RASTER",
                "validate_errors": [],
                "band_name": "amplitude",
            },
        }
    )

    # 7. Error cases (the C++ contract; Python has no equivalent runtime).
    error_cases = [
        {
            "id": "error_checksum_mismatch",
            "package": "packages/bad_checksum/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "checksum mismatch",
            },
        },
        {
            "id": "error_path_escape",
            "package": "packages/path_escape/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "escapes the model package root",
            },
        },
        {
            "id": "error_missing_artifact",
            "package": "packages/missing_artifact/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "artifact file missing",
            },
        },
        {
            "id": "error_malformed_manifest",
            "package": "packages/malformed/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "Invalid manifest JSON",
            },
        },
        {
            "id": "error_corrupt_onnx",
            "package": "packages/corrupt/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "TiledInferenceError",
                "message_contains": "onnxruntime",
            },
        },
        {
            "id": "error_class_count_mismatch",
            "package": "packages/class_mismatch/manifest.json",
            "input": input_descriptor,
            "options": {"classes": 3, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "does not match the package's declared",
            },
        },
        {
            "id": "error_run_classes_override_mismatch",
            "package": "packages/conv3d/manifest.json",
            "input": input_descriptor,
            "options": {"classes": 4, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "run declares classes=4",
            },
        },
        {
            "id": "error_multiband_input",
            "package": "packages/multiband/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "single seismic volume",
            },
        },
        {
            "id": "error_output_crs_missing",
            "package": "packages/conv3d/manifest.json",
            "input": {**input_descriptor, "crs": ""},
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "spatial contract",
            },
        },
        {
            "id": "error_missing_band",
            "package": "packages/missing_band/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "declared input bands",
            },
        },
        {
            "id": "error_dtype_mismatch",
            "package": "packages/conv3d/manifest.json",
            "input": {
                **input_descriptor,
                "dtype": "int32",
            },
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "not supported by the native prediction",
            },
        },
        {
            "id": "error_missing_volume",
            "package": "packages/conv3d/manifest.json",
            "input": {
                **input_descriptor,
                "uri": "volumes/does_not_exist.raw",
            },
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "input volume not found",
            },
        },
        {
            "id": "error_shape_size_mismatch",
            "package": "packages/conv3d/manifest.json",
            "input": {
                **input_descriptor,
                "shape": [10, 12, 8],
            },
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "bytes but shape",
            },
        },
        {
            "id": "error_mask_size_mismatch",
            "package": "packages/conv3d_nodata/manifest.json",
            "input": {
                **input_descriptor,
                "quality_mask_uri": "volumes/block_f16.raw",
            },
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "InputContractError",
                "message_contains": "quality mask",
            },
        },
        {
            "id": "error_batch_negative",
            "package": "packages/conv3d/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "batch": -3,
                        "write_outputs": False},
            "expect": {
                "raises": "ValueError",
                "message_contains": "batch must be >= 1",
            },
        },
        {
            "id": "error_output_budget",
            "package": "packages/conv3d/manifest.json",
            "input": input_descriptor,
            "options": {
                "classes": CLASSES,
                "output_budget_bytes": 1024,
                "write_outputs": False,
            },
            "expect": {
                "raises": "InputContractError",
                "message_contains": "above the configured limit",
            },
        },
        {
            "id": "error_bad_rank_output",
            "package": "packages/bad_rank/manifest.json",
            "input": input_descriptor,
            "options": {"classes": CLASSES, "write_outputs": False},
            "expect": {
                "raises": "ModelPackageError",
                "message_contains": "model output rank=4",
            },
        },
    ]

    # Self-check: the fixture envelope shape passes the Python spatial
    # validator (the same contract the C++ envelope must satisfy).
    try:
        from paleo_workbench.prediction.spatial_result import (
            validate_spatial_result,
        )

        envelope = {
            "spatial_output_type": "CLASSIFIED_RASTER",
            "crs": CRS,
            "geotransform": GEOTRANSFORM,
            "grid": {"shape": list(VOLUME_SHAPE), "classes": CLASSES},
            "artifact_path": "classmap.raw",
            "result_summary": {
                "spatial": {
                    "spatial_output_type": "CLASSIFIED_RASTER",
                    "grid": {"shape": list(VOLUME_SHAPE), "classes": CLASSES},
                    "crs": CRS,
                    "geotransform": GEOTRANSFORM,
                    "artifact_path": "classmap.raw",
                }
            },
        }
        errors = validate_spatial_result(envelope)
        if errors:
            raise SystemExit(f"spatial envelope self-check failed: {errors}")
    except ImportError as exc:  # pydantic chain unavailable -> skip loudly
        print(f"spatial validator self-check skipped: {exc}", file=sys.stderr)

    oracle = {
        "meta": {
            "generator": "tools/oracle/generate_prediction_runtime_fixtures.py",
            "numpy": np.__version__,
            "onnxruntime": __import__("onnxruntime").__version__,
            "onnx": __import__("onnx").__version__,
            "volume_shape": list(VOLUME_SHAPE),
            "tile": list(TILE),
            "overlap": OVERLAP,
            "classes": CLASSES,
            "class_names": CLASS_NAMES,
            "crs": CRS,
            "geotransform": GEOTRANSFORM,
            "cases": len(cases) + len(error_cases),
            "runs": len(cases),
            "error_cases": len(error_cases),
            "error_count_note": (
                "success cases replay full classmap/probmap/summary; error "
                "cases assert the C++ error class + message fragment"
            ),
        },
        "cases": cases,
        "error_cases": error_cases,
    }
    ORACLE_PATH.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {ORACLE_PATH} ({len(cases)} runs, "
        f"{len(error_cases)} error cases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
