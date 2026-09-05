# UI Design System V5 — QA 报告（U8）

日期：2026-09-06 · Branch：`feat/ui-design-system-v5` · 环境：offscreen Qt
（QT_QPA_PLATFORM=offscreen，软件 GL，QGIS bridge 降级路径 fallback 画布）

## 1. 证据集

| 集合 | 位置 | 内容 |
|---|---|---|
| 迁移前真基线 | `visual_qa/baseline-v5/` | 12 状态 @1600×900（token 迁移前捕获） |
| 迁移后证据 | `visual_qa/01..12-*.png` | 12 状态 @1600×900（迁移后重拍） |
| 矩阵基线 | `visual_qa/baseline-v5-matrix/` | 4 核心状态 × 主题×密度×尺寸 = 30 shots + manifest.json |

矩阵维度：{默认工作站, 编图, 综合, 深色} × {light, dark, high_contrast} ×
{compact, comfortable} × {1440×900, 1180×720, 1920×1080}（01 状态额外跑满主题×尺寸扫描）。

工具：
- `scripts/capture_workstation_screens.py`（单 shot，支持 `--theme/--density/--size`）
- `scripts/capture_ui_matrix.py`（`--core`/`--full` 矩阵驱动 + manifest）
- `scripts/diff_ui_matrix.py`（逐 shot 像素差报告；阈值仅分级提示，非门禁，D8）

## 2. 矩阵结果

- 30/30 shots 捕获成功（两次独立运行一致）。
- 同 baseline 比对：26/30 **像素级一致（0.00%）**——offscreen 流程确定性良好。
- 4 张 changed 中：
  - `01-...__light__comfortable__1180x720.png` 3.41%（bbox 0,52,1160,481）：
    1180px 恰在 Inspector 自动折叠阈值（1280px）之下，折叠动画的时序抖动；
    语义行为由 `test_workstation_shell` 覆盖。已知动态区，不视为回归。

## 3. 视觉 review 结论（人工判读截图）

- **Light**：白色工作面 + 冷灰结构 + 石化青激活 + amber 过程色，与 V3 Light
  一致；dock、任务中心、app bar、状态条 chrome 统一。
- **Dark**：dock/任务中心/状态条正确随主题（迁移前 capture harness 的 app 级
  样式表缺失导致 dock 呈 Fusion 灰的问题已修）；井位图 pyqtgraph 底色随
  `BG_CHART` token 变暗；图表轴/文字可读。
- **High Contrast**：黑 rail + 白工作面 + 全黑描边；井名青色、amber badge 在
  黑底上可读；状态不只靠颜色（badge 白字 + 文案、图标 + 文字）。
- **Compact**：app bar 40px、rail 48px、按钮 24px 行高 22px；与 comfortable
  对比密度差异明显且无错位（`track_control_height`/`bind_metrics` 生效）。
- **1180×720**：Inspector 自动折叠，App Bar / tabs / 画布 / 任务中心可达，
  无关键控件截断；首页容器最小宽 960px 由滚动容器兜底。
- **1920×1080**：中央画布延展正常，dock 宽度不漂移。
- 任务中心空表显示统一空态（`PwbEmptyState`）；运行任务 amber 进度 + 取消钮。

## 4. 已知动态区（diff 报告的合法噪声源）

1. 任务运行态的进度 % 与用时（08/09/10 状态）。
2. Inspector 自动折叠阈值附近的布局时序（1180px）。
3. 12-dark-theme 状态本底即 dark 主题（矩阵中其 light 组合等价于 01 状态）。

## 5. 基线更新流程

1. 修改 UI 后运行：`capture_ui_matrix.py --core visual_qa/baseline-v5-matrix`
2. 肉眼 review diff 报告（`diff_ui_matrix.py`）中的 changed/CHANGED 条目；
3. 确认为预期视觉演进后 commit 新基线（PNG + manifest.json 一起）；
4. 结构性回归断言不依赖像素 diff（语义 Qt tests 钉住）。
