# ADR 0002: 3D Geological Modeling & Horizon Sculpting Architecture

* **Status**: Accepted
* **Date**: 2026-07-23
* **Deciders**: Paleo Workbench Core Architecture Team

## Context

In 3D geological framework modeling and seismic interpretation, geoscientists need to:
1. Interactively sculpt 3D horizon surface meshes near salt domes, channel edges, and sparse pick regions.
2. Incorporate fault throw displacements ($\text{Dip}, \text{Strike}, \text{Throw}$) without causing surface mesh self-entanglement.
3. Compute precise closed formation volume integrals ($V_{reservoir}$) between top and bottom horizons across fault blocks.

Traditional 2D grid matrix representations ($Z_{grid}[i, j]$) fail on steep dips, vertical fault offsets, and non-grid-aligned boundaries. Furthermore, cloning full 500,000+ vertex arrays on every interactive brush drag causes UI stuttering.

## Decision

We adopt a 3D Polyhedron Mesh architecture composed of three core modules:

1. **`SculptableHorizonMesh`**: Represents 3D horizons as 3D vertex position arrays `(N, 3)` and triangle face indices `(M, 3)`. Employs a **Sparse Delta Patch Undo/Redo Stack** that stores only modified vertex IDs and height deltas ($\Delta z$) within the radial brush influence sphere ($R$), enabling instant Undo/Redo without full mesh array duplication.
2. **`FaultDisplacement`**: Implements a kinematic vector field engine $\vec{D}(\vec{x})$ that calculates spatial displacement vectors across hanging-wall and footwall blocks, applying smooth distance decay to horizon vertices across fault planes.
3. **`FormationVolumeIntegrator`**: Automatically constructs vertical side-wall mesh strips between top ($H_{top}$) and bottom ($H_{bot}$) horizons to form a watertight 3D Polyhedron Mesh, evaluating reservoir volume via Gauss Divergence Theorem surface integrals:
   $$\iiint_V dV = \frac{1}{3} \iint_{\partial V} (x n_x + y n_y + z n_z) \, dA$$

## Consequences

### Positive
- Supports arbitrary 3D deformed geometries, steep structural flanks, and fault displacement boundaries.
- Sparse delta patch undo/redo enables 60 FPS interactive brush sculpting on 500,000+ vertex meshes.
- Mathematically exact reservoir volume integration on complex structural traps.

### Negative / Trade-offs
- Higher initial algorithm complexity compared to 2D pixel thickness summation.
- Requires side-wall topology stitching for watertight Polyhedron Mesh construction.
