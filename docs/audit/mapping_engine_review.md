# Paleo Workbench 智能编图系统专项审查报告 (Mapping Engine Review)

## 1. 智能编图流程分析：从数据结果到地图表达

在古地理图件编制中，从底层离散数据到出版级地图的转换是地学系统的核心价值链条。

```mermaid
graph TD
    Data[离散井点 / 地震属性 / 测井解释表] --> Intent[AI 意图解析 / 编图任务触发]
    Intent --> Interpolation[各向异性约束插值 (Constrained IDW)]
    Interpolation --> Raster[标量网格场 (Scalar Grid)]
    
    Raster --> VectorPipeline[SingleFactorPipeline (矢量化处理)]
    VectorPipeline --> Contours[光滑等值线 (LineString)]
    VectorPipeline --> FaciesPoly[相带多边形 (Polygon + 拓扑自愈)]
    
    Contours --> MapComposer[Map Composer (排版引擎)]
    FaciesPoly --> MapComposer
    
    subgraph LayoutElements ["标准化地图整饰要素"]
        Title[主标题 + 工区层位标头]
        NorthArrow[真北指北针]
        ScaleBar[动态线段比例尺]
        Legend[动态相带与色阶图例]
        Grid[投影经纬网格 (Graticule)]
        TimeScale[国际地质年代对照表]
    end
    
    LayoutElements --> MapComposer
    MapComposer --> Export[出版级矢量交付物 (SVG / PDF / 印刷出图)]
```

---

## 2. 单因素图与综合编图当前支持状态

| 编图要素 / 环节 | 传统手动模式 | Paleo Workbench 自动化管线 | 评估结论 |
|---|---|---|---|
| **插值网格生成** | 手工配置网格间距与搜索半径 | 基于工区边界与井网密度自适应推断行列数与断层遮挡关系 | 优秀 |
| **等值线追踪** | 离线软件生成后手动导入 CAD | `extract_grid_contours` 自动提取光滑闭合等值线矢量图层 | 优秀 |
| **沉积相带面构建** | 人工勾绘多边形，极易产生自相交与重叠 | `extract_facies_polygons` 自动分级提取相带面并自动闭合拓扑 | 优异 |
| **拓扑自愈与共边校验** | 人工肉眼比对节点 | `repair_invalid_geometry` 自动消除自相交（Bow-tie）与悬挂节点 | 优异 |
| **地图版式整饰** | 手动在 Illustrator / CorelDraw 中拼贴 | `MapCompositionDocument` 与 `MapComposerRenderer` 一键自动排版 | 优秀 |
| **图例与比例尺联动** | 手动绘制色块与比例尺刻度 | 根据主图视口范围（Extent）与色阶自动计算比例尺与图例条目 | 优异 |

---

## 3. Map Template Engine 架构与规范

### 3.1 声明式文档模型 (`MapCompositionDocument`)
- 系统采用类似 QGIS Print Layout 的声明式 JSON 数据结构，将版面上所有元素定义为独立的 `ComposerElement`：
  - `MAIN_MAP`: 主图视口，绑定当前图层快照与图层树可见性。
  - `TITLE`: 自动组装工区名称、目标层位（如“川西坳陷须家河组一段”）与图名（如“砂地比等值线图”）。
  - `NORTH_ARROW`: 自动对齐主图中央子午线或指北偏角。
  - `SCALE_BAR`: 根据主图比例尺（Scale）与投影单位（米/千米）动态计算分段长度。
  - `LEGEND`: 自动提取激活图层的样式渲染器（分类符号/分级色带），渲染出符合行业标准的两列式图例。
  - `TIMESCALE`: 自动附带地层年表柱状图。

### 3.2 矢量输出渲染器 (`MapComposerRenderer`)
- 支持纯矢量 SVG 与高精度 PDF 导出，图元精度达到 $0.1\text{mm}$，完全满足核心期刊出版与生产报告归档标准。

---

## 4. 智能编图系统演进建议

1. **图斑注记智能避让算法 (Label Collision Avoidance)**:
   - 引入改进的退火算法或贪心放置策略，在井名、等值线标注与相带名称密集区域实现自动微调避让，杜绝文字重叠。
2. **多因素综合古地理图智能融合引擎**:
   - 构建多因素决策树矩阵（如：砂地比 $>0.5$ 且 泥岩颜色=红褐 $\rightarrow$ 辨识为水上分流河道），实现多张单因素图向综合沉积相图的自动推理合成。
3. **交互式拖拽排版对话框 (`MapComposerDialog`)**:
   - 在 Qt 前端封装可视化排版画布，支持用户自由缩放、微调各整饰要素位置并即时预览。
