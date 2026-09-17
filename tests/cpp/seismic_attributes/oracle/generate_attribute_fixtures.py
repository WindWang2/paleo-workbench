"""Generate the frozen seismic-attribute oracle fixtures (E line).

Runs the pinned Python oracle (geo-viz-engine@08851951,
geoviz_seismic.attributes: compute_envelope / compute_instantaneous_phase /
compute_instantaneous_frequency / compute_rms_amplitude) over synthetic
volumes and the real tiny.sgy fixture and writes input + expected payloads
that the C++ tests (attribute_kernels_test.cpp etc.) compare against.

Deterministic: PCG64 with fixed seeds, float32 payloads. Re-running with the
same submodule gitlink and interpreter regenerates byte-identical files.

Before writing, the generator self-checks analytic invariants (integer-cycle
cosine, constants, zeros) so a misuse of the oracle cannot freeze wrong
expectations.

Usage (pinned interpreter, read-only):
    /opt/miniconda3/bin/python3.13 tests/cpp/seismic_attributes/oracle/generate_attribute_fixtures.py \
        --out tests/cpp/seismic_attributes/fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import scipy

REPO_ROOT = Path(__file__).resolve().parents[4]  # worktree root
GEOVIZ_PACKAGES = REPO_ROOT / "geo-viz-engine" / "packages"
sys.path.insert(0, str(GEOVIZ_PACKAGES))

from geoviz_seismic import attribute_pipeline  # noqa: E402
from geoviz_seismic.attributes import (  # noqa: E402
    compute_envelope,
    compute_instantaneous_frequency,
    compute_instantaneous_phase,
    compute_rms_amplitude,
)

TINY_SGY = REPO_ROOT / "tests" / "fixtures" / "realdata" / "tiny.sgy"

# Frozen tolerances (v3-contracts.md §4) — decided before any C++ run.
TOLERANCES = {
    "envelope": {"max_abs": 1e-5, "max_rel": 1e-4},
    "phase": {"max_abs": 1e-4},
    "freq": {"max_abs": 5e-3, "max_rel": 1e-2},
    "rms": {"max_abs": 1e-6, "max_rel": 1e-5},
}

INTERPRETER = {
    "python": sys.version.split()[0],
    "numpy": np.__version__,
    "scipy": scipy.__version__,
    "executable": sys.executable,
}

ORACLE = {
    "gitlink": "geo-viz-engine@08851951f3bbc0beb90886adf52e1928f4383c16",
    "module": "geoviz_seismic.attributes",
    "functions": [
        "compute_envelope",
        "compute_instantaneous_phase",
        "compute_instantaneous_frequency",
        "compute_rms_amplitude",
    ],
}


def synth_volume(seed: int, shape: tuple[int, int, int]) -> np.ndarray:
    """Sine-composite + seeded noise volume (float32, C-order, time last)."""
    rng = np.random.Generator(np.random.PCG64(seed))
    ni, nx, nt = shape
    i = np.arange(ni, dtype=np.float32)[:, None, None]
    j = np.arange(nx, dtype=np.float32)[None, :, None]
    t = np.arange(nt, dtype=np.float32)[None, None, :]
    base = (
        np.sin(0.31 * i + 0.05 * t)
        + 0.5 * np.cos(0.47 * j - 0.11 * t)
        + 0.25 * np.sin(0.13 * (i + j) + 0.29 * t)
    )
    return (base + rng.normal(0.0, 0.15, size=shape)).astype(np.float32)


def load_tiny_sgy() -> np.ndarray:
    """Read the real 8x8x32 tiny.sgy fixture through the geoviz loader."""
    from geoviz_seismic.loader import SeismicLoader

    loader = SeismicLoader(str(TINY_SGY))
    meta = loader.inspect()
    ilines = [meta.iline_start + i * meta.iline_step for i in range(meta.n_inlines)]
    volume = np.stack(
        [np.asarray(loader.read_inline(il), dtype=np.float32) for il in ilines]
    )
    assert volume.shape == (meta.n_inlines, meta.n_crosslines, meta.n_samples), (
        volume.shape,
        meta,
    )
    return np.ascontiguousarray(volume, dtype=np.float32)


def sha256(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def payload_stats(array: np.ndarray) -> dict:
    finite = array[np.isfinite(array)]
    return {
        "elements": int(array.size),
        "n_nan": int(np.count_nonzero(np.isnan(array))),
        "n_inf": int(np.count_nonzero(np.isinf(array))),
        "min": float(finite.min()) if finite.size else 0.0,
        "max": float(finite.max()) if finite.size else 0.0,
        "mean": float(finite.mean()) if finite.size else 0.0,
    }


def write_case(out_dir: Path, name: str, volume: np.ndarray,
               expected: dict[str, tuple[np.ndarray, dict]]) -> None:
    """`expected` maps filename -> (array, meta) with meta carrying params."""
    case_dir = out_dir / name
    case_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    volume.tofile(case_dir / "input.f32")
    files["input.f32"] = {"sha256": sha256(volume), **payload_stats(volume)}
    for filename, (array, meta) in expected.items():
        array.tofile(case_dir / filename)
        files[filename] = {"sha256": sha256(array), **payload_stats(array), **meta}
    manifest = {
        "case": name,
        "shape": list(volume.shape),
        "dtype": "float32",
        "order": "C (inline, crossline, sample); sample axis = time",
        "tolerances": TOLERANCES,
        "files": files,
    }
    (case_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{name}: shape={volume.shape} files={sorted(expected)}")


def attrs_all(volume: np.ndarray, dt: float = 1.0, rms_windows=(21,)) -> dict:
    out = {
        "expected_envelope.f32": (compute_envelope(volume, axis=-1), {"algorithm": "envelope"}),
        "expected_phase.f32": (
            compute_instantaneous_phase(volume, axis=-1), {"algorithm": "phase"}),
        "expected_freq.f32": (
            compute_instantaneous_frequency(volume, dt, axis=-1),
            {"algorithm": "freq", "sample_interval": dt, "unit": "Hz"}),
    }
    for w in rms_windows:
        out[f"expected_rms_w{w}.f32"] = (
            compute_rms_amplitude(volume, w, axis=-1),
            {"algorithm": "rms", "window": w, "total_window": 2 * w + 1})
    return out


def self_check() -> None:
    """Analytic invariants — refuse to freeze a misused oracle."""
    # Integer-cycle cosine: exactly bin-centered FFT -> exact analytic signal.
    n = 256
    t = np.arange(n, dtype=np.float64) / n
    amp, freq_hz = 0.8, 30.0
    sig = (amp * np.cos(2 * np.pi * freq_hz * t)).astype(np.float32)[None, None, :]
    env = compute_envelope(sig, axis=-1)
    assert np.max(np.abs(env - amp)) < 1e-6, ("sine envelope", env.min(), env.max())
    fr = compute_instantaneous_frequency(sig, 1.0 / n, axis=-1)
    core = fr[0, 0, 2:-2]
    assert np.max(np.abs(core - freq_hz)) < 1e-3, ("sine frequency", core.min(), core.max())
    # Constants: env=|c|, freq=0, rms=|c|. The float32 oracle phase chain
    # (angle -> unwrap cumsum in float32) leaves ~2e-5 Hz noise on constant
    # negative traces (measured), so the frequency invariant is checked to
    # 1e-3, far inside the frozen 5e-3 abs tolerance; envelope/rms are exact.
    for c in (2.5, -2.5):
        vol = np.full((1, 1, 8), c, dtype=np.float32)
        assert np.max(np.abs(compute_envelope(vol, axis=-1) - abs(c))) < 1e-6
        f = compute_instantaneous_frequency(vol, 0.002, axis=-1)
        assert np.max(np.abs(f)) < 1e-3, ("const freq", f)
        assert np.max(np.abs(compute_rms_amplitude(vol, 21, axis=-1) - abs(c))) < 1e-6
    # Zeros.
    z = np.zeros((1, 1, 8), dtype=np.float32)
    assert np.all(compute_envelope(z, axis=-1) == 0.0)
    # Provider axis equivalence: axis=0 on (n_t, n_traces) == axis=-1 on
    # (n_traces, n_t) per trace (attribute_pipeline convention).
    vol2d = synth_volume(1, (1, 6, 11))[0]  # (xl, t)
    provider = attribute_pipeline.apply(1, np.ascontiguousarray(vol2d.T), 1.0)  # envelope, axis=0
    direct = compute_envelope(vol2d, axis=-1)
    assert np.allclose(provider.T, direct, atol=1e-7), "provider axis mismatch"
    print("self-check: analytic invariants + provider axis equivalence OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    self_check()

    # Coverage: even 2^6 / odd non-2-power / prime / shortest lengths /
    # degenerate constants / impulse / integer-cycle sine / NaN+Inf / real.
    write_case(out_dir, "synth_mixed", synth_volume(20260917, (24, 20, 64)),
               attrs_all(synth_volume(20260917, (24, 20, 64)), dt=0.002,
                         rms_windows=(0, 1, 21, 100)))
    odd = synth_volume(20260918, (13, 17, 45))
    write_case(out_dir, "synth_odd", odd,
               {**attrs_all(odd, dt=1.0, rms_windows=(3,)),
                **{}} )
    prime = synth_volume(20260919, (6, 5, 31))
    write_case(out_dir, "synth_prime31", prime,
               {"expected_envelope.f32": (compute_envelope(prime, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(prime, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(prime, 0.002, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 0.002, "unit": "Hz"})})
    nt2 = synth_volume(20260921, (4, 3, 2))
    write_case(out_dir, "synth_nt2", nt2,
               {"expected_envelope.f32": (compute_envelope(nt2, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(nt2, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(nt2, 1.0, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 1.0, "unit": "Hz"}),
                "expected_rms_w1.f32": (compute_rms_amplitude(nt2, 1, axis=-1),
                                        {"algorithm": "rms", "window": 1, "total_window": 3})})
    nt1 = synth_volume(20260922, (4, 3, 1))
    write_case(out_dir, "synth_nt1", nt1,
               {"expected_envelope.f32": (compute_envelope(nt1, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(nt1, axis=-1), {"algorithm": "phase"}),
                "expected_rms_w0.f32": (compute_rms_amplitude(nt1, 0, axis=-1),
                                        {"algorithm": "rms", "window": 0, "total_window": 1}),
                "expected_rms_w2.f32": (compute_rms_amplitude(nt1, 2, axis=-1),
                                        {"algorithm": "rms", "window": 2, "total_window": 5})})

    zeros = np.zeros((5, 5, 8), dtype=np.float32)
    write_case(out_dir, "zeros", zeros, attrs_all(zeros, dt=1.0, rms_windows=(21,)))
    const_pos = np.full((5, 5, 8), 2.5, dtype=np.float32)
    write_case(out_dir, "constant_pos", const_pos, attrs_all(const_pos, dt=0.002, rms_windows=(21,)))
    const_neg = np.full((5, 5, 8), -2.5, dtype=np.float32)
    write_case(out_dir, "constant_neg", const_neg,
               {"expected_envelope.f32": (compute_envelope(const_neg, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(const_neg, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(const_neg, 0.002, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 0.002, "unit": "Hz",
                                       "note": "float32 phase chain leaves ~2e-5 Hz tail noise on "
                                               "constant negative traces; C++ double path returns 0"}),
                "expected_rms_w21.f32": (compute_rms_amplitude(const_neg, 21, axis=-1),
                                         {"algorithm": "rms", "window": 21, "total_window": 43})})

    impulse = np.zeros((8, 8, 32), dtype=np.float32)
    impulse[2, 3, 16] = 1.0
    impulse[5, 5, 5] = -0.5
    impulse[0, 0, 31] = 0.25
    write_case(out_dir, "impulse", impulse,
               {"expected_envelope.f32": (compute_envelope(impulse, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(impulse, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(impulse, 0.002, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 0.002, "unit": "Hz"}),
                "expected_rms_w2.f32": (compute_rms_amplitude(impulse, 2, axis=-1),
                                        {"algorithm": "rms", "window": 2, "total_window": 5})})

    n = 256
    t = np.arange(n, dtype=np.float32) / n
    sine = (0.8 * np.cos(2 * np.pi * 30.0 * t)).astype(np.float32)
    sine_vol = np.broadcast_to(sine[None, None, :], (4, 4, n)).copy()
    write_case(out_dir, "sine_30hz", sine_vol,
               {"expected_envelope.f32": (compute_envelope(sine_vol, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(sine_vol, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(sine_vol, 1.0 / n, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 1.0 / n, "unit": "Hz"}),
                "expected_rms_w10.f32": (compute_rms_amplitude(sine_vol, 10, axis=-1),
                                         {"algorithm": "rms", "window": 10, "total_window": 21})})

    nan_vol = synth_volume(20260920, (8, 8, 16))
    nan_vol[3:5, 3:5, 3:5] = np.nan
    nan_vol[6, 6, 10] = np.inf
    write_case(out_dir, "nan_inf", nan_vol,
               {"expected_envelope.f32": (compute_envelope(nan_vol, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(nan_vol, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(nan_vol, 0.002, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 0.002, "unit": "Hz"}),
                "expected_rms_w2.f32": (compute_rms_amplitude(nan_vol, 2, axis=-1),
                                        {"algorithm": "rms", "window": 2, "total_window": 5})})

    tiny = load_tiny_sgy()
    write_case(out_dir, "tiny_sgy_real", tiny,
               {"expected_envelope.f32": (compute_envelope(tiny, axis=-1), {"algorithm": "envelope"}),
                "expected_phase.f32": (compute_instantaneous_phase(tiny, axis=-1), {"algorithm": "phase"}),
                "expected_freq.f32": (compute_instantaneous_frequency(tiny, 0.002, axis=-1),
                                      {"algorithm": "freq", "sample_interval": 0.002, "unit": "Hz",
                                       "note": "tiny.sgy dt=2.0 ms -> 0.002 s, output Hz"}),
                "expected_rms_w21.f32": (compute_rms_amplitude(tiny, 21, axis=-1),
                                         {"algorithm": "rms", "window": 21, "total_window": 43}),
                "expected_rms_w0.f32": (compute_rms_amplitude(tiny, 0, axis=-1),
                                        {"algorithm": "rms", "window": 0, "total_window": 1}),
                "expected_rms_w100.f32": (compute_rms_amplitude(tiny, 100, axis=-1),
                                          {"algorithm": "rms", "window": 100, "total_window": 201,
                                           "note": "total window > n_t folds via symmetric padding"})})

    top = {
        "oracle": ORACLE,
        "interpreter": INTERPRETER,
        "cases": sorted(p.name for p in out_dir.iterdir() if p.is_dir()),
        "tolerances": TOLERANCES,
        "comparison_rules": {
            "envelope": "max_abs + max_rel over all elements; NaN masks must match elementwise",
            "phase": "circular difference wrapped to [-pi, pi]; NaN masks must match",
            "freq": "max_abs + max_rel over finite elements; NaN masks must match",
            "rms": "max_abs + max_rel over all elements; NaN masks must match elementwise",
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(top, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"fixtures written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
