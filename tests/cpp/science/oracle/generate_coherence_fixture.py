"""Generate the frozen coherence_c3 oracle fixtures.

Runs the pinned Python implementation (geo-viz-engine@08851951,
geoviz_seismic.attributes.compute_coherence_c3, numpy path) over synthetic
volumes and the real tiny.sgy fixture and writes input/expected payloads that
the C++ test (coherence_c3_oracle_test.cpp) compares against.

Deterministic: PCG64 with fixed seeds, float32 everywhere. Re-running with the
same submodule version regenerates byte-identical payloads.

Usage (read-only interpreter from the main repo):
    ../paleo-workbench/.venv/Scripts/python.exe tests/cpp/science/oracle/generate_coherence_fixture.py \
        --out tests/cpp/science/fixtures/coherence_c3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]  # worktree root
GEOVIZ_PACKAGES = REPO_ROOT / "geo-viz-engine" / "packages"
sys.path.insert(0, str(GEOVIZ_PACKAGES))

from geoviz_seismic.attributes import compute_coherence_c3  # noqa: E402

TINY_SGY = REPO_ROOT / "tests" / "fixtures" / "realdata" / "tiny.sgy"


def synth_volume(seed: int, shape: tuple[int, int, int]) -> np.ndarray:
    """Sine-composite + seeded noise wedge volume (float32, C-order)."""
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


def write_case(out_dir: Path, name: str, volume: np.ndarray, params: dict) -> None:
    expected = compute_coherence_c3(
        volume,
        win_il=params["win_il"],
        win_xl=params["win_xl"],
        win_t=params["win_t"],
        use_gpu=False,
    ).astype(np.float32, copy=False)
    case_dir = out_dir / name
    case_dir.mkdir(parents=True, exist_ok=True)
    volume.tofile(case_dir / "input.f32")
    expected.tofile(case_dir / "expected.f32")
    finite = expected[np.isfinite(expected)]
    stats = {
        "elements": int(expected.size),
        "min": float(finite.min()) if finite.size else 0.0,
        "max": float(finite.max()) if finite.size else 0.0,
        "mean": float(finite.mean()) if finite.size else 0.0,
        "sha256_expected": hashlib.sha256(
            np.ascontiguousarray(expected).tobytes()
        ).hexdigest(),
    }
    (case_dir / "stats.json").write_text(
        json.dumps({**stats, "params": params}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (case_dir / "manifest.json").write_text(
        json.dumps(
            {
                "case": name,
                "shape": list(volume.shape),
                **params,
                "tolerance_max_abs": 2e-3,
                "oracle": "geoviz_seismic.attributes.compute_coherence_c3@08851951",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{name}: shape={volume.shape} params={params} stats={stats}")


def load_tiny_sgy() -> np.ndarray:
    """Read the real 8x8x32 tiny.sgy fixture through the geoviz loader."""
    sys.path.insert(0, str(GEOVIZ_PACKAGES))
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_case(
        out_dir,
        "synth_default",
        synth_volume(20260916, (24, 20, 40)),
        {"win_il": 5, "win_xl": 5, "win_t": 5},
    )
    write_case(
        out_dir,
        "synth_asym_window",
        synth_volume(20260916, (24, 20, 40)),
        {"win_il": 3, "win_xl": 7, "win_t": 2},
    )
    write_case(
        out_dir,
        "synth_small_dims",
        synth_volume(777, (4, 3, 9)),
        {"win_il": 5, "win_xl": 5, "win_t": 5},
    )
    write_case(
        out_dir,
        "synth_constant",
        np.full((8, 8, 16), 2.5, dtype=np.float32),
        {"win_il": 3, "win_xl": 3, "win_t": 3},
    )

    nan_volume = synth_volume(888, (8, 8, 16))
    nan_volume[3:5, 3:5, 3:5] = np.nan  # NaN block exercises the 1.0 path
    write_case(out_dir, "synth_nan_region", nan_volume, {"win_il": 2, "win_xl": 2, "win_t": 2})

    tiny = load_tiny_sgy()
    write_case(out_dir, "tiny_sgy_real_w3", tiny, {"win_il": 3, "win_xl": 3, "win_t": 3})
    write_case(out_dir, "tiny_sgy_real_w1x1x5", tiny, {"win_il": 1, "win_xl": 1, "win_t": 5})

    print(f"fixtures written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
