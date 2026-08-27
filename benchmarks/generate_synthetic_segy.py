#!/usr/bin/env python3
"""Generate deterministic synthetic 3-D SEG-Y volumes for large-volume work.

The output is a standard SEG-Y Rev 1 file (big-endian, IEEE float32 traces,
inline-major trace ordering, INLINE_3D/CROSSLINE_3D trace headers) intended
as the shared test volume for the "100G seismic volume" wayfinder effort
(WindWang2/paleo-workbench#1067):

- ``tiny``     16 IL x 16 XL x 128 T     (~0.6 MB file)   smoke tests / unit tests
- ``quick2g``  1024 IL x 1024 XL x 512 T (~2.4 GB file)   fast regression
- ``full100g`` 5000 IL x 5000 XL x 1000 T (~106 GB file)  benchmark & acceptance

Every inline is generated from its own seeded ``numpy.random.Generator``
stream (``default_rng([seed, iline])``), so the volume is byte-for-byte
reproducible for a given (preset, seed, numpy version) and could be resumed
inline-by-inline if ever needed.

Geology model (all deterministic): white-noise reflectivity convolved with a
Ricker wavelet, four sinusoidal reflector surfaces, a planar fault that throws
the reflectors on one side, and a meandering channel that dims amplitudes
along its path.

Trace layout is written byte-by-byte (not via segyio) so full-scale
generation runs at raw disk throughput; ``--verify`` reads the result back
through segyio to prove the file is well-formed and matches the generator.

Usage::

    python benchmarks/generate_synthetic_segy.py --preset full100g \
        --out /data/bench/synthetic_100g.segy --verify

Throughput and ETA are printed every 200 inlines.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import oaconvolve

# --- SEG-Y layout constants (all offsets 0-based, big-endian on disk) ------
TEXT_HEADER_BYTES = 3200
BIN_HEADER_BYTES = 400
TRACE_HEADER_BYTES = 240
# Binary-header field offsets.
BIN_DT_OFF = 16  # int16, microseconds
BIN_NS_OFF = 20  # int16, samples per trace
BIN_FMT_OFF = 24  # int16, 5 = IEEE float32
BIN_MSYS_OFF = 300  # int16, 1 = meters
# Trace-header field offsets (int32 unless noted).
TR_SEQ_LINE_OFF = 0
TR_SEQ_FILE_OFF = 4
TR_SX_OFF = 180
TR_SY_OFF = 184
TR_ILINE_OFF = 188
TR_XLINE_OFF = 192

TRACE_SAMPLE_INTERVAL_US = 2000  # 2 ms
BIN_SIZE_GRID_M = 25.0  # bin spacing for synthetic SX/SY coordinates


@dataclass(frozen=True)
class VolumeSpec:
    nil: int  # inline count
    nxl: int  # crossline count
    nt: int  # samples per trace
    seed: int = 20260827

    @property
    def data_bytes(self) -> int:
        return self.nil * self.nxl * self.nt * 4

    @property
    def file_bytes(self) -> int:
        traces = self.nil * self.nxl
        return TEXT_HEADER_BYTES + BIN_HEADER_BYTES + traces * (
            TRACE_HEADER_BYTES + self.nt * 4
        )


PRESETS: dict[str, VolumeSpec] = {
    "tiny": VolumeSpec(16, 16, 128),
    "quick2g": VolumeSpec(1024, 1024, 512),
    "full100g": VolumeSpec(5000, 5000, 1000),
}

# Reflector surfaces: (base sample, amplitude in samples, xline period).
_REFLECTORS: tuple[tuple[float, float, float], ...] = (
    (120.0, 18.0, 900.0),
    (320.0, 30.0, 1400.0),
    (560.0, 22.0, 700.0),
    (800.0, 34.0, 1800.0),
)
_FAULT_XLINE_FRACTION = 0.62  # fault plane at 62% of the crossline range
_FAULT_THROW_SAMPLES = 14.0
_CHANNEL_DEPTH_SAMPLE = 560.0
_CHANNEL_HALFWIDTH = 90.0
_CHANNEL_MEANDER = 150.0  # crosslines of meander amplitude
_WAVELET_POINTS = 61
_WAVELET_SIGMA = 12.0


def _ebcdic_text_header(spec: VolumeSpec) -> bytes:
    lines = [
        f"C {i + 1:>2} " + text
        for i, text in enumerate([
            "SYNTHETIC SEISMIC VOLUME - DETERMINISTIC TEST DATA",
            f"GRID {spec.nil} IL x {spec.nxl} XL x {spec.nt} T, DT 2 MS, IEEE FL32",
            f"SEED {spec.seed}, INLINE-MAJOR, GENERATED IN-PLACE",
            "FOR PALEO-WORKBENCH 100G-VOLUME BENCHMARKS (#1067)",
        ])
    ]
    block = "\n".join(lines).encode("ascii")
    if len(block) > TEXT_HEADER_BYTES:
        raise ValueError("text header overflow")
    return block.ljust(TEXT_HEADER_BYTES, b" ").decode("ascii").encode("cp500")


def _binary_header(spec: VolumeSpec) -> bytes:
    hdr = bytearray(BIN_HEADER_BYTES)
    hdr[BIN_DT_OFF : BIN_DT_OFF + 2] = int(TRACE_SAMPLE_INTERVAL_US).to_bytes(2, "big")
    hdr[BIN_NS_OFF : BIN_NS_OFF + 2] = int(spec.nt).to_bytes(2, "big")
    hdr[BIN_FMT_OFF : BIN_FMT_OFF + 2] = (5).to_bytes(2, "big")
    hdr[BIN_MSYS_OFF : BIN_MSYS_OFF + 2] = (1).to_bytes(2, "big")
    return bytes(hdr)


def _put_i32_field(block: np.ndarray, off: int, values: np.ndarray) -> None:
    """Write big-endian int32 ``values`` into uint8 header rows at ``off``."""
    raw = np.asarray(values, dtype=">i4").tobytes()
    block[:, off : off + 4] = np.frombuffer(raw, dtype=np.uint8).reshape(
        len(values), 4
    )


def _trace_headers(spec: VolumeSpec, iline_idx: int) -> np.ndarray:
    """Trace-header rows for one inline (nxl x 240 uint8)."""
    nxl = spec.nxl
    iline = iline_idx + 1
    xlines = np.arange(1, nxl + 1, dtype=np.int64)
    block = np.zeros((nxl, TRACE_HEADER_BYTES), dtype=np.uint8)
    seq0 = iline_idx * nxl
    _put_i32_field(block, TR_SEQ_LINE_OFF, seq0 + xlines)
    _put_i32_field(block, TR_SEQ_FILE_OFF, seq0 + xlines)
    _put_i32_field(block, TR_SX_OFF, np.rint(xlines * BIN_SIZE_GRID_M).astype(np.int64))
    _put_i32_field(block, TR_SY_OFF, np.full(nxl, np.rint(iline * BIN_SIZE_GRID_M), np.int64))
    _put_i32_field(block, TR_ILINE_OFF, np.full(nxl, iline))
    _put_i32_field(block, TR_XLINE_OFF, xlines)
    return block


def _ricker(points: int, sigma: float) -> np.ndarray:
    """Mexican-hat wavelet (scipy removed ``signal.ricker`` in 1.15)."""
    x = np.arange(points, dtype=np.float64) - (points - 1.0) / 2.0
    a2 = (x / sigma) ** 2
    w = (1.0 - a2) * np.exp(-a2 / 2.0)
    w /= np.abs(w).max()
    return w.astype(np.float32)


def _inline_samples(spec: VolumeSpec, iline_idx: int) -> np.ndarray:
    """One inline slab (nxl x nt, float32, native endian), fully deterministic."""
    rng = np.random.default_rng([spec.seed, iline_idx])
    nxl, nt = spec.nxl, spec.nt
    refl = rng.standard_normal((nxl, nt), dtype=np.float32) * 0.25

    xl = np.arange(nxl, dtype=np.float64)
    fault_xl = _FAULT_XLINE_FRACTION * (nxl - 1)
    throw = np.where(xl > fault_xl, _FAULT_THROW_SAMPLES, 0.0)

    for k, (base, amp, period) in enumerate(_REFLECTORS):
        phase = 0.7 * k + 0.013 * iline_idx
        surf = (
            base
            + amp * np.sin(2.0 * np.pi * xl / period + phase)
            + throw
            + 4.0 * np.sin(0.01 * iline_idx + k)
        )
        idx = np.rint(surf).astype(np.int64)
        valid = (idx >= 0) & (idx < nt)
        if valid.any():
            rows = np.nonzero(valid)[0]
            refl[rows, idx[rows]] += np.float32(0.8 + 0.35 * k)

    # Meandering channel that dims amplitudes around its axis.
    center = 0.5 * nxl + _CHANNEL_MEANDER * np.sin(0.004 * iline_idx)
    dist = np.abs(xl - center)
    chan = np.exp(-((dist / _CHANNEL_HALFWIDTH) ** 2))
    d_idx = int(round(_CHANNEL_DEPTH_SAMPLE))
    if 0 < d_idx < nt - 1:
        band = slice(d_idx - 40, d_idx + 40)
        refl[:, band] *= (1.0 - 0.45 * chan)[:, None].astype(np.float32)

    wavelet = _ricker(_WAVELET_POINTS, _WAVELET_SIGMA)
    slab = oaconvolve(refl, wavelet[np.newaxis, :], mode="same", axes=1)
    return np.ascontiguousarray(slab, dtype=np.float32)


def generate_volume(spec: VolumeSpec, out_path: Path, progress: bool = True) -> dict:
    """Write the full SEG-Y volume; returns timing/throughput facts."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    written = 0
    with open(out_path, "wb") as fh:
        fh.write(_ebcdic_text_header(spec))
        fh.write(_binary_header(spec))
        written += TEXT_HEADER_BYTES + BIN_HEADER_BYTES
        for il in range(spec.nil):
            # SEG-Y is interleaved per trace (240-byte header, then samples);
            # assemble one interleaved record block per inline for throughput.
            headers = _trace_headers(spec, il)
            data = (
                np.ascontiguousarray(_inline_samples(spec, il))
                .astype(">f4")
                .view(np.uint8)
                .reshape(spec.nxl, spec.nt * 4)
            )
            records = np.empty((spec.nxl, TRACE_HEADER_BYTES + spec.nt * 4), dtype=np.uint8)
            records[:, :TRACE_HEADER_BYTES] = headers
            records[:, TRACE_HEADER_BYTES:] = data
            fh.write(records.tobytes())
            written += spec.nxl * (TRACE_HEADER_BYTES + spec.nt * 4)
            if progress and ((il + 1) % 200 == 0 or il + 1 == spec.nil):
                dt = time.perf_counter() - t0
                done = il + 1
                rate = written / dt / (1024 * 1024)
                eta = (spec.file_bytes - written) / max(rate, 1e-9) / 1e6 / 60
                print(
                    f"  inline {done}/{spec.nil}  {written / 1e9:.1f} GB  "
                    f"{rate:.0f} MB/s  ETA {eta:.1f} min",
                    flush=True,
                )
    elapsed = time.perf_counter() - t0
    actual = out_path.stat().st_size
    if actual != spec.file_bytes:
        raise RuntimeError(
            f"size mismatch: wrote {actual} bytes, expected {spec.file_bytes}"
        )
    return {
        "path": str(out_path),
        "file_bytes": actual,
        "elapsed_s": elapsed,
        "throughput_mb_s": actual / elapsed / (1024 * 1024),
    }


def verify_volume(spec: VolumeSpec, path: Path) -> dict:
    """Read the file back through segyio and check geometry + content."""
    import segyio

    facts: dict = {}
    with segyio.open(path, "r", ignore_geometry=False) as f:
        expected_traces = spec.nil * spec.nxl
        if int(f.tracecount) != expected_traces:
            raise AssertionError(f"tracecount {f.tracecount} != {expected_traces}")
        ilines = np.asarray(f.ilines)
        xlines = np.asarray(f.xlines)
        if not (ilines[0] == 1 and ilines[-1] == spec.nil and len(ilines) == spec.nil):
            raise AssertionError(f"ilines wrong: {ilines[:3]}..{ilines[-3:]}")
        if not (xlines[0] == 1 and xlines[-1] == spec.nxl and len(xlines) == spec.nxl):
            raise AssertionError(f"xlines wrong: {xlines[:3]}..{xlines[-3:]}")
        hdr = f.header[0]
        assert int(hdr[segyio.TraceField.INLINE_3D]) == 1
        assert int(hdr[segyio.TraceField.CROSSLINE_3D]) == 1
        assert int(hdr[segyio.TraceField.INLINE_3D]) == 1
        # Content: regenerate two inlines (first / a middle one) and compare.
        for il_idx in (0, spec.nil // 2):
            expected = _inline_samples(spec, il_idx)
            got = np.asarray(f.iline[il_idx + 1], dtype=np.float32)
            if not np.array_equal(got, expected):
                raise AssertionError(f"inline {il_idx + 1} content mismatch")
        facts["tracecount"] = expected_traces
        facts["ilines"] = f"{len(ilines)} ({ilines[0]}..{ilines[-1]})"
        facts["xlines"] = f"{len(xlines)} ({xlines[0]}..{xlines[-1]})"
        facts["samples"] = int(len(f.samples))
    return facts


def sha256_of(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            blob = fh.read(chunk)
            if not blob:
                break
            h.update(blob)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset", choices=sorted(PRESETS), default="tiny")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--nil", "--nxl", "--nt", type=int, dest="unused", help=argparse.SUPPRESS)
    ap.add_argument("--verify", action="store_true", help="segyio read-back check")
    ap.add_argument("--sha256", action="store_true", help="print file digest")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    spec = PRESETS[args.preset]
    if args.seed is not None:
        spec = VolumeSpec(spec.nil, spec.nxl, spec.nt, seed=args.seed)

    if not args.quiet:
        print(
            f"preset={args.preset}  grid={spec.nil}x{spec.nxl}x{spec.nt}  "
            f"file≈{spec.file_bytes / 1e9:.1f} GB  seed={spec.seed}\n"
            f"writing {args.out} ..."
        )
    facts = generate_volume(spec, args.out, progress=not args.quiet)
    print(
        f"done: {facts['file_bytes'] / 1e9:.2f} GB in {facts['elapsed_s']:.1f} s "
        f"({facts['throughput_mb_s']:.0f} MB/s)"
    )
    if args.verify:
        vf = verify_volume(spec, args.out)
        print(f"verify OK: {vf}")
    if args.sha256:
        print(f"sha256: {sha256_of(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
