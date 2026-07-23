# 3D Geological Modeling & Horizon Sculpting Workbench Design Specification

## Problem Statement

Geologists and geophysicists in Paleo Workbench need to build 3D structural frameworks, perform interactive 3D horizon surface sculpting, incorporate fault throw displacements, and compute closed formation volume integrals.

Currently, building 3D geological models from seismic interpretation horizons and well tops can suffer from surface self-intersections near fault zones, slow isosurface mesh extraction, and lack of real-time volume calculation feedback during interactive horizon editing.

## Solution

Build a deep, high-performance **3D Geological Modeling & Horizon Sculpting Workbench** powered by C++ Marching Tetrahedra isosurface mesh extraction (`marching_cubes_3d`), 3D horizon mesh sculpting (`HorizonSculpting`), fault throw displacement modeling (`FaultDisplacement`), and automated closed formation volume integration.

Key features include:
1. **Accelerated Isosurface Extraction (`marching_cubes_3d`)**: Direct C++ extraction of 3D triangular surface meshes from scalar volume grids for real-time 3D OpenGL viewport rendering.
2. **Interactive Horizon Sculpting (`HorizonSculpting`)**: Local control point deformation with radial basis functions (RBF) to sculpt horizons in areas with sparse seismic picks.
3. **Fault Throw Displacement Modeling (`FaultDisplacement`)**: Displace horizon surfaces across fault planes according to dip angle and throw displacement vectors without topology corruption.
4. **Volumetric Integration**: Calculate gross rock volume (GRV) and net-to-gross formation volumes within closed 3D layer bounds.

## User Stories

1. As a structural geologist, I want to extract 3D isosurface meshes from seismic attribute volumes in milliseconds using C++ Marching Tetrahedra acceleration, so that I can inspect complex 3D geobody boundaries interactively.
2. As an interpreter, I want to edit 3D horizon surfaces using localized brush sculpting, so that I can refine surface geometries near salt domes or channel edges.
3. As a geologist, I want horizon surfaces to displace cleanly across fault planes based on fault throw vectors, so that structural traps are represented accurately without self-intersecting artifacts.
4. As a reservoir engineer, I want to calculate gross rock volume (GRV) enclosed between top and base horizons automatically, so that I can evaluate hydrocarbon volume potential.
5. As a visualizer, I want to toggle between wireframe mesh mode and lit phong-shaded surface mode in the 3D viewport, so that structural relief is highlighted clearly.
6. As a developer, I want pure-Python fallbacks for C++ `marching_cubes_3d` isosurface extraction, so that the 3D modeling features run reliably across all OS platforms.

## Implementation Decisions

1. **Integrated 3D Modeling Page (`GeologicalModeling3DPage`)**:
   - Hosts 3D OpenGL viewport (`SurfaceWidget`) with interactive horizon sculpting tools.
   - Integrates with `VisualizationWorkspace` to load `VizPayload(kind="engine_preview")` or 3D surface meshes.

2. **C++ Isosurface Extractor (`IsosurfaceExtractor`)**:
   - Injected into engine via `set_isosurface_extractor(cpp_marching_cubes_func)`.
   - Generates compact vertex buffers `(vertices, faces, normals)` directly for GPU uploading.

3. **Horizon Sculpting Engine (`HorizonSculpting`)**:
   - Applies local Gaussian or RBF influence spheres to smooth or elevate vertex heights near user brush pointers.

4. **Fault Displacement Engine (`FaultDisplacement`)**:
   - Computes piecewise vertical and lateral vertex offsets along defined fault plane geometries.

## Testing Decisions

1. **Test Philosophy**:
   - Test 3D surface mesh generation, sculpting radius logic, fault displacement vectors, and volume integrations through headless API seams without opening PySide6 OS windows.

2. **Target Modules & Seams**:
   - **`tests/test_horizon_sculpting.py`**: Validates 3D surface mesh vertex sculpting, radius bounds, and smooth annealing.
   - **`tests/test_marching_cubes_3d.py`**: Validates C++ `marching_cubes_3d` mesh extraction, volume integration, and pure-Python parity.
   - **`tests/test_fault_displacement.py`**: Validates fault throw vertex displacement and non-self-intersection invariants.

3. **Prior Art**:
   - Follows pattern of `tests/test_seismic_volume_state.py` and `tests/test_attribute_pipeline.py`.

## Out of Scope

- Full 3D finite-element geomechanical stress modeling.
- Real-time fluid flow reservoir simulation.

## Further Notes

- Fully compliant with `CONTEXT.md` domain vocabulary and existing `VizPayload` data structures.
