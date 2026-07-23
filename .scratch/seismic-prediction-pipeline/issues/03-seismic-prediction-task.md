# 03 — SeismicPredictionTask Dual Tensor Output & VisualizationWorkspace Alpha Blend Integration

**What to build:**
AI prediction task generating discrete `ClassMap` (geological facies codes) and continuous `ProbMap` (confidence probabilities) payloads, rendering opacity-modulated overlays inside `VisualizationWorkspace`.

**Blocked by:** 02 — Asynchronous AttributePipeline Engine & GIL-Release Worker

**Status:** ready-for-agent

- [ ] `SeismicPredictionTask` outputs dual `ClassMap` (uint8) and `ProbMap` (float32) ndarrays.
- [ ] `VisualizationWorkspace` routes prediction payloads to `SeismicHost`.
- [ ] Renders facies discrete color map with continuous probability alpha opacity modulation.
- [ ] Fully verified by unit tests in `tests/test_seismic_prediction_task.py`.
