# 02 — Null / Unit / Depth Correctness

## Status: implemented (§3–4, P0-3 + P1-1/2/5)

### Depth units — before → after
| site | before | after |
|---|---|---|
| viz/well_log_load.detect_depth_unit | `return "m"` for unknown | `None` (unknown) + `detect_depth_unit_info` (declared flag) |
| curve_interpretation.depth_unit_normalize | empty unit → "m" no-op | `UnknownDepthUnitError` |
| curve_interpretation.depth_shift | raw meters add on any axis | axis-unit conversion; refuses unknown |
| correlation_overlay | empty unit → meters placement | ft conversion via whitelist; unknown refuses placement (typed warning) |
| engine adapter | unknown → "m" silently | `depth_unit_declared=False` + `depth-unit:unknown` diagnostic (bridge label stays for rendering) |
| well_tie_host sonic integration | unknown → meters | refuses (returns None) |
| canvas depth cursor | unknown → meters publish | fails closed `depth-unit:unknown` |
| harness well.create_display | hardcoded "m" | honest null + declared flag |

### Nulls
- three sentinel defaults existed (−999.25 LAS / −999.0 fast API / −9000 XML
  threshold) with a 1e-6-vs-exact match mismatch. `NullPolicy` types the
  four states; the derived-LAS writer now RECORDS injection
  (`derived_injected`), declared sentinels preserved (R1-M1 intact).
- gaps: `interp_gap_preserving` (resample) never bridges interior NaN
  spans; engine submission keeps NaN values on finite depths → native
  run-splitting renders gaps with fallback parity (P0-1).

## Known residue (documented, not fixed this round)
- the LAS preview loader still defaults `null_value=-999.25` when a file
  declares none (ResForm-compatible v1 whitelist contract); the derived
  pipeline records its policy, the preview path only warns.
