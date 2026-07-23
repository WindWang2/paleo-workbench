# 02 — CorrelationSectionResult Execution & Polygon Band Pipeline

**What to build:**
End-to-end `execute()` method calculating shifts, generating inter-well quad polygons, and evaluating DTW alignment paths into a unified `CorrelationSectionResult` model.

**Blocked by:** 01 — StratigraphicCorrelationEngine Fluent Builder Core Engine

**Status:** ready-for-agent

- [ ] `execute()` calculates shifts, quad polygons, and DTW alignment paths.
- [ ] `recommend_top()` produces DTW formation top depth suggestions with confidence scores.
- [ ] Fully verified by unit tests in `tests/test_stratigraphic_correlation_engine.py`.
