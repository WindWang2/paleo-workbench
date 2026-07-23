# 03 — StratigraphyCorrelationPage Engine Wiring & UI Integration

**What to build:**
Replaces manual multi-module orchestration calls in `StratigraphyCorrelationPage` and `WellSectionHost` with `StratigraphicCorrelationEngine` pipeline calls.

**Blocked by:** 01 — StratigraphicCorrelationEngine Fluent Builder Core Engine, 02 — CorrelationSectionResult Execution & Polygon Band Pipeline

**Status:** ready-for-agent

- [ ] `StratigraphyCorrelationPage` wires correlation actions through `StratigraphicCorrelationEngine`.
- [ ] Fully verified by tests in `tests/test_well_section_workbench.py`.
