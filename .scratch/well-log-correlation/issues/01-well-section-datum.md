# 01 — WellSectionDatum Multi-Mode Datum Alignment Engine

**What to build:**
Multi-mode depth alignment policy (`align_depths`) supporting Measured Depth (MD/TVD), Subsea Elevation (TVDSS), and Stratigraphic Horizon Flattening ($Z=0$ at target marker top) across multi-well correlation sections.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `WellSectionDatum` supports MD, TVDSS, and Stratigraphic Horizon Flattening ($Z=0$).
- [ ] Shift values ($z_{\text{aligned}} = z_{\text{true}} - z_{\text{datum}}$) are calculated correctly for each well track.
- [ ] Fully verified by unit tests in `tests/test_well_section_datum.py`.
