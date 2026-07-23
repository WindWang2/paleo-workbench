# Paleogeography Workbench Screen Inventory

Source: `古地理图编制系统 (standalone).html`

## Pages

The standalone prototype has 11 icon-rail navigation items (updated from initial 9-page inventory after 3D geological modeling workbench addition):

1. 首页: project dashboard (workflow steps, recent activity, data completeness)
2. 数据: multi-source data management and conversion
3. 测井预测: well log visualization + prediction
4. 地震预测: seismic visualization + prediction
5. 层序格架: sequence stratigraphy framework
6. 岩相古地理: stratigraphic facies & paleogeography
7. 可视化: composite visualization (well/seismic/cross-well)
8. 制备: cartographic data preparation (factor maps)
9. 编图: paleogeographic map composition workbench — balanced layout with left layer tree (editable + reference layers), center edit canvas (with LOD navigation), right reference map dock (CRS-aligned, opacity/visibility), collapsible bottom work area (properties/topology issues/single-factor shelf), canvas-priority mode, structured topology save gate, and indexed snapping
10. 成图审核: QC and export
11. **三维地质建模**: 3D geological modeling workbench — borehole/tunnel/fault 3D rendering with GPU clipping, well-seismic tie calibration, seismic slice overlay, AI consistency advisor, and FLAC3D/Abaqus numerical simulation export

## Design Tokens

- Primary: `#1f6fe0`
- Accent: `#6f47cf`
- Success: `#1f9d57`
- Warning: `#c47e12`
- Surface: `#ffffff`
- Background: `#eef2f7`
- Teal: `#0f93a4` (step 2 indicator, newly discovered)
- Header BG: `#f3f5f9` (menu bar and header toolbar)
- Body BG: `#eef0f4` (main content area; initial inventory `#eef2f7` was close but not exact)