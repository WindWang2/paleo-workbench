# 03 — Findings

Running log of load-bearing discoveries.

- PR #1099/#1105 "merged" but dropped from main (see 00-current-state §1); re-land required.
- a4953678 held fixes clobbered by #1089 rewrites: IDW tiling, CRS lookup, QGIS rotation, host engine branch, DTW minmax, lineage deque.
- geoviz_seismic lives in geo-viz-engine submodule (own repo, pushable); production convention = feature branch in submodule + pin bump in parent (as #1078 did).
