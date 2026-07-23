# 01 — C++ LASParserProvider & Min-Max LOD Curve Downsampling

**What to build:**
C++ accelerated memory block extraction for LAS files (`fast_las_parse_data`) with 4-point LOD downsampling, NULL value handling, and pure-Python fallback parity validation.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `LASParserProvider` handles fast memory block extraction for LAS files.
- [ ] 4-Point Min-Max curve downsampling maintains 60 FPS viewport rendering.
- [ ] NULL missing values handled correctly.
- [ ] Fully verified by unit tests in `tests/test_las_parser_provider.py`.
