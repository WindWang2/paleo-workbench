# 01 — GeoViz module inventory (execution-time)

Source of truth: `geo-viz-engine` submodule @ 08851951 (v0.1-web-728),
re-derived at the fork point. Counts exclude tests/fixtures/`__pycache__`.

## Packages

| Package | Product modules | Heaviest modules (lines) | Domain |
| --- | ---: | --- | --- |
| geoviz_common | 6 | paint_scheduler 145, screen_path_cache 97 | shared canvas infra |
| geoviz_map | 16 | canvas 191, layers/wells 130 | web-mercator basemap |
| geoviz_paleo_map | 52 | canvas 955, facies_polygons 693, edit_commands 474, cartography/window 469, export_professional 423 | paleo map + cartography |
| geoviz_plots | 34 | map_edit/api 1176, plot_widget 1132, kriging 647, surface_widget 611 | charts/interp/contour/map-edit |
| geoviz_seismic | 33 | renderer_3d 4100, seismic_view 2563, profile_vd 1259, chunked 881 | seismic 2D/3D viewer |
| geoviz_well_log | 49 | las_preview 620, cross_well_widget 603, canvas 525 | well log + cross-well + sections |
| geoviz_well_seismic_3d | 15 | scene 1390, joint_widget 1134, segy_survey 518 | joint 3D |
| geoviz_well_tie | 12 | synthetic 190, calibration 178, canvas 155 | well tie |
| geoviz_cross_well | 10 | canvas 640, formation_preview 280, picks_model 272 | cross-well correlation |

The Python app shell (`geo-viz-engine/src`) wires 8 nav pages over these
packages; the *native* product is `apps/paleo_workbench_platform`
(pwb-platform) whose hubs are 数据/井/地震(含井震联合 3D)/编图/可视化.

## Native-side geoviz units (libs/*)

geoviz-relevant C++ units at HEAD (61 total units; these carry the viz
domains): `visualization` (well log/cross-well/well-tie cores), `viz_charts`
(axes/colormaps/marching-squares/convex-hull/fence/well-qc + Qt layer),
`geo3d_viz` (viewport/scene-manager/workspace-controller + joint scene),
`seismic_viewer` (slice widget/horizon core/view state/exports/crossplot),
`seismic_io`, `seismic_service`, `seismic_attributes`, `ui_wellseis`
(joint pages/seams), `well_science`, `geomodel`, `science` (C3 kernel),
`ui_pages_preview`, `ui_seqviz` (visualization page).
