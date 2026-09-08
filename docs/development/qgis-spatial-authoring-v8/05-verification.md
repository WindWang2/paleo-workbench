# 05 — Verification

运行环境：本 worktree `.venv`（Python 3.12.13，PySide6 6.8.3），
桥 0.4.0a0（链接 C:/deps Qt 6.8.0 + authoring 自包含 vendor build 复用，
`PALEO_QGIS_REUSE_VENDOR=1`）。测试入口 `scripts/run_qgis_env.py`
（loader 配方 + MSVCP 预钉经 sitecustomize 注入子进程，见 03-decisions D6）。

## 新增测试（V8）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| tests/test_qgis_provider_fields_v8.py | W1：provider schema 应用（类型/别名/约束/控件/默认值）、GeoJSON properties typed 往返（全量 + delta）、schema 漂移重建、legacy 回退清理、畸形 wire fail-closed、manifest feature flags、W4 指示器、W5 legend filter 工程树不变 | qgis-marked ✅ |
| tests/test_qgis_row_indicators_v8.py | W4：kinds 词汇、面板→原生指示器投影、干净态清除、未知 kind 双重防御 | qgis-marked ✅ |
| tests/test_qgis_lifecycle_stress_v8.py | W6：100× 工程切换无层泄漏、100× 工具激活循环、30× 树视图重建、指示器共存循环、StackEvents 析构竞态、attach 契约 | qgis-marked ✅ |
| tests/test_topology_compound_undo.py | W2：复合撤销/重做原子性、冲突拒绝非静默、宏降级、丢弃、工作站集成 | headless ✅ |
| tests/test_geometry_authority_v8.py | W3：PIP 洞/多 part/边界/退化、向量化 parity 全格点、inclusive 变体、线段距离、extent、centroid/bbox、composite hit-test、workarea 分类、geomodel 掩膜 | headless ✅ |
| tests/test_layout_export_mapping.py（扩展） | W5：filter_layers emit、include 表词汇、旧桥降级预警 | headless ✅ |

## 既有回归（受影响面）

分批通过 `scripts/run_qgis_env.py`（等价 V7 的批驱动双腿法）：

- W2 面：test_topology_service / test_composite_editing /
  test_workstation_authoring_kernel / test_qgis_v7_authoring ✅
- W3 面：test_map_interaction / test_geomodel_builders / test_cartographic_qa /
  test_geometry_operations / test_map_layers / test_map_document_snapshot /
  test_layout_export_mapping / test_polygon_quality_adversarial /
  test_domain_binding（分类）✅
- W1/W4/W5 面：test_qgis_layer_schema / test_mirror_delta_publish /
  test_qgis_layer_panel / test_qgis_layout_export /
  test_qgis_mapstack_lifecycle / test_qgis_select_identify ✅
- W6 面：test_qgis_canvas_tool_wiring / test_qgis_mapstack_tools ✅

完整清单与逐文件退出码见 06-performance 附录（批驱动 JSON）。

## 已知环境性失败（非本 goal 引入，stash 前后对照验证）

- tests/test_layer_lifecycle.py 3 项：需要 geoviz C++ 扩展
  （layer_model_core/grid_render_core，本 worktree 未编译原生 geoviz 腿；
  CI 覆盖）。已用"改动前后同失败"法验证与本 goal 无关。
- 标量栅格（osgeo）路径测试：默认配方下 osgeo 与 vendor gdal 的 DLL 名
  冲突无解 → 诚实跳过；conda-Qt 配方（PALEO_QGIS_CONDA_QT=1）或 CI qgis
  腿覆盖（见 08-known-limitations §3）。
