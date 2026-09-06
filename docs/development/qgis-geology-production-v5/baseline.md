# Baseline — QGIS 地质编图生产线 v5

Branch: `feat/qgis-geology-production-v5`，基线 commit `de4c9971`（origin/main，含 #1198–#1202 五个并行 v5 方向合入）。
Worktree: `/home/kevin/projects/paleo-wt-qgis-geology-production-v5`。
审计日期：2026-09-06（三路并行源码审计：科学计算链 / 制图·产品·桥接层 / 文档·构建环境）。

## 权威图（现状）

```
科学结果权威:  Well/Factor inputs → workflow/factor_interpolation.py → geoviz 插值内核
              → FactorGridResult(workflow/factor_grid_result.py:239) → grid_artifact NPZ(catalog)
显示权威(2D):  QGIS（vendored 4.2.0, ADR 0059 专业 authoring 权威）
              → MapRenderSnapshot → QgisMapRenderBackend(桥) / FallbackMapRenderBackend(QPainter)
编辑权威:      Python（VectorEditSession + 命令栈）；QGIS 工具只发回调（edit_tools.hpp 契约）
树语义回写:    QgisLayerTreePanel → parse_tree_change → Python 权威模型（visibility/order/rename）
成图排版权威:  mapping/composer/ 组件图（21 ElementType, schema v2）→ 自研 SVG 渲染 → QSvgRenderer/QPdfWriter
产品权威:      MapProductRecord(project/models.py:476) + catalog OUTPUT version + workflow/versioning.py VersionSet
```

## 科学计算链现状

| 能力 | 位置 | 状态 |
|---|---|---|
| factor extraction | `mapping/geological_pipeline/pipeline.py:164` `extract_factors` | 完整（QC 过滤、坐标键族审计 #1150）；派生因子（砂地比=Hs/Ht、厚度=base−top）显式但**无 derived 溯源标记**（pipeline.py:258-301） |
| 井表值列选择 | `workflow/well_table.py:33` | z→Rs→Ht 按行回退已废除（#1151），缺列行跳过并计数 |
| IDW #1（任务管线权威） | geo-viz `.../interpolation/idw.py:195` | 全样本 + fault barrier（:81） |
| IDW #2（pipeline kNN） | `mapping/geological_pipeline/interpolator.py:114` | cKDTree kNN + 半径，与 #1 语义不同（双轨） |
| constrained IDW | `workflow/constrained_idw_adapter.py:538` → vendored haiyou engine | 最重实现（边界多边形/断层消隐/方向廊道/declustering/井重锚定） |
| Ordinary Kriging | geo-viz `factor/kriging.py:311/528` | 真 OK + 方差；`_pure_numpy_kriging` fallback（interpolator.py:458，有质量测试） |
| variogram | geo-viz `factor/kriging.py:157/222` | 经验 + spherical/exponential/gaussian 拟合（完整）；**无各向异性变差函数** |
| spline | geo-viz `interpolation/scipy_grid.py:14` | scipy cubic 薄包装，失败降级 nearest 并标 degraded |
| directional trend | geo-viz `interpolation/directional.py:163` | 各向异性高斯核（真实）；克里金不含各向异性 |
| fault barrier | 仅 IDW backend + haiyou | **克里金不支持** |
| CV | LOO R²（kriging.py:446 闭式；factor_interpolation.py:223 ≤64 点）、约束 IDW 4 折 R² | **只有 R²；无 RMSE/MAE/ME/residual map；批量 plan 无 CV** |
| FactorGridResult | `workflow/factor_grid_result.py:239` | grid/variance/crs/unit/provenance/boundary 完整；**主管线 from_engine_dict 不传 unit**（factor_interpolation.py:421/476/728） |
| contour | 3 套：`geological_pipeline/contouring.py`（MapDocument 路径）、`workflow/contour_draft.py:249`（ContourDraft 权威）、haiyou 精化（约束 IDW 专属） | 无单一权威 |
| polygonization/facies | `geological_pipeline/polygonization.py:223` | 阈值分级 + 格网边界追踪；**无小多边形过滤、无用户域 clip、孔洞归属弱兜底**（:210-211） |
| CRS | `FactorGridResult.crs` 显式契约（None=禁止猜测） | **contouring.py:338、polygonization.py:242,327 在 crs=None 时静默回退 "EPSG:4326"**；插值对 lat/lon 按等距平面算距离 |
| 多因素融合 | 不存在 | 相带仅单因子阈值；层级（相/亚相/微相）只消费不生成 |

## 制图/产品/桥接层现状

| 能力 | 位置 | 状态 |
|---|---|---|
| MapDocument/MapLayer | `mapping/layers.py:497` + snapshot DTO（map_render_backend.py:69/:101） | 完整（8 类图层、to/from_snapshot） |
| PaleoMapDocument | `project/models.py:344`（schema v1 + domain_migration） | 完整 |
| MapProduct | `workflow/map_product.py:81/175` + `project/models.py:476` | assemble/describe 有（fail-closed：拒 mock/无 grid）；**clone/rerun/compare/publish 无产品级 API**；stale 检测在 `workflow/freshness.py:151` |
| 版本/promote/supersede | `catalog/service.py:2864/2937`、`workflow/versioning.py:107` | catalog 层完整；产品层需跨模块手工拼装 |
| QGIS mirror | `ui/qgis_stack/mirror.py:11`（单向要素）+ `tree_sync.py:19`（树回写） | 完整；echo 防护双层（C++ SuppressGuard:509 + Python `_publishing`） |
| 桥 API 面 | `native/qgis_render_bridge/src/`（bridge/stack/gui/geometry/style 五块，~60+ 方法） | 完整；`export_vector`（SVG/PDF, qgis_render_bridge.cpp:730）；vendored 链接 setup.py（PALEO_QGIS_* 环境变量） |
| vendored QGIS | `/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor`（4.2.0, 1.1GB, core/gui/analysis+srs.db 齐全） | **可复用**（PALEO_QGIS_REUSE_VENDOR=1 + PALEO_QGIS_BUILD_DIR）；桥扩展 .so 未编译 |
| **setup.py bug** | `native/qgis_render_bridge/setup.py:156/:229` | **NameError：`resource_database` 未定义**（有产物时 already_built 判断即崩） |
| symbology | QGIS 路径=QgsFeatureRenderer XML（style_codec.cpp）；fallback=Python 自绘（renderers.py） | 双栈；**色带未映射 QgsColorRamp/QgsRasterShader**（标量层预栅格化 RGBA 进 GeoTIFF 镜像） |
| labeling | style_codec.cpp:333-377 QgsPalLayerSettings + data-defined | 完整（QGIS 路径） |
| composer 组件图 | `mapping/composer/models.py`（21 ElementType, schema v2）+ components.py（undo/redo/z序）+ templates.py（9 模板）+ renderer.py（SVG 自绘） | 组件体系完整；**MAIN_MAP 内容走旧 Python 渲染链 → QGIS 专属符号在成图上降义** |
| **无 QgsLayout** | 全仓 0 命中 QgsLayout/QgsPrintLayout | legend/scalebar/north arrow 为数据驱动自绘，非 QgsLayoutItem |
| 图层编辑 | `mapping/vector_layer.py:212/309`（命令栈）、geometry_service、topology、map_tools、原生 Pwb 工具 | 完整；属性表部分（无过滤/表单，map_attribute_table.py） |
| 导出 | `ui/map_export_worker.py:122`（画布→render_sync；否则 painter）；composer/export.py（SVG/PNG/PDF 毫米页） | **providers/builtin/map_export.py:251 硬编码 prefer_native_renderer=False（fallback-as-production）**；ui/map_export_worker.py QGIS 失败静默降级 painter |
| 成图 QA | `workflow/qc.py BASIC_QC_RULES:17`（6 条文档内容规则） | **无 legend completeness/renderer mismatch/CRS mismatch/合成页 QA** |
| fallback 防混淆 | qgis_backend_probe（map_render_backend.py:2299）+ ADR 0057 fallback 标记 | 机制完整，但上述两处反例存在 |

## 构建与测试环境（本机事实）

- vendored QGIS 4.2.0 build：`/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor`（与当前 worktree `third_party/qgis` UPSTREAM.md commit 一致 → 允许跨 worktree 复用）。
- 桥扩展编译命令：`PALEO_WITH_QGIS_RENDERER=1 PALEO_QGIS_REUSE_VENDOR=1 PALEO_QGIS_BUILD_DIR=<vendor> PALEO_QGIS_CMAKE_PREFIX=/usr/lib/cmake/Qt6 python3.13 -m pip install -e native/qgis_render_bridge`（pyproject.toml:65 文档化路径）。
- Python：`/opt/miniconda3/bin/python3.13`，pybind11 3.0.4；用户站 editable 安装族（paleo_workbench/geo_viz/...）；pytest `pythonpath=[".", ...]` 保证 worktree 代码优先。
- 测试运行器：`/home/kevin/projects/paleo_project/run_env.sh <worktree> [pytest args]`（offscreen + 软件 GL + PYTHONPATH 注入 geo-viz/well-log）。
- pytest markers：`qgis`（需桥，conftest 自动 skip；`PALEO_REQUIRE_QGIS=1` fail-closed）、`slow`、`opengl`、`capacity`。
- 文档约定：v5 四件套（baseline/target-state/decisions/verification，中文可勾选清单 + D 编号决策）；仓库级 ADR 编号另计（0057/0059 为 QGIS 权威权威文件）。

## 本 Goal 关闭的缺口（按里程碑映射）

1. M1 — unit 未贯通主管线、派生因子无溯源标记、单因素图无统一产品契约。
2. M2 — 无 RMSE/MAE/ME/residual、批量 plan 无 CV、克里金无诊断出口整合。
3. M3 — contour/facies 静默 EPSG:4326 回退、mask 未贯穿全链、等距平面假设无策略声明。
4. M4 — 无小多边形参数化处理、无用户域 clip、孔洞弱兜底。
5. M5 — 多因素融合完全缺失。
6. M6/M7 — 无 QgsLayout、MAIN_MAP 成图内容不走 QGIS、屏显/成图无一致性保证。
7. M8 — 属性表部分（过滤/表单缺）。
8. M9 — 样式库有基础（VectorStyle JSON + QGIS renderer XML）但无地质语义库整合。
9. M10 — MapProduct 无 clone/rerun/compare。
10. M11 — 无头生产导出绕开 QGIS（fallback-as-production）、导出选项不完备。
11. M12 — 成图 QA 空白。
12. 前置缺陷 — setup.py NameError 阻断桥构建。
