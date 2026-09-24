# Paleo Workbench：按设计稿精确还原五工作区

日期：2026-09-24。状态：**实施规格（geometry authority）**——以
[`../qt-ribbon-workspaces-2026-09-21/`](../qt-ribbon-workspaces-2026-09-21/README.md)
五张设计稿为逐区域还原目标。上一版实现受既有源程序结构影响，区域
组成与设计稿有偏差；本轮按稿重建工作区内部。

## 总原则（用户指令）

- **精确还原设计稿**的层次与面板组成；设计稿的控件几何是目标布局，
  示意数据/文案仍以真实权威为准。
- **编图相关能用 QGIS 部件的直接用 QGIS**：`QgsMapCanvas`、
  `QgsLayerTreeView`、`QgsMessageBar`、`QgsBrowserTreeView`、
  `QgsDockWidget` 惯例、状态栏坐标/比例尺部件。
- **没有的内容先占空**：占位面板写明来源，不伪造功能。

## 恒定壳层 chrome（所有页相同）

```
标题栏
RibbonBar：导航行 [文件][数据管理][1智能预测][2约束与单因素][3综合编图][验证]
           ␣[搜索命令 Ctrl+K][任务][Agent][折叠]；命令带随页签切换
层位条（ws1-4）：‹ › C3 [C6] D53 D61 D62 D63 D71 D72 —— target_horizon 权威
WorkstationFrame：
  左 dock  资源管理器（rail + 工程树）＋ 每工作区下部面板（工作流步骤等）
  中央    每工作区固定复合页（见下）
  右 dock  每工作区面板列
  底 dock  任务 | 日志 | 验证记录
QStatusBar：X/Y 坐标 · 比例尺 · CRS · 当前层位
```

## 页 0 — 数据管理

| 区域 | 设计稿内容 | 部件 |
|---|---|---|
| Ribbon | 数据导入 / 整理 / 质量检查 / 版本与关联 / 输出 | 现有分组 |
| 左 | 资源管理器树（概览/井数据/地震数据/层位/解释要素/约束与单因素图/综合编图） | 现有 nav 树 |
| 中央上 | 搜索行 + 类型/状态过滤 + 资产表（名称/类型/所属对象/层位/版本/状态/修改时间/大小） | 现有资产表 |
| 中央下 | tabs：数据预览 / 版本历史 / 关联关系 | 现有页 |
| 右 | 数据属性（键值）+ 数据血缘·处理流程（纵向流程） | 现有属性/血缘面板 |

## 页 1 — 智能预测

| 区域 | 设计稿内容 | 部件 |
|---|---|---|
| Ribbon | 输入与模型 / 预测运行 / 叠加对照 / 结果 | 现有分组 |
| 左下 | 智能预测工作流（1 相团几何检查…5 结果评估与导出） | 现有步骤面板 |
| 中央上 | `QgsMapCanvas` + `QgsMessageBar` + 画布装饰（指北针/比例尺/图例，`map_chrome_painter`） | 共享会话画布 |
| 中央下 | **井震两联并排**（非 tab）：左 地震剖面窗格（标题行：剖面选择 + 显示:振幅 + 色标:seismic + 属性 + 联动 checkbox），右 测井轨道窗格（标题行：井名 + 联动 checkbox） | `SeismicSliceWidget`；测井轨道占空（well_log_viewer optional-absent） |
| 右 | tabs：图层 / 预测参数 / 样式；图层 tab = `QgsLayerTreeView`（主要图层 + 参考图层复选） | 图层树真件；参数/样式占空 |

## 页 2 — 约束与单因素

| 区域 | 设计稿内容 | 部件 |
|---|---|---|
| Ribbon | 约束编辑 / 插值计算 / 连井分析 / 等值线 / 结果 | 现有分组 |
| 左下 | 约束分析 5 步 + 剖面设置（剖面井复选 A3/A1/A12/A10/A7 + 显示设置：地层格架/沉积相/测井曲线） | 步骤面板已有；剖面设置占空或接 viz_b 选井 |
| 中央上 | `QgsMapCanvas` | 共享会话画布 |
| 中央下 | **连井剖面整宽窗格**（标题行：连井剖面（与地图联动）） | viz_b CrossWell 真件 |
| 右 | tabs：约束 / 单因素 / 参考；约束=要素复选（物源线/展布线/井位及井名/研究区边界），单因素=图层清单（砂体厚度图(当前)…含砂率图），参考=岩性图例+界面线图例 | 结构按稿；内容占空/接既有清单 |

## 页 3 — 综合编图

| 区域 | 设计稿内容 | 部件 |
|---|---|---|
| Ribbon | 相界编辑 / 参考图 / 图件整饰 / 版式 / 输出 | 现有分组 |
| 左下 | 编图工作流（1 单因素图检查…5 成果导出） | 现有步骤面板 |
| 中央上 | `QgsMapCanvas` + 图例/指北针/比例尺装饰 | 共享会话画布 |
| 中央下 | **单因素参考·联动显示** 缩略图带（厚度图/砂地比图/坡度图/最近井距离图/预测置信度 5 卡） | `FactorReferenceStrip` 已有；空时按稿列占位卡 |
| 右 | tabs：编图图层 / 图件整饰 / 版式输出；编图图层=`QgsLayerTreeView` + 参考图透明度滑条组；版式输出=`LayoutEditorPanel` 或占空 | 图层树真件 |

## 页 4 — 验证

| 区域 | 设计稿内容 | 部件 |
|---|---|---|
| Ribbon | 对象与基准 / 联动对比 / 检查 / 复核 / 报告 | 现有分组 |
| 左下 | 验证设置（空间对齐/井点符合/层位一致/输入版本 复选） | 现有 |
| 中央 | 上排 QSplitter(H)：只读地图 | 地震剖面对照（两套解释）；中排 检查项目表；下排 井验证对比（深度/解释/预测/结果） | `ValidationWorkspacePage` 已有此骨架 |
| 右 | 验证结果表（通过/待复核/未执行 计数 + 对象/检查项/状态）+ 选中问题详情（定位到视图/备注/结论） | 现有复核详情面板 |

## 实施边界

- 中央画布为**共享会话画布**：各图页经 `take_canvas` 槽位收编同一
  `QgsMapCanvas`（切页 re-parent，不切实例）。
- 中央下排窗格为**页内固定复合**（设计稿的窗格是内容区，不是窗口级
  dock）；右列/左下仍走 dock。
- 占位面板统一 `PlaceholderPane`：标题行 + 来源说明 + 灰底，绝不伪造
  已实现外观。
- 阶段权威不变：进入数据管理/验证不写 `mapping_stage`；三科学页仍投影
  `applyStageValue` 唯一写路径。
- 面板开关、布局持久化、DPI 缩放沿用 WorkstationFrame/ui_ribbon 既有
  机制，不造第二套。

## 落地修复记录（2026-09-24 实施中发现并修掉的缺陷）

- **`make_stage_pane` 栈页必须是外框**：helper 返回内容宿主而调用方曾把
  host 入栈 → 题头框沦为游离子控件叠在栈角（ws2 题头重影）。现为
  `make_stage_pane(title, name, stack)` 内部 `addWidget(frame)`。
- **dock 收编必须在创建点旁**：`constraint_panel`/`composite_layer` 的
  `adopt_dock` 曾寄在 `installStageFlow`（受 `PWB_WITH_STAGE_FLOW` 门控），
  使无 stage-flow 的壳层构建静默缺右栏 tab。已上移到
  `install_conv27_surface`（dock 创建点）；`platform_ribbon_visual` 补上
  `PWB_WITH_CONV_27=1` 与 `Pwb::UiWorkbench` 链接，截图与产品二进制一致。
- **`DataReaderPanel::loading_page_` 漏入栈**：`setCurrentWidget` 对非栈内
  widget 静默无效，游离页在 ws0 数据预览区与标题重影。已 `addWidget` 入栈，
  loading 态首次真正可用。
- **CAD dock 漂屏**：`QgsAdvancedDigitizingDockWidget` 被 parent 到普通
  canvas（非 QMainWindow），show() 后以浮窗子控件叠在画布上缘。已重父进
  canvas 下永隐藏的容器（`CadDockHiddenHome`），对象存续、永不绘制。
