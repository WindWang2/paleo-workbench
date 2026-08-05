# T14 geometry golden fixture

Fixed single-well sample for **WellPlot Desktop** export / screen layout
geometry checks (issue #302 / T14). First-ship subset only — not the full
§16 0.1 mm matrix (that is Export B1 / T16).

## Dataset

| Field | Value |
|-------|--------|
| File | `T14_GOLDEN_V1.las` |
| Well | `T14-GOLDEN-V1` |
| Depth | 1000.0 – 1010.0 m, step 1.0 |
| Curves | GR, RT, RHOB |
| Template | `std-gr-rt-den` (depth + GR + RT + DEN) |

Committed in-repo so CI does not download external data.

## What is asserted

See `well_log_workstation/geometry_golden.py` and
`tests/test_well_log_workstation_geometry_golden.py`:

1. Template track **width fractions** match the golden table.
2. Qt-paint **export layout** track left/width in physical **mm** (A4
   landscape content box) within **0.1 mm** of the frozen golden edges.
3. Depth → Y mapping endpoints (and mid) within 0.1 mm.
4. Optional SVG viewBox page box matches `PageSpec` mm.

## Updating the golden

If intentional layout constants change (margins, header band, page size),
update the frozen numbers in `geometry_golden.py` (`GOLDEN_*`) in the same
commit and note why. Do not loosen `TOL_MM` without an ADR relative to
§16 / Export B0.
