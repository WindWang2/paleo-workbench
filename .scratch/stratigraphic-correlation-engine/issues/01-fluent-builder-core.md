# 01 — StratigraphicCorrelationEngine Fluent Builder Core Engine

**What to build:**
Fluent API chaining (`with_wells`, `with_datum`, `with_layout`, `with_dtw_config`) and sub-engine delegation in `StratigraphicCorrelationEngine`.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `StratigraphicCorrelationEngine` supports fluent configuration chaining (`with_wells`, `with_datum`, `with_layout`, `with_dtw_config`).
- [ ] Sub-engine dependencies (`WellSectionDatum`, `DTWLogMatcher`, `FormationTopCorrelator`) are injected and configurable.
- [ ] Fully verified by unit tests in `tests/test_stratigraphic_correlation_engine.py`.
