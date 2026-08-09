# Composite 自由图形(Free Graphics)设计规格

日期:2026-08-04 · 状态:已获用户逐节批准 · 来源:Phase-2 follow-up Candidate 3(Phase-3 范围)

## 1. 需求(用户已确认的边界)

1. **元素范围(全集)**:文本、箭头/折线、矩形、椭圆、多边形、自由手绘线、图片/logo、指北针、比例尺,共 9 种纸面注释 item。
2. **编辑交互**:放置 / 移动 / 手柄缩放 / 删除 + 属性编辑(描边色、填充色、线宽 mm、字号 mm、文本内容、比例尺分母)。
3. **持久化**:自由图形随 `plots/<id>.json` 持久化(schema v4);**一并修复面板布局不保存的缺口**(交互添加/拖动面板的 `rect_mm` 目前不落盘,拖完即丢)。
4. **架构归属**:geoviz cartography 包承载全部图形机制;宿主 `well-log-engine/apps/wellplot-desktop/well_log_workstation` 只做持久化与窗口接线(方案 A,已批准)。

## 2. 架构总览

```
geo-viz-engine (packages/geoviz_paleo_map/geoviz_paleo_map/cartography/)
├── items/free/            # 9 种 FreeGraphicsItem 子类(新增)
├── items/base_item.py     # LayoutGraphicsItem —— 补真实 resize 手柄逻辑
├── tools(并入 window.py/scene.py)  # 放置模式状态机
├── sidebar(并入 window.py)         # 选中项属性面板
└── window.py              # CartographyLayoutWindow 新增公开 API

paleo-workbench (well-log-engine/apps/wellplot-desktop/well_log_workstation/)
├── plot_document.py       # schema v4: free_graphics 字段
├── composite_view.py      # 保存布局入口 + 恢复接线 + 工具条
└── shell.py               # Ctrl+S 快捷键(可选挂载点)
```

**关键既有事实(探索已核实)**:

- `PaperGraphicsScene` 1 scene unit = 1 mm;`sceneRect = paper_rect`(`cartography/scene.py:43-49`)。
- 导出走 `scene.render`(PDF/SVG/PNG),新 QGraphicsItem 子类 **addItem 即自动进入三种导出,零导出改动**。
- 现有 item 均为 `LayoutGraphicsItem` 子类(FigurePanel/TitleBlock/Legend);8 个缩放手柄**只有绘制没有逻辑**(`base_item.py:23-40`)。
- 无工具/模式架构(裸 QGraphicsView"选中即移动");无属性编辑 UI;模板预设 `scene.clear()`(`templates.py:12`)。
- 宿主目前取 `win._view`(`composite_view.py:100`)、`window._scene`(`export_dispatch.py:242`)私有属性 —— 本期以公开 API 取代。
- 持久化缺口:`create_composite_plot` 只在创建时写盘一次;交互添加/拖动面板无任何保存路径。

## 3. geoviz 侧组件设计

### 3.1 item 体系(`cartography/items/free/`)

基类 `FreeGraphicsItem(LayoutGraphicsItem)`:统一 `id`(uuid4)、`kind`、`to_record()`/`from_record()`、选中装饰。九种:

| item | kind | 几何(mm) | 特有属性 |
|---|---|---|---|
| `FreeTextItem` | `text` | `(x, y)`,可选 `w`(折行宽) | `text`、`font_mm`、`align`(left/center/right,默认 left) |
| `FreeArrowItem` | `arrow` | `points: [[x,y]…]`(≥2 点) | 箭头大小 `head_mm`(默认 3) |
| `FreeRectItem` | `rect` | `(x, y, w, h)` | — |
| `FreeEllipseItem` | `ellipse` | `(x, y, w, h)` | — |
| `FreePolygonItem` | `polygon` | `points`(闭合) | 填充色(默认可空) |
| `FreehandItem` | `freehand` | `points`(开放,放置时鼠标拖出) | — |
| `FreeImageItem` | `image` | `(x, y, w, h)` | `path`(工区相对路径) |
| `NorthArrowItem` | `north_arrow` | `(x, y, w, h)` | — |
| `ScaleBarItem` | `scale_bar` | `(x, y, w, h)` | `denominator: int`(如 5000 表 1:5000) |

公共样式:`stroke`(hex,默认 `#000000`)、`fill`(hex 或 null,默认 null)、`width_mm`(默认 0.3)。

- **字号单位**:一律以 mm 存储与编辑(纸面交付物直觉单位);绘制时按 1 unit = 1 mm 换算 QFont 像素(解决 `annotation_item.py` 先例的像素字体与纸面坐标不一致问题)。
- **指北针/比例尺绘制**:借鉴 `geoviz_paleo_map/layers/north_arrow.py:13`、`scale_bar.py:30` 的画法,改造为纸面固定 mm 尺寸;比例尺长度由 `denominator` 与 w 共同决定标注文字。

### 3.2 真实 resize(`items/base_item.py`)

- 在 `LayoutGraphicsItem` 实现手柄命中(mousePress 命中 8 手柄之一)+ 拖动映射(mouseMove 按角/边更新几何)+ 释放提交;rect 类 item 改 `setRect`,points 类 item 按包围盒仿射映射。
- **面板 item 同步受益**:`FigurePanelGraphicsItem` 的 `rect_mm` 由此可被用户真正调整 —— 这是面板布局持久化修复的前置。

### 3.3 工具模式(放置状态机)

- 窗口工具栏新增互斥模式组:`选择 / 文本 / 箭头 / 矩形 / 椭圆 / 多边形 / 手绘 / 图片 / 指北针 / 比例尺`。
- 放置模式下的鼠标协议:点击类(文本/指北针/比例尺/图片)单击放置默认尺寸;拖拽类(矩形/椭圆/箭头/手绘)按下-拖动-释放成形;多边形为多点连击+双击/Enter 闭合;Esc 或点"选择"回到选择模式。
- 图片放置弹 `QFileDialog` 选图;geoviz 侧 `FreeImageItem` 只持有图片源路径与像素,**不感知工区** —— 复制入工区资产目录是宿主职责(见 §4.3)。

### 3.4 属性面板(sidebar)

- sidebar 新增"选中项属性"区:`QFormLayout` + `QLineEdit`(文本/颜色 hex)/ `QDoubleSpinBox`(线宽 mm、字号 mm、比例尺分母)/ `QComboBox`(对齐)。
- 场景选中变化 → 面板刷新;编辑 → 即时写回 item。删除:Del 键 + 右键菜单(编辑属性入口同置,`annotation_item.py:85-110` 先例)。

### 3.5 序列化(跨仓契约,冻结)

每 item `to_record() -> dict`,纯 JSON:

```json
{
  "id": "uuid4-string",
  "kind": "text|arrow|rect|ellipse|polygon|freehand|image|north_arrow|scale_bar",
  "style": {"stroke": "#000000", "fill": null, "width_mm": 0.3, "font_mm": 3.5},
  "geometry": {"x": 20.0, "y": 15.0, "w": 60.0, "h": 12.0, "points": [[x, y]]},
  "props": {"text": "…", "path": "plots/assets/<plot_id>/<uuid>.png", "denominator": 5000, "head_mm": 3.0, "align": "left"}
}
```

- `geometry` 按 kind 取子集:点类用 `points`,框类用 `x/y/w/h`,文本用 `x/y`(+可选 `w`)。
- `from_record(record) -> item | None`:未知 `kind`、几何缺失/越界、样式非法 → 返回 None(宿主侧计数并提示)。

### 3.6 `CartographyLayoutWindow` 公开 API(新增)

- `add_free_graphic(record: dict) -> str | None`(返回 item id;失败 None)
- `free_graphics() -> list[dict]`(场景中全部自由图形的 to_record)
- `remove_free_graphic(item_id: str) -> bool`
- `panels() -> list[dict]`(每个面板的 `{plot_id, slot, source_plot_type, rect_mm, render_mode}` 读回)
- (宿主停用 `win._view` / `window._scene` 私有属性;`CompositeView` 改经公开方法。)

## 4. 宿主侧与持久化设计

### 4.1 schema v4(`well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py`)

- `PlotDocument` 新增 `free_graphics: list[dict] = field(default_factory=list)` —— kind 判别式 dict,**不**为 9 种各建 typed dataclass(校验/兜底在 geoviz `from_record` 边界,与 PanelRef 宽松解析先例一致)。
- `PLOT_SCHEMA_VERSION = 4`;升级链追加 `version == 3` 分支 `setdefault("free_graphics", [])`(照抄 :104-113 模式);仅 `type == "composite" or doc.free_graphics` 时写入(与 panels 同款条件)。
- `revision` 语义不变(ADR 0051):保存布局经 `save_plot_document` 自动 bump。

### 4.2 保存路径(一个入口,覆盖自由图形 + 面板布局)

CompositeView 工具条新增"保存布局"按钮(+Ctrl+S):

1. `window.panels()` 读回 → 回写 `doc.panels` 的 `rect_mm`(按 `plot_id + slot` 匹配;交互新增面板追加进列表;场景中已不存在的面板移除);
2. `window.free_graphics()` → `doc.free_graphics`;
3. `save_plot_document(workspace, doc)` 落盘。

**显式保存,不做拖拽自动保存**:拖拽高频、自动写盘太热;显式语义可预期,符合 ADR 0025 "区分未提交修改与项目保存状态"。`_on_add_panel` 不再即时保存(统一由该入口覆盖)。

### 4.3 图片资产

- **职责切分**:geoviz 侧 `FreeImageItem` 放置时只记录图片源路径(绝对路径)并加载像素,不感知工区;**复制入工区是宿主在保存时的动作**。
- **保存时**(§4.2 第 2 步内):宿主检查 `free_graphics()` 记录,凡 `kind == "image"` 且 `props.path` 不是工区相对路径(`plots/assets/` 前缀)的,把源文件复制为 `plots/assets/<plot_id>/<uuid>.png` 并把记录中的 `path` 改写为该相对路径,再写入 `doc.free_graphics`。
- **恢复时**:相对路径相对工区根解析;文件缺失 → 占位矩形 + 文件名文字,不阻断其他 item 重建。

### 4.4 恢复路径

`_show_composite`:现有逐面板 `add_panel_ref` 之后,按 `doc.free_graphics` 逐条 `add_free_graphic`;凡 `add_free_graphic` 返回 None 的记录计数并在状态栏提示"N 条图形记录无法恢复"。模板预设清空场景后,按文档重放重建(切换模板 = 放弃未保存布局,保存入口先行)。

## 5. 错误处理

| 场景 | 行为 |
|---|---|
| 未知 kind / 记录畸形 | `from_record` 返回 None,跳过 + 状态栏计数提示 |
| 几何越出 paper_rect | 放置与恢复时钳制到纸面 |
| 图片文件缺失 | 占位矩形 + 文件名,不中断恢复 |
| schemaVersion ∉ {1..4} | `WorkspaceError`(现状不变) |
| 保存时工作区/文档缺失 | 沿用 `save_plot_document` 现有异常,按钮处弹窗 |

## 6. 测试

- **geoviz**(其 pytest infra;父仓 required 套件亦覆盖):每种 item `to_record`/`from_record` round-trip(几何+样式无损);未知 kind 容错;resize 手柄映射单测;放置工具 QTest 冒烟(offscreen)。
- **宿主**:schema v4 round-trip + v3 旧文件兼容(镜像 `well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_revision.py` 模式);保存布局写回 rect_mm + free_graphics;按记录恢复重建(offscreen Qt);图片 asset 写盘/读回/缺失容错。
- 本地无 PySide6:`py_compile` + 纯 Python 序列化逻辑本地跑,Qt 行为以 CI 为准(本会话既定验证模式)。

## 7. PR 切分(顺序依赖)

- **PR-A(geo-viz-engine)**:free item 体系 + resize 基础设施 + 工具模式 + 属性面板 + 公开 window API + 序列化契约。
- **PR-B(paleo-workbench)**:gitlink bump + schema v4 + FreeGraphic 持久化 + CompositeView 保存/恢复 + 面板布局保存修复 + 工具条入口。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 模板 `scene.clear()` 清空用户放置项 | 文档为准重放重建;切换模板视为放弃未保存布局 |
| QFont 像素 vs mm 单位错位 | 字号一律 mm 存储,绘制换算 |
| 跨仓契约漂移 | record dict schema 本规格冻结(§3.5),PR-B 照契约实现 |
| 工作量(9 item + 交互架构) | item 共享基类与序列化模式,单个绘制 <50 行;分两 PR 交付 |
| 面板拖拽后未保存即关 | 显式保存入口;后续可加快捷键与脏标记提醒(见 §9) |

## 9. 明确不做(Out of scope)

- 规范符号库(`svg_output/` Q/HS 1011—2016 符号)的运行时加载 —— 后续独立项。
- 辅助线/网格吸附/对齐工具(`scene.py` 声称的 grid snapping 未实现,本期不补)。
- 非打印项过滤机制(边距虚线照进导出的现状不改)。
- 撤销/重做栈、脏标记与关闭提醒(可后续增强)。
- 面板 z-order 管理、组合/对齐分布操作。
