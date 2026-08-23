# Paleo Workbench GIS/QGIS 融合与智能制图审查报告 (GIS & Mapping Review)

## 1. QGIS 思想融合与 GIS 核心能力审查

### 1.1 GIS 核心要素对齐情况

| GIS 核心能力 | Paleo Workbench 实现模块 | QGIS 对标组件 | 融合程度与评估 |
|---|---|---|---|
| **图层模型 (Layer Model)** | `mapping/vector_layer.py`, `layer_model_core.cpp` | `QgsVectorLayer`, `QgsRasterLayer` | 良好。实现了点、线、面、标量栅格的不可变快照与增量版本管理。 |
| **坐标参考系 (CRS & Proj)** | `mapping/geometry_schema.py`, PROJ/GDAL 绑定 | `QgsCoordinateReferenceSystem` | 良好。严格区分 SourceCRS 与 ProjectCRS，支持动态重投影。 |
| **符号与样式引擎 (Symbology)** | `mapping/map_styles.py`, `mapping/qgis_style.py` | `QgsFeatureRenderer`, `QgsSymbol` | 良好。支持单一符号（Single Symbol）、分类符号（Categorized）、渐变色阶（Graduated）及规则符号（Rule-based）。 |
| **渲染管线 (Render Pipeline)** | `mapping/map_render_backend.py`, `qgis_render_bridge` | `QgsMapRendererCustomPainterJob` | 优异。支持 QPainter Fallback 与原生 QGIS C++ 渲染无缝切换。 |
| **拓扑编辑与校验 (Topology)** | `mapping/topology.py`, `feature_editor.py` | QGIS Advanced Digitizing & Snapping | 良好。支持自动捕捉、公共边同步拖拽、自相交自愈与事务回滚。 |
| **空间属性查询 (Query)** | `mapping/feature_query_index.py` | `QgsSpatialIndex` (R-Tree) | 良好。构建了内存 R-Tree 索引，支持百万级图元毫秒级点选与框选。 |

---

## 2. 编图系统与 Map Composer 模板架构审查

### 2.1 地图模板体系 (Map Template Standard)
古地理图的工业化编制不仅要求绘制地质要素，还必须具备符合国家/行业制图规范的完整整饰要素。

```
Map Template (统一地图排版模板)
├── Main Map Canvas (主图画布，支持多图层叠加、动态比例尺联动、视口裁剪)
├── Map Title & Subtitle (主标题、副标题、地层层位、编制单位)
├── Dynamic Legend (智能图例，自动根据图层可见性与符号规则过滤生成)
├── North Arrow (真北/磁北指北针，支持多种经典地质样式)
├── Scale Bar (多段制/线段式比例尺，米/千米单位自适应换算)
├── Coordinate Grid / Graticule (经纬度网格、高斯-克吕格投影千米网格与角标)
├── Geological Time Scale Header (国际/行业标准地质年表色块标识)
├── Annotation & Callouts (地名标注、勘探构造单元注记、防遮挡避让)
├── Data Source & Lineage Block (数据来源、资产版本 SHA-256、编制人员签署)
└── Layout & Margins (A0-A4 标准图幅纸张、出血线、DPI 分辨率控制)
```

### 2.2 现状差距与重构要点
- 目前系统的制图导出功能偏向于直接保存视口画布（Canvas Viewport Dump），缺乏独立的**打印排版器 (Print Composer Engine)**。
- 需构建声明式 `MapCompositionDocument` 数据模型，使地图布局与主画布解耦，支持模板保存、复用与批量脚本导出。

---

## 3. 单因素图 (Haiyou Visualization) 深度融合分析

### 3.1 单因素分析要素分类

```mermaid
graph LR
    subgraph Data_Inputs ["地质数据输入"]
        Wells["测井解释点 (孔隙度/渗透率/砂地比)"]
        Faults["断层边界/构造带多边形"]
        BasinBoundary["盆地/凹陷有效沉积边界"]
    end

    subgraph Compute_Engine ["约束计算引擎 (haiyou_constrained_idw)"]
        DirectionCorridor["各向异性方向廊道混合"]
        LOS_Testing["断层线段视线遮挡阻隔"]
        Batched_IDW["批量反距离加权网格插值"]
        StadiumBuffer["断层胶囊体缓冲区消隐"]
        WellResidual["井点残差局部无缝锚定"]
    end

    subgraph QGIS_Unified_Pipeline ["统一 GIS 符号与渲染管线"]
        ContinuousRaster["连续标量场着色 (GridRenderCore)"]
        IsolineContour["等值线提取与光滑注记 (Contour)"]
        CategorizedFacies["相带多边形拓扑提取 (Facies Rings)"]
        SymbolicOverlay["散点气泡图 / 玫瑰图 / 饼图叠加"]
    end

    Data_Inputs --> Compute_Engine
    Compute_Engine --> QGIS_Unified_Pipeline
```

### 3.2 融合演进方案 (Unified Single-Factor Pipeline)
1. **统一数据抽象**:
   - 单因素插值输出由简单的 NumPy 二维数组升级为标准的 `ScalarRasterLayer`，携带仿射变换矩阵（GeoTransform）与空间参考系（CRS）。
2. **多维度单因素图支持**:
   - **连续标量热力图**: 孔隙度、地层厚度、砂地比的连续色阶渲染。
   - **等值线图 (Contour)**: 结合 Marching Squares 自动生成平滑等值线矢量图层与高程注记。
   - **多边形相带图 (Facies Polygons)**: 基于阈值划分相带边界，自动转换为具备完整拓扑的矢量图斑。
   - **井点统计符号图 (Proportional / Pie Symbols)**: 在井位上叠加岩性饼图、砂岩厚度柱状图或古水流玫瑰图。

---

## 4. 智能编图升级路线图

1. **实现 Map Composer 核心排版引擎**:
   - 建立 `paleo_workbench/mapping/composer/` 模块，支持标准图幅定义与整饰要素自动生成。
2. **打通单因素计算到矢量拓扑编图的桥梁**:
   - 实现从“单因素等值线网格”一键转换为“古地理制图编辑图层”，支持地质专家在插值结果基础上进行交互式拓扑微调与笔刷修形。
3. **支持全矢量无损工业出版格式导出**:
   - 保证输出的 PDF/SVG 文件中文字保留为可搜索文本字体、图斑保留为精确贝塞尔曲线路径、图例与比例尺保持矢量保真度。
