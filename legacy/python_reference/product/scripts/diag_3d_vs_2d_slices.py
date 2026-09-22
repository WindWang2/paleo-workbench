#!/usr/bin/env python3
"""Diagnose 3D volume planes vs 2D profile panels (Image #1 symptom).

User symptom: 三维体显示的剖面与下方 Inline/Crossline/Time 剖面不一致.

Contract under test (seismic_view + Renderer3D):
  volume shape (ni, nx, nt)
  3D plane data  = volume slices WITHOUT .T
  2D panel data  = loader full-res (or volume) WITH .T for display
  Time 2D labels X=Inline, Y=Crossline after .T → data shape must be (nx, ni)

Exit 0 = all checks pass (green). Exit 1 = red (bug present).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "geo-viz-engine"))
sys.path.insert(0, str(ROOT / "geo-viz-engine/packages/geoviz_seismic"))

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_seismic.loader import SeismicLoader
from geoviz_seismic.models import SliceInfo
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path


def _build_slice_info(meta, slice_type: str, position: int, data_shape: tuple) -> SliceInfo:
    """Mirror seismic_view._build_slice_info axis labeling."""
    n_h = data_shape[1] if len(data_shape) > 1 else data_shape[0]
    n_v = data_shape[0]
    m = meta
    if slice_type == "inline":
        h_arr = np.arange(n_h) * m.xline_step + m.xline_start
        v_arr = np.arange(n_v) * m.dt_ms + m.t0_ms
        return SliceInfo(
            slice_type=slice_type,
            position=position,
            axis_h_label="Crossline",
            axis_v_label="Time (ms)",
            axis_h_values=h_arr.tolist(),
            axis_v_values=v_arr.tolist(),
        )
    if slice_type == "crossline":
        h_arr = np.arange(n_h) * m.iline_step + m.iline_start
        v_arr = np.arange(n_v) * m.dt_ms + m.t0_ms
        return SliceInfo(
            slice_type=slice_type,
            position=position,
            axis_h_label="Inline",
            axis_v_label="Time (ms)",
            axis_h_values=h_arr.tolist(),
            axis_v_values=v_arr.tolist(),
        )
    h_arr = np.arange(n_h) * m.iline_step + m.iline_start
    v_arr = np.arange(n_v) * m.xline_step + m.xline_start
    return SliceInfo(
        slice_type=slice_type,
        position=position,
        axis_h_label="Inline",
        axis_v_label="Crossline",
        axis_h_values=h_arr.tolist(),
        axis_v_values=v_arr.tolist(),
    )


def main() -> int:
    segy = ROOT / "data/地震体/200P_seismic.sgy"
    if not segy.is_file():
        print("SKIP: no demo SEGY")
        return 0

    failures: list[str] = []

    vol, _ = load_seismic_volume_from_path(str(segy))
    loader = SeismicLoader(str(segy))
    try:
        meta = loader.inspect()
        print(f"meta: IL={meta.n_inlines} XL={meta.n_crosslines} T={meta.n_samples}")
        print(f"preview volume: {vol.shape}")
        print(f"IL range: {meta.iline_start}–{meta.iline_start + (meta.n_inlines - 1) * meta.iline_step}")
        print(f"XL range: {meta.xline_start}–{meta.xline_start + (meta.n_crosslines - 1) * meta.xline_step}")

        # --- Check 1: timeslice shape == volume axes (Image #1 Time labels) ---
        t_mid = meta.n_samples // 2
        ts = loader.read_timeslice(t_mid)
        print(f"\n[1] read_timeslice mid shape={ts.shape} expected=({meta.n_inlines},{meta.n_crosslines})")
        if ts.shape != (meta.n_inlines, meta.n_crosslines):
            failures.append(
                f"TIME_SHAPE: timeslice {ts.shape} != (ni,nx)=({meta.n_inlines},{meta.n_crosslines}) "
                f"— 2D Time axes will be swapped vs 3D (Image #1 symptom)"
            )
        else:
            print("    OK timeslice axes match volume")

        # --- Check 2: Time panel labels after .T (what user sees on axes) ---
        panel_t = ts.T  # seismic_view always .T before ProfileVD
        info_t = _build_slice_info(meta, "time", t_mid, panel_t.shape)
        h0, h1 = info_t.axis_h_values[0], info_t.axis_h_values[-1]
        v0, v1 = info_t.axis_v_values[0], info_t.axis_v_values[-1]
        print(f"[2] Time panel after .T shape={panel_t.shape}")
        print(f"    X={info_t.axis_h_label} {h0:.0f}–{h1:.0f}")
        print(f"    Y={info_t.axis_v_label} {v0:.0f}–{v1:.0f}")
        # Image #1 bug signature: X ends ~4575 (IL start + n_xl) and Y ends ~1955 (XL start + n_il)
        bug_x = abs(h1 - (meta.iline_start + (meta.n_crosslines - 1) * meta.iline_step)) < 2
        bug_y = abs(v1 - (meta.xline_start + (meta.n_inlines - 1) * meta.xline_step)) < 2
        good_x = abs(h1 - (meta.iline_start + (meta.n_inlines - 1) * meta.iline_step)) < 2
        good_y = abs(v1 - (meta.xline_start + (meta.n_crosslines - 1) * meta.xline_step)) < 2
        if bug_x and bug_y:
            failures.append(
                f"TIME_LABELS_SWAPPED: X={h0:.0f}–{h1:.0f} Y={v0:.0f}–{v1:.0f} "
                f"matches Image #1 wrong labels (IL/XL extents swapped)"
            )
        elif not (good_x and good_y):
            failures.append(
                f"TIME_LABELS_UNEXPECTED: X={h0:.0f}–{h1:.0f} Y={v0:.0f}–{v1:.0f}"
            )
        else:
            print("    OK Time labels match full IL/XL ranges")

        # --- Check 3: 3D time plane vs timeslice content (strided) ---
        # Approximate factor from shapes
        fi = max(1, round(meta.n_inlines / vol.shape[0]))
        fx = max(1, round(meta.n_crosslines / vol.shape[1]))
        ft = max(1, round(meta.n_samples / vol.shape[2]))
        # Prefer actual volume from loader with known factor if we can re-load
        factor = (6, 4, 8)
        vol2 = loader.get_volume_downsampled(factor)
        t_idx = vol2.shape[2] // 2
        t_full = t_idx * factor[2]
        ts2 = loader.read_timeslice(t_full)
        a = ts2[:: factor[0], :: factor[1]][: vol2.shape[0], : vol2.shape[1]]
        b = vol2[: a.shape[0], : a.shape[1], t_idx]  # 3D plane = volume[:,:,t]
        corr = float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])
        print(f"[3] 3D volume[:,:,t] vs strided timeslice corr={corr:.4f} (factor={factor})")
        if corr < 0.95:
            # Also try transposed — if that fixes, axes still wrong
            if a.T.shape == b.shape:
                corr_t = float(
                    np.corrcoef(a.T.ravel().astype(float), b.ravel().astype(float))[0, 1]
                )
                print(f"    corr if timeslice pre-transposed first: {corr_t:.4f}")
            failures.append(
                f"TIME_CONTENT: 3D plane vs 2D timeslice corr={corr:.4f} < 0.95 "
                f"(content mismatch like Image #1 3D vs Time panel)"
            )
        else:
            print("    OK content agrees")

        # --- Check 4: Inline / Crossline 3D vs loader (full-res at mapped index) ---
        il_p = vol2.shape[0] // 2
        xl_p = vol2.shape[1] // 2
        il_num = int(meta.iline_start + il_p * factor[0] * meta.iline_step)
        xl_num = int(meta.xline_start + xl_p * factor[1] * meta.xline_step)
        # Clamp to available
        f = loader._open()
        il_num = int(f.ilines[min(il_p * factor[0], len(f.ilines) - 1)])
        xl_num = int(f.xlines[min(xl_p * factor[1], len(f.xlines) - 1)])

        il_full = loader.read_inline(il_num)  # (nx, nt)
        xl_full = loader.read_crossline(xl_num)  # (ni, nt)
        print(f"[4] inline {il_num} shape={il_full.shape} expect=({meta.n_crosslines},{meta.n_samples})")
        print(f"    xline  {xl_num} shape={xl_full.shape} expect=({meta.n_inlines},{meta.n_samples})")
        if il_full.shape != (meta.n_crosslines, meta.n_samples):
            failures.append(f"IL_SHAPE: {il_full.shape}")
        if xl_full.shape != (meta.n_inlines, meta.n_samples):
            failures.append(f"XL_SHAPE: {xl_full.shape}")

        # Stride-compare to volume planes
        il_ds = il_full[:: factor[1], :: factor[2]]
        sh = (min(il_ds.shape[0], vol2.shape[1]), min(il_ds.shape[1], vol2.shape[2]))
        # Map il_num to volume index
        il_list = list(f.ilines)
        try:
            il_vol_idx = il_list.index(il_num) // factor[0]
        except ValueError:
            il_vol_idx = il_p
        il_vol_idx = min(il_vol_idx, vol2.shape[0] - 1)
        a = il_ds[: sh[0], : sh[1]]
        b = vol2[il_vol_idx, : sh[0], : sh[1]]
        corr_il = float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])
        print(f"    inline 3D vs full-strided corr={corr_il:.4f}")
        if corr_il < 0.95:
            failures.append(f"IL_CONTENT: corr={corr_il:.4f}")

        xl_ds = xl_full[:: factor[0], :: factor[2]]
        sh = (min(xl_ds.shape[0], vol2.shape[0]), min(xl_ds.shape[1], vol2.shape[2]))
        xl_list = list(f.xlines)
        try:
            xl_vol_idx = xl_list.index(xl_num) // factor[1]
        except ValueError:
            xl_vol_idx = xl_p
        xl_vol_idx = min(xl_vol_idx, vol2.shape[1] - 1)
        a = xl_ds[: sh[0], : sh[1]]
        b = vol2[: sh[0], xl_vol_idx, : sh[1]]
        corr_xl = float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])
        print(f"    xline  3D vs full-strided corr={corr_xl:.4f}")
        if corr_xl < 0.95:
            failures.append(f"XL_CONTENT: corr={corr_xl:.4f}")

        # --- Check 5: Image #1 exact label signature (repro of broken state) ---
        # Simulate un-normalized depth_slice orientation
        try:
            raw_depth = np.asarray(f.depth_slice[t_mid], dtype=np.float32)
            print(f"[5] raw segyio depth_slice shape={raw_depth.shape} (before normalize)")
            if raw_depth.shape == (meta.n_crosslines, meta.n_inlines):
                panel_bad = raw_depth.T  # wrong path if depth was already (xl,il) and we .T for panel
                # Wait: if view does read_timeslice().T and read returns raw depth (xl,il),
                # panel = (il, xl) with wrong labels...
                # broken: read returns (xl,il)=(411,641), panel=.T → (641,411)
                panel_broken = raw_depth.T
                info_bad = _build_slice_info(meta, "time", t_mid, panel_broken.shape)
                print(
                    f"    if NOT normalized: panel shape={panel_broken.shape} "
                    f"X={info_bad.axis_h_values[0]:.0f}–{info_bad.axis_h_values[-1]:.0f} "
                    f"Y={info_bad.axis_v_values[0]:.0f}–{info_bad.axis_v_values[-1]:.0f}"
                )
                # Image #1: X~4165-4575, Y~1315-1955
                if abs(info_bad.axis_h_values[-1] - 4575) < 5 and abs(
                    info_bad.axis_v_values[-1] - 1955
                ) < 5:
                    print("    CONFIRMED: un-normalized path reproduces Image #1 axis labels")
        except Exception as exc:
            print(f"[5] depth_slice probe skipped: {exc}")

    finally:
        loader.close()

    print("\n=== RESULT ===")
    if failures:
        print("RED — 3D vs 2D slice contract broken:")
        for fmsg in failures:
            print(f"  FAIL: {fmsg}")
        return 1
    print("GREEN — 3D planes and 2D profiles agree on axis contract + content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
