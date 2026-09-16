"""Generate the frozen seismic slice fixtures from the real tiny.sgy file.

Produces:
  * volume_xl_major.f32 — the 8x8x32 tiny.sgy volume stored CROSSLINE-major
    (permuted, asymmetric strides) so the C++ slicing must honor strides;
  * expected_inline/crossline/sample planes (byte-exact float32);
  * expected_inline_indexed8.f32 — uint8 bytes stored as a .f32 payload,
    produced with the frozen _py_fast_slice_to_indexed8 semantics
    (paleo_workbench/native_backend.py): finite-only stretch, truncation
    toward zero, NaN -> 0.

Usage:
    ../paleo-workbench/.venv/Scripts/python.exe tests/cpp/science/oracle/generate_seismic_fixture.py \
        --out tests/cpp/science/fixtures/seismic/tiny_sgy
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]  # worktree root
GEOVIZ_PACKAGES = REPO_ROOT / "geo-viz-engine" / "packages"
sys.path.insert(0, str(GEOVIZ_PACKAGES))
sys.path.insert(0, str(REPO_ROOT))  # paleo_workbench package import root

import geoviz_seismic  # noqa: E402

# The venv may resolve geoviz from its editable install (main-repo submodule).
# Both copies are pinned to the same gitlink; abort if that ever diverges.
_pkg_root = Path(geoviz_seismic.__file__).resolve()
for _candidate in (_pkg_root.parents):
    if (_candidate / ".git").exists() or (_candidate / ".." / ".git").exists():
        _sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_candidate), capture_output=True, text=True
        ).stdout.strip()
        assert _sha == "08851951f3bbc0beb90886adf52e1928f4383c16", (
            f"oracle geoviz copy at {_candidate} is {_sha}, expected 08851951"
        )
        break

from geoviz_seismic.loader import SeismicLoader  # noqa: E402

from paleo_workbench.native_backend import _py_fast_slice_to_indexed8  # noqa: E402

TINY_SGY = REPO_ROOT / "tests" / "fixtures" / "realdata" / "tiny.sgy"


def read_volume(loader, meta) -> np.ndarray:
    """Read (n_il, n_xl, n_t) via physical iline VALUES (1-based here)."""
    ilines = [
        meta.iline_start + i * meta.iline_step for i in range(meta.n_inlines)
    ]
    return np.stack(
        [np.asarray(loader.read_inline(il), dtype=np.float32) for il in ilines]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    loader = SeismicLoader(str(TINY_SGY))
    meta = loader.inspect()
    volume = read_volume(loader, meta)
    assert volume.shape == (meta.n_inlines, meta.n_crosslines, meta.n_samples)

    # Crossline-major storage: axis strides in elements are
    # (n_t, n_il * n_t, 1) over a (n_xl, n_il, n_t) buffer.
    xl_major = np.ascontiguousarray(np.transpose(volume, (1, 0, 2)))
    xl_major.tofile(out_dir / "volume_xl_major.f32")

    volume[3].tofile(out_dir / "expected_inline.f32")      # read_slice(inline, 3)
    volume[:, 5, :].tofile(out_dir / "expected_crossline.f32")
    volume[:, :, 16].tofile(out_dir / "expected_sample.f32")

    indexed, vmin, vmax = _py_fast_slice_to_indexed8(volume, 0, 3)  # inline 3, auto stretch
    assert indexed.dtype == np.uint8
    indexed.astype(np.float32).tofile(out_dir / "expected_inline_indexed8.f32")

    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source": "tests/fixtures/realdata/tiny.sgy",
                "shape": [int(meta.n_inlines), int(meta.n_crosslines), int(meta.n_samples)],
                "dt_ms": float(meta.dt_ms),
                "iline_start": float(meta.iline_start),
                "iline_step": float(meta.iline_step),
                "xline_start": float(meta.xline_start),
                "xline_step": float(meta.xline_step),
                "last_sample_ms": float((meta.n_samples - 1) * meta.dt_ms + meta.t0_ms),
                "storage": "crossline-major",
                "slices": {"inline": 3, "crossline": 5, "sample": 16},
                "indexed8_stretch": [vmin, vmax],
                "oracle": "geoviz_seismic.loader + native_backend._py_fast_slice_to_indexed8@671ee426",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"tiny_sgy fixtures written to {out_dir} shape={volume.shape} "
        f"indexed8 stretch=({vmin}, {vmax})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
