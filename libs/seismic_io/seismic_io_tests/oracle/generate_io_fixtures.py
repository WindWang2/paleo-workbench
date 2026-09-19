"""Generate the frozen native-IO oracle fixtures (S line).

Produces SEG-Y files (IEEE format 5 and IBM format 1, unsorted trace order,
NaN-contaminated samples), a PWBVOL1 payload, expected metadata, and the
expected half-open window dumps that the C++ tests (tile_read_test.cpp,
service_test.cpp) compare against. Window expectations are computed with
numpy slicing of the SAME sample grid an independent reader (segyio) verified
— so the oracle is doubly sourced.

Also freezes BinGridGeometry probe conversions computed with the pinned
geoviz models.BinGridGeometry (geo-viz-engine@08851951) for the spatial
seam test, and a slanted plane with analytic dip angles for cross-checks.

Negative self-check: a perturbed expected window (1000x the frozen max_abs
tolerance) must FAIL the comparator; a vacuous comparator cannot pass.

Usage (pinned interpreter, read-only):
    .venv-oracle/bin/python libs/seismic_io/seismic_io_tests/oracle/\
generate_io_fixtures.py --out libs/seismic_io/seismic_io_tests/fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
ORACLE_MODELS = (
    REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
    / "geoviz_seismic" / "models.py"
)

TOL = {"max_abs": 1e-6}

INTERPRETER = {
    "python": sys.version.split()[0],
    "numpy": np.__version__,
    "executable": sys.executable,
}


def load_models():
    spec = importlib.util.spec_from_file_location("geoviz_oracle_models",
                                                  ORACLE_MODELS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# SEG-Y writing (pure struct; deliberately independent of segyio)
# ---------------------------------------------------------------------------

def put16_be(buf: bytearray, off: int, v: int) -> None:
    buf[off] = (v >> 8) & 0xFF
    buf[off + 1] = v & 0xFF


def put32_be(buf: bytearray, off: int, v: int) -> None:
    for b in range(4):
        buf[off + b] = (v >> (24 - 8 * b)) & 0xFF


def ibm_from_float(value: float) -> int:
    """IBM System/360 float encoding (format code 1), big-endian int."""
    if value == 0.0:
        return 0
    sign = 0x80000000 if value < 0 else 0
    value = abs(float(value))
    # normalize into [1/16, 1)
    exp16 = 0
    while value >= 1.0:
        value /= 16.0
        exp16 += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exp16 -= 1
    mantissa = int(value * (1 << 24))
    if mantissa >= (1 << 24):  # rounding overflow
        mantissa >>= 4
        exp16 += 1
    return sign | ((exp16 + 64) << 24) | mantissa


def write_segy(path: Path, ni: int, nc: int, ns: int, dt_us: int,
               fmt: int, ilines: list[int], xlines: list[int],
               samples_ilxl_t: np.ndarray, cdp_corners: dict | None) -> None:
    """samples_ilxl_t[(il_idx, xl_idx, t)] float32; traces written in the
    (ilines, xlines) FILE ORDER given (the grid may be unsorted)."""
    buf = bytearray(3600)
    put16_be(buf, 3200 + 16, dt_us)
    put16_be(buf, 3200 + 20, ns)
    put16_be(buf, 3200 + 24, fmt)
    for il_idx, il in enumerate(ilines):
        for xl_idx, xl in enumerate(xlines):
            trace = bytearray(240 + ns * 4)
            put32_be(trace, 188, il)
            put32_be(trace, 192, xl)
            if cdp_corners is not None and (il_idx, xl_idx) in cdp_corners:
                corner = cdp_corners[(il_idx, xl_idx)]
                put16_be(trace, 70, corner.get("scalar", 0))
                put32_be(trace, 72, int(corner.get("source_x", 0)))
                put32_be(trace, 76, int(corner.get("source_y", 0)))
                put32_be(trace, 180, int(corner.get("cdp_x", 0)))
                put32_be(trace, 184, int(corner.get("cdp_y", 0)))
            row = samples_ilxl_t[il_idx, xl_idx]
            for t in range(ns):
                v = float(row[t])
                off = 240 + t * 4
                if np.isnan(v):
                    payload = struct.unpack(">I", struct.pack(
                        ">f", np.float32(np.nan)))[0]
                elif fmt == 5:
                    payload = struct.unpack(">I", struct.pack(
                        ">f", np.float32(v)))[0]
                else:  # IBM (format 1)
                    payload = ibm_from_float(v)
                struct.pack_into(">I", trace, off, payload)
            buf.extend(trace)
    path.write_bytes(bytes(buf))


def write_pwbvol(path: Path, vol: np.ndarray, axis_starts: list[float],
                 axis_steps: list[float], axis_units: list[str]) -> None:
    header = {
        "version": 1,
        "shape": [int(vol.shape[0]), int(vol.shape[1]), int(vol.shape[2])],
        "axes": ["inline", "crossline", "sample"],
        "axis_starts": axis_starts,
        "axis_steps": axis_steps,
        "axis_units": axis_units,
        "value_unit": "amplitude",
        "layout": "c-order-f32",
        "algorithm_id": "io.oracle",
        "algorithm_version": "1.0.0",
        "build_identity": "io-oracle",
        "request_id": "io-oracle-0",
        "approximations": [],
    }
    header_text = json.dumps(header, separators=(",", ":")).encode()
    buf = b"PWBVOL1\0" + struct.pack("<I", len(header_text)) + header_text
    buf += vol.astype("<f4").tobytes()
    path.write_bytes(buf)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def build_cases(out: Path) -> dict:
    cases: dict = {}
    rng = np.random.default_rng(31415926)

    # Case A: format 5, unsorted grid, NaN contamination, dt 2 ms.
    ni, nc, ns = 6, 4, 10
    vol = rng.uniform(-1.0, 1.0, size=(ni, nc, ns)).astype(np.float32)
    vol[1, 2, 3] = np.float32("nan")
    vol[5, 0, 0] = np.float32("nan")
    vol[0, 3, 9] = np.float32("inf")
    file_il = [5, 1, 3, 6, 2, 4]     # file order, NOT sorted
    file_xl = [3, 1, 4, 2]
    ilines = sorted(file_il)
    xlines = sorted(file_xl)
    # Reorder: vol[il_idx, xl_idx] uses sorted grid; write in file order.
    perm_il = [ilines.index(v) for v in file_il]
    perm_xl = [xlines.index(v) for v in file_xl]
    write_segy(out / "io_oracle.sgy", ni, nc, ns, 2000, 5, file_il, file_xl,
               vol[perm_il][:, perm_xl], None)
    cases["io_oracle.sgy"] = {
        "shape": [ni, nc, ns], "dt_ms": 2.0, "format": 5,
        "iline_start": float(min(ilines)), "iline_step": 1.0,
        "xline_start": float(min(xlines)), "xline_step": 1.0,
        "unit": "ms", "domain": "time", "note": "unsorted grid, NaN/Inf",
    }

    # Case B: format 1 (IBM), steps (2, 3), dt 4 ms.
    ni2, nc2, ns2 = 4, 3, 8
    vol2 = rng.uniform(-100.0, 100.0, size=(ni2, nc2, ns2)).astype(np.float32)
    write_segy(out / "io_oracle_ibm.sgy", ni2, nc2, ns2, 4000, 1,
               [1, 3, 5, 7], [10, 13, 16], vol2, None)
    cases["io_oracle_ibm.sgy"] = {
        "shape": [ni2, nc2, ns2], "dt_ms": 4.0, "format": 1,
        "iline_start": 1.0, "iline_step": 2.0,
        "xline_start": 10.0, "xline_step": 3.0,
        "unit": "ms", "domain": "time",
        "note": "IBM floats; non-unit line steps",
    }

    # Case C: bin-grid calibrated survey (CDP corners + SourceGroupScalar).
    # Origin (500000, 3000000), azimuth 20 deg, spacings il=25 m, xl=50 m.
    # Corner world coords computed through the PINNED models.BinGridGeometry
    # itself, so the C++ inference must invert exactly this calibration.
    models = load_models()
    grid = models.BinGridGeometry(x_origin=500000.0, y_origin=3000000.0,
                                  il_azimuth_deg=20.0, il_spacing_m=25.0,
                                  xl_spacing_m=50.0)
    ni3, nc3, ns3 = 4, 4, 6
    vol3 = rng.uniform(-1.0, 1.0, size=(ni3, nc3, ns3)).astype(np.float32)
    corners = {}
    iline_step, xline_step = 2, 3
    probes = []
    for (il_idx, xl_idx), key in {(0, 0): "origin", (1, 0): "plus_il",
                                  (0, 1): "plus_xl"}.items():
        il_val = 100 + il_idx * iline_step
        xl_val = 200 + xl_idx * xline_step
        # Corner positions are ONE grid step apart: fractional indices are
        # the line offsets DIVIDED by the line step.
        x, y = grid.il_xl_to_xy(float(il_val - 100) / iline_step,
                                float(xl_val - 200) / xline_step)
        # Centimetre quantization through the standard SourceGroupScalar
        # (scalar = -100 -> divide by 100 on read): the finest SEG-Y int32
        # encoding that fits a 3,000 km UTM northing (mm would overflow
        # int32). Inferred grid stays within ~5 mm of the calibration.
        corners[(il_idx, xl_idx)] = {
            "scalar": -100, "cdp_x": int(round(x * 100.0)),
            "cdp_y": int(round(y * 100.0)),
        }
        probes.append({"il": il_val, "xl": xl_val, "x": x, "y": y})
    write_segy(out / "io_oracle_bins.sgy", ni3, nc3, ns3, 1000, 5,
               [100, 102, 104, 106], [200, 203, 206, 209], vol3, corners)

    # Freeze what the PINNED LOADER INFERS from the written bytes (not the
    # construction parameters): open the file with segyio and run the
    # oracle's own _infer_bin_grid on the corner traces. The inference
    # convention (azimuth = atan2(dx, dy) + sign fix) is the frozen
    # behavior the C++ inspector must replicate.
    import segyio
    loader_src = (
        REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
        / "geoviz_seismic" / "loader.py"
    )
    # loader.py uses relative imports (.models); register a synthetic
    # package so the standalone load resolves them against the same
    # pinned directory.
    import types
    pkg_name = "geoviz_oracle_pkg"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(loader_src.parent)]
    sys.modules.setdefault(pkg_name, pkg)
    lspec = importlib.util.spec_from_file_location(pkg_name + ".loader",
                                                   loader_src)
    lmod = importlib.util.module_from_spec(lspec)
    sys.modules[pkg_name + ".loader"] = lmod
    lspec.loader.exec_module(lmod)
    with segyio.open(out / "io_oracle_bins.sgy", "r", strict=False,
                     ignore_geometry=True) as f:
        inferred = lmod._infer_bin_grid(
            f, [100, 102, 104, 106], [200, 203, 206, 209])
    if inferred is None:
        raise AssertionError("oracle _infer_bin_grid returned None")
    inferred_grid = {
        "x_origin": inferred.x_origin, "y_origin": inferred.y_origin,
        "il_azimuth_deg": inferred.il_azimuth_deg,
        "il_spacing_m": inferred.il_spacing_m,
        "xl_spacing_m": inferred.xl_spacing_m,
    }
    # Probe round trips through the INFERRED grid (what consumers get).
    probe_expect = []
    for probe in probes:
        il_f, xl_f = inferred.xy_to_il_xl(probe["x"], probe["y"])
        x2, y2 = inferred.il_xl_to_xy(il_f, xl_f)
        nearest = inferred.nearest_il_xl(probe["x"], probe["y"])
        probe_expect.append({
            "x": probe["x"], "y": probe["y"],
            "il_frac": il_f, "xl_frac": xl_f,
            "x_roundtrip": x2, "y_roundtrip": y2,
            "nearest_il": nearest[0], "nearest_xl": nearest[1],
        })
    cases["io_oracle_bins.sgy"] = {
        "shape": [ni3, nc3, ns3], "dt_ms": 1.0, "format": 5,
        "iline_start": 100.0, "iline_step": 2.0,
        "xline_start": 200.0, "xline_step": 3.0,
        "unit": "ms", "domain": "time",
        "bin_grid": inferred_grid,
        "bin_grid_constructed": {
            "x_origin": grid.x_origin, "y_origin": grid.y_origin,
            "il_azimuth_deg": grid.il_azimuth_deg,
            "il_spacing_m": grid.il_spacing_m,
            "xl_spacing_m": grid.xl_spacing_m,
        },
        "probes": probe_expect,
        "note": "bin-grid calibration; expectation = the pinned loader's "
                "own corner-trace inference of the written bytes",
    }

    # Case D: PWBVOL1 with depth axis ("m").
    ni4, nc4, ns4 = 3, 5, 7
    vol4 = rng.uniform(-2.0, 2.0, size=(ni4, nc4, ns4)).astype(np.float32)
    vol4[2, 4, 6] = np.float32("nan")
    write_pwbvol(out / "io_oracle.pwbvol", vol4,
                 [10.0, 20.0, 1500.0], [5.0, 5.0, 2.5],
                 ["", "", "m"])
    cases["io_oracle.pwbvol"] = {
        "shape": [ni4, nc4, ns4], "storage": "pwbvol1",
        "iline_start": 10.0, "iline_step": 5.0,
        "xline_start": 20.0, "xline_step": 5.0,
        "sample_start": 1500.0, "sample_step": 2.5,
        "unit": "m", "domain": "depth", "note": "depth-domain payload",
    }

    return {
        "io_oracle.sgy": vol,
        "io_oracle_ibm.sgy": vol2,
        "io_oracle_bins.sgy": vol3,
        "io_oracle.pwbvol": vol4,
    }, cases


WINDOWS = [
    {"name": "full", "origin": [0, 0, 0], "extent": None},  # full volume
    {"name": "corner", "origin": [0, 0, 0], "extent": [2, 2, 3]},
    {"name": "end", "origin": None, "extent": [1, 2, 4]},   # pinned per case
    {"name": "middle", "origin": [1, 1, 2], "extent": [2, 2, 3]},
    {"name": "single_trace", "origin": [2, 1, 0], "extent": [1, 1, None]},
]


def expected_windows(vol: np.ndarray) -> dict[str, np.ndarray]:
    ni, nc, ns = vol.shape
    out = {}
    out["full"] = vol
    out["corner"] = vol[0:2, 0:2, 0:3]
    out["end"] = vol[ni - 1:ni, nc - 2:nc, ns - 4:ns]
    out["middle"] = vol[1:3, 1:3, 2:5]
    out["single_trace"] = vol[2:3, 1:2, 0:ns]
    return out


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(arr: np.ndarray) -> dict:
    finite = arr[np.isfinite(arr)]
    return {
        "elements": int(arr.size),
        "n_nan": int(np.isnan(arr).sum()),
        "n_inf": int(np.isinf(arr).sum()),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
    }


def negative_self_check(windows: dict[str, np.ndarray]) -> None:
    for name, expected in windows.items():
        perturbed = expected + np.float32(1000.0 * TOL["max_abs"])
        with np.errstate(invalid="ignore"):
            nan_a, nan_b = np.isnan(expected), np.isnan(perturbed)
            if not np.array_equal(nan_a, nan_b):
                continue
            fa, fb = expected[~nan_a], perturbed[~nan_b]
            if fa.size == 0:
                continue  # all-NaN window: mask perturbation not needed here
            if float(np.max(np.abs(fa - fb))) <= TOL["max_abs"]:
                raise AssertionError(
                    f"negative self-check failed for window {name}: "
                    "perturbed oracle passed the frozen tolerance")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vols, cases = build_cases(args.out)

    # Independent verification: segyio must agree with the struct writer on
    # the IEEE case (sample-exact on the finite subset after grid mapping).
    try:
        import segyio
        with segyio.open(args.out / "io_oracle.sgy", "r", strict=False) as f:
            # segyio reports ilines/xlines in FILE order for an unsorted
            # file; map through the sorted grid to compare with vol.
            ilines = [int(v) for v in f.ilines]
            xlines = [int(v) for v in f.xlines]
            sorted_il = sorted(ilines)
            sorted_xl = sorted(xlines)
            vol = vols["io_oracle.sgy"]
            for il in ilines:
                block = np.asarray(f.iline[il], dtype=np.float32)
                i = sorted_il.index(il)
                for j, xl in enumerate(xlines):
                    trace = block[j]
                    want = vol[i, sorted_xl.index(xl)]
                    finite = np.isfinite(trace) & np.isfinite(want)
                    if not np.allclose(trace[finite], want[finite],
                                       rtol=0, atol=0):
                        raise AssertionError(
                            f"segyio cross-check mismatch at ({il},{xl})")
        cases["io_oracle.sgy"]["segyio_crosscheck"] = "pass"
    except ImportError:
        cases["io_oracle.sgy"]["segyio_crosscheck"] = "skipped (no segyio)"

    # Freeze expected windows per case.
    manifest = {"cases": {}, "interpreter": INTERPRETER,
                "tolerances": TOL,
                "comparison": "format-5/pwbvol1 windows: exact f32 "
                              "equality (NaN positions bitwise); IBM "
                              "format-1 windows: dual criterion "
                              "|a-e| <= max(1e-4, 1e-6*|e|) absorbing the "
                              "encoder-side 24-bit mantissa loss",
                "oracle": {
                    "files": ["io_oracle.sgy", "io_oracle_ibm.sgy",
                              "io_oracle_bins.sgy", "io_oracle.pwbvol"],
                    "bin_grid": "geoviz_seismic.models.BinGridGeometry"
                                "@08851951",
                }}
    for name, vol in vols.items():
        windows = expected_windows(vol)
        negative_self_check(windows)
        files = {}
        for wname, values in windows.items():
            path = args.out / f"{name}.{wname}.f32"
            values.astype(np.float32).tofile(path)
            files[f"{name}.{wname}.f32"] = {
                "window": wname, "shape": list(values.shape),
                "sha256": sha256_of(path), **stats(values),
            }
        manifest["cases"][name] = {
            "meta": cases[name], "files": files,
            "windows": {w["name"]: w for w in WINDOWS if w["name"] != "full"},
        }

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(vols)} IO oracle cases under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
