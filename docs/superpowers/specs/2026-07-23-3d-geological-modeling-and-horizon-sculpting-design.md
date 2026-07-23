# 3D Geological Modeling & Horizon Sculpting Workbench Specification

## Problem Statement

Geologists, geophysicists, and reservoir engineers in Paleo Workbench need to build 3D structural framework models, perform interactive 3D horizon surface sculpting, incorporate fault throw displacements, and compute closed formation volume integrals.

Currently, building 3D geological models from seismic horizons and well tops can suffer from:
1. **Self-Intersections & Discontinuity Artifacts**: Horizon meshes near fault zones often self-intersect or fail to represent vertical fault throw offsets accurately.
2. **High Memory Overhead during Sculpting**: Interactive brush deformation on 500,000+ vertex 3D meshes can cause UI stuttering or high memory consumption if full mesh arrays are duplicated on every mouse drag.
3. **Inaccurate Volumetric Estimates**: Simplified 2D grid cell thickness summation ($\sum \Delta z \cdot \Delta x \cdot \Delta y$) fails on steep dips, vertical fault offsets, and non-grid-aligned boundaries, producing unreliable hydrocarbon volume estimates.

## Solution

Build a deep, high-performance **3D Geological Modeling & Horizon Sculpting Workbench** powered by:
1. **Stateful Horizon Mesh & Delta Patch Undo (`SculptableHorizonMesh`)**: Represents 3D horizon surfaces as 3D vertex position arrays `(N, 3)` and triangle face indices `(M, 3)` with a **Sparse Delta Patch Undo/Redo Stack** that records only modified vertex IDs and height deltas ($\Delta z$) within the radial brush influence sphere ($R$), enabling 60 FPS interactive sculpting without full mesh cloning.
2. **Kinematic Fault Displacement Vector Field (`FaultDisplacement`)**: Applies a distance-decay kinematic displacement vector field $\vec{D}(\vec{x})$ across hanging-wall and footwall blocks based on dip angle, strike, and throw magnitude, deforming horizon meshes cleanly across fault boundaries without self-entanglement.
3. **Gauss Divergence Theorem Formation Volume Integrator (`FormationVolumeIntegrator`)**: Constructs vertical side-wall mesh strips between top ($H_{top}$) and bottom ($H_{bot}$) horizons to form a watertight 3D Polyhedron Mesh, evaluating exact reservoir volume via Gauss Divergence Theorem surface integrals:
   $$\iiint_V dV = \frac{1}{3} \iint_{\partial V} (x n_x + y n_y + z n_z) \, dA$$
4. **Accelerated Isosurface Extraction (`marching_cubes_3d`)**: Leverages C++ Marching Tetrahedra algorithm for real-time 3D isosurface mesh extraction from scalar volume fields.

## User Stories

1. As a structural geologist, I want to extract 3D isosurface meshes from seismic attribute volumes in milliseconds using C++ Marching Tetrahedra acceleration, so that I can inspect complex 3D geobody boundaries interactively.
2. As an interpreter, I want to edit 3D horizon surfaces using localized radial brush sculpting, so that I can refine surface geometries near salt domes or channel edges.
3. As a geologist, I want to undo and redo interactive sculpting operations instantly without lag, so that I can experiment with alternative surface interpretations safely.
4. As an interpreter, I want horizon surfaces to displace cleanly across fault planes based on fault throw vectors, so that structural traps are represented accurately without self-intersecting artifacts.
5. As a reservoir engineer, I want to calculate exact gross rock volume (GRV) enclosed between top and base horizons across fault blocks, so that I can evaluate hydrocarbon volume potential accurately.
6. As a visualizer, I want to toggle between wireframe mesh mode and lit phong-shaded surface mode in the 3D viewport, so that structural relief is highlighted clearly.
7. As a developer, I want pure-Python fallbacks for C++ `marching_cubes_3d` isosurface extraction, so that the 3D modeling features run reliably across all OS platforms.

## Implementation Decisions

- **`SculptableHorizonMesh` Data Structure & Undo Stack**:
  - Encapsulates 3D vertex positions `(N, 3)`, triangle face indices `(M, 3)`, and grid spatial metadata.
  - Implements a sparse delta patch stack where each sculpt stroke records `{modified_vertex_indices, old_z_values, new_z_values}`.
  - `undo()` and `redo()` restore modified vertices in-place without re-allocating memory for unmodified vertices.
- **`FaultDisplacement` Vector Field Engine**:
  - Computes spatial displacement vector maps $\vec{D}(\vec{x})$ for hanging-wall vs footwall blocks.
  - Applies smooth Gaussian distance decay along fault plane normal vectors to avoid mesh self-intersection artifacts near fault boundaries.
- **`FormationVolumeIntegrator` Polyhedron Integrator**:
  - Automatically identifies top ($H_{top}$) and bottom ($H_{bot}$) boundary edges and generates vertical side-wall quadrilateral/triangle strips.
  - Verifies watertight mesh closure before evaluating Gauss Divergence Theorem surface integrals.
- **`GeologicalModeling3DPage` Host Surface**:
  - Hosts 3D OpenGL viewport (`SurfaceWidget`) with interactive horizon sculpting tools.
  - Integrates with `VisualizationWorkspace` to load `VizPayload(kind="engine_preview")` or 3D surface meshes.
- **ADR Compliance**:
  - Fully compliant with `docs/adr/0002-3d-geological-modeling-and-horizon-sculpting-architecture.md` and `CONTEXT.md` vocabulary (`SculptableHorizonMesh`, `FaultDisplacement`, `FormationVolumeIntegrator`).

## Testing Decisions

- **Test Philosophy**:
  - Test 3D surface mesh generation, sculpting radius logic, fault displacement vectors, and volume integrations through headless API seams without opening PySide6 OS windows.
- **Target Modules & Seams**:
  - **`tests/test_horizon_sculpting.py`**: Validates `SculptableHorizonMesh` vertex sculpting, radial influence bounds, smooth annealing, and sparse delta patch undo/redo history.
  - **`tests/test_fault_displacement.py`**: Validates `FaultDisplacement` kinematic vector field calculations, fault throw offsets, and non-self-intersection invariants.
  - **`tests/test_marching_cubes_3d.py`**: Validates C++ `marching_cubes_3d` mesh extraction, watertight mesh validation, `FormationVolumeIntegrator` surface integration accuracy, and pure-Python parity.
  - **`tests/test_geological_modeling_3d_page.py`**: Validates PySide6 page layout, 3D viewport controls, and snapshot exports.
- **Prior Art**:
  - Builds on `tests/test_seismic_volume_state.py` and `tests/test_map_edit_scene.py`.

## Out of Scope

- Full 3D finite-element geomechanical stress & strain modeling.
- Real-time multiphase fluid flow reservoir simulation.

## Further Notes

- The sparse delta patch undo stack ensures that 500,000+ vertex meshes maintain <1ms per-stroke undo/redo latency, preserving 60 FPS viewport rendering performance.
