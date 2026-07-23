# 1. Seismic Prediction & Attribute Pipeline Architecture

* Status: accepted
* Date: 2026-07-23

## Context and Problem Statement

The Paleo Workbench requires high-performance, responsive 3D/2D seismic visualization and attribute computation (3D Coherence, Spectral Decomposition, AI Facies/Fracture Inference).
Previously, seismic state coordination and attribute calculations suffered from UI blocking, un-synchronized 2D/3D slice views, and raw array representations lacking confidence/uncertainty measures.

## Decision Drivers

* **UI Responsiveness**: Large SEG-Y volume attribute calculations (e.g. 500x500x1000 samples) must run off the main GUI thread with full progress feedback.
* **Spatial Parity**: 2D profile slice navigation and 3D OpenGL volume renderings must stay perfectly synchronized in real-time.
* **Uncertainty Transparency**: AI geological interpretation predictions must expose model uncertainty rather than hard binary masks.

## Considered Options

* **Option 1**: Asynchronous `NativeEngineBackend` GIL-Release worker threads + Event-Driven `SeismicVolumeState` observer + Dual `ClassMap`/`ProbMap` tensors with alpha blending.
* **Option 2**: Main thread synchronous attribute calculation + Un-synchronized 2D/3D views + Static binary overlay masks.

## Decision Outcome

Chosen option: **Option 1**, because it maintains a responsive UI under heavy 3D computations, provides seamless 2D/3D slice cross-synchronization via `BinGridGeometry`, and presents continuous probability confidence channels alongside discrete facies classifications.

### Positive Consequences

* GUI thread remains fluid (60 FPS) during long-running C++ attribute calculation tasks.
* Users can instantly toggle between Grid coordinates (Inline, Crossline) and Geographic coordinates (Easting, Northing).
* `VisualizationWorkspace` renders facies predictions with opacity-modulated confidence overlays, highlighting low-confidence inference zones automatically.

### Negative Consequences

* Higher memory footprint from maintaining continuous probability arrays alongside class indices.
* Requires clean observer event cleanup on canvas widget destruction.
