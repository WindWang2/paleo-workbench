"""Tests for the synthetic SEG-Y benchmark volume generator (#1067/#1069)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GEN_PATH = _REPO_ROOT / "benchmarks" / "generate_synthetic_segy.py"
_spec = importlib.util.spec_from_file_location("generate_synthetic_segy", _GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("generate_synthetic_segy", gen)
_spec.loader.exec_module(gen)

segyio = pytest.importorskip("segyio")


@pytest.fixture(scope="module")
def tiny_volume(tmp_path_factory) -> tuple:
    spec = gen.PRESETS["tiny"]
    path = tmp_path_factory.mktemp("tiny") / "tiny.segy"
    gen.generate_volume(spec, path, progress=False)
    return spec, path


def test_file_size_matches_trace_math(tiny_volume):
    spec, path = tiny_volume
    assert path.stat().st_size == spec.file_bytes


def test_segyio_geometry_and_headers(tiny_volume):
    spec, path = tiny_volume
    with segyio.open(path, "r", ignore_geometry=False) as f:
        assert f.tracecount == spec.nil * spec.nxl
        assert list(f.ilines) == list(range(1, spec.nil + 1))
        assert list(f.xlines) == list(range(1, spec.nxl + 1))
        assert len(f.samples) == spec.nt
        assert f.samples[1] - f.samples[0] == pytest.approx(2.0)  # dt = 2 ms
        hdr = f.header[0]
        assert int(hdr[segyio.TraceField.INLINE_3D]) == 1
        assert int(hdr[segyio.TraceField.CROSSLINE_3D]) == 1
        mid = f.header[spec.nxl * (spec.nil // 2) + spec.nxl // 2]
        assert int(mid[segyio.TraceField.INLINE_3D]) == spec.nil // 2 + 1
        assert int(mid[segyio.TraceField.CROSSLINE_3D]) == spec.nxl // 2 + 1
        assert not np.allclose(f.iline[1], 0.0)


def test_determinism_same_seed_same_bytes(tmp_path):
    spec = gen.PRESETS["tiny"]
    a, b = tmp_path / "a.segy", tmp_path / "b.segy"
    gen.generate_volume(spec, a, progress=False)
    gen.generate_volume(spec, b, progress=False)
    assert gen.sha256_of(a) == gen.sha256_of(b)
    # A different seed must change the data.
    gen.generate_volume(gen.VolumeSpec(spec.nil, spec.nxl, spec.nt, seed=spec.seed + 1), b, progress=False)
    assert gen.sha256_of(a) != gen.sha256_of(b)


def test_verify_volume_passes_on_fresh_file(tiny_volume, tmp_path):
    spec, _ = tiny_volume
    path = tmp_path / "tiny_copy.segy"
    gen.generate_volume(spec, path, progress=False)
    facts = gen.verify_volume(spec, path)
    assert facts["tracecount"] == spec.nil * spec.nxl


def test_loader_geometry_detection_accepts_file(tiny_volume):
    """The production loader must grid this file via INLINE/CROSSLINE headers."""
    loader = pytest.importorskip("geoviz_seismic.loader")
    spec, path = tiny_volume
    with segyio.open(path, "r", ignore_geometry=True) as f:
        fields = loader.detect_iline_xline_fields(f)
    assert fields is not None, "loader failed to detect inline/crossline grid"
    # segyio TraceField byte positions (1-based): INLINE_3D=189, CROSSLINE_3D=193.
    assert set(fields) == {189, 193}
