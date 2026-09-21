# 11 — Known limitations

**Classification discipline**: every item below is labelled. Items 1–7 are
**unfinished migration** (Python product capabilities without a native
equivalent) — they are work items, not environment constraints, and they
are the reason the final statement in `12` is scoped the way it is. Items
8+ are genuine environment/boundary notes.

## Unfinished migration (explicit, not hidden)

1. **Arbitrary line** (geoviz_seismic `seismic_view` 任意剖面: polyline
   trace gather at full resolution through the chunked reader). Native
   `SeismicSliceWidget` is inline/crossline/sample only. Full-volume
   attribute kernels are reachable via the volume-level dialog, but the
   arbitrary-line *view* is Python-only. Follow-up: polyline gather in
   `libs/seismic_viewer` (extraction + render geometry + oracle).
2. **2D fence VD profile** (`profile_2d.py`: amplitude strip + wells +
   tops + probe on a fence). Native joint has 3D fence curtains and the
   `FenceExtraction` strips explicitly "shared by the 3D curtain and the
   2D VD view" — the 2D consumer was never built. Follow-up: strip
   renderer reusing seismic_viewer VD mapping.
3. **Professional figure export — geographic graticule/degree frame**
   (`export_professional.py`, reachable from the Python export service).
   The native composer grid is a mm-decorative line grid; no lat/lon
   graticule, degree labels, hemisphere marks, or numeric scale bar of
   that contract. The QGIS layout path exports PNG/PDF/SVG with the
   composer component set. Follow-up: graticule component in
   `mapping_document` composer templates.
4. **Stratal surfaces render untextured** — the native
   `extract_stratal_slice`/`stratal_slice_volume` kernels exist, but the
   product seam (`StratalInput`) has no volume input, so overlays are
   colored planes (Python renders amplitude-sampled attribute planes).
   Follow-up: volume seam through `TiledVolumeAccess` → face_colors.
5. **Joint-page auto-tie is an honest refusal** — the joint context has
   placeholder single-layer records (Python parity; Python's own flow
   fails identically on that data). Real well tie lives in the VIZ-B dock
   (real logs, calibration, auto-tie, report — E2E-3). Advancing this
   needs sonic/density curves piped into the joint scene.
6. **Horizon interpretation entries** (`horizon_interpretations` from the
   Python project document) are not in the native project store schema —
   the stratal combos offer the `.dat` browse path only; the hook returns
   an honest empty list. Follow-up: native project schema extension.
7. **Binding-layer per-kernel cases** for the newly inline 2D kernels
   (sweetness/relative-impedance/振幅 leaf) — kernel-layer oracles exist;
   binding-level assertions are currently covered by the real-.dat E2E
   plumbing + vocabulary tests. Follow-up test batch.
8. **Panel-level structural attributes on 2D sections** (dips/azimuth/
   curvature/C3) require cross-trace neighborhoods; native computes them
   volume-level (dialog → published version) and refuses inline with a
   pointer to that path. Python computes some inline via transposed
   neighbor access; the refusal is the documented capability boundary.

## Environment / boundary notes (not migration gaps)

* PCG64 noise parity remains deferred (`ui_workers` demo seams) — affects
  demo-noise byte parity only, never product data.
* Windows/MSVC validation not executed this session (Linux only); the
  platform test matrix carries the Windows families on CI.
* Real-GL pixel-level screenshot comparison: the product ran on a real X
  display without errors and offscreen GL-less paths degrade honestly;
  automated pixel comparison remains future work (as on main).
* Windows-side `python_free` ldd checks are POSIX-only by design
  (deploy-tree review covers Windows).
* `#1443` (closure_science second-run crash) and the platform lifecycle
  issues are owned by the parallel session's merged #1453 line; this
  branch verified the merged tree's full suite green.
